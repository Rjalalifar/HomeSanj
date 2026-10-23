"""Offline isolation, restart recovery, paired experiments and release controls."""
import asyncio
import json
import pytest
from sqlalchemy import select
from backend.app.db import Database
from backend.app.evaluation_store import OfflineJob
from backend.app.evaluation_replay import freeze_manifest, digest
from backend.app.evaluation_experiments import compare, release, latest_release
from backend.app.offline_evaluation import OfflineWorker, enqueue, enqueue_judge, blind_packet, judge_sample
from backend.app.llm import AvalAIProvider, ProviderError
from backend.app.feedback import SamplingInput, ReviewSample, ReviewAnnotation, select_review_samples
from tests.test_feedback import request_fixture
from backend.app.evaluation import corpus


@pytest.fixture
def db(tmp_path):
    database = Database(f'sqlite:///{tmp_path / "offline.sqlite"}')
    database.migrate()
    return database


def test_crashed_job_lease_recovers_without_duplicate_enqueue(db):
    job_id = enqueue(db, 'export', {})
    assert enqueue(db, 'export', {}) == job_id
    first, second = OfflineWorker(db, None), OfflineWorker(db, None)
    assert first.claim(now=100).job_id == job_id
    assert second.claim(now=101) is None
    assert second.claim(now=401).job_id == job_id
    with db.session() as session:
        assert session.get(OfflineJob, job_id).attempts == 2


def test_disabled_judge_is_deferred_without_network(db, monkeypatch):
    monkeypatch.setenv('AI_JUDGE_ENABLED', 'false')
    rid = request_fixture(db)
    samples = select_review_samples(db, 'owner', SamplingInput(request_id=rid))
    provider = AvalAIProvider(db)
    job_id = enqueue_judge(db, samples['samples'][0]['sample_id'], provider)
    assert asyncio.run(OfflineWorker(db, provider).tick())
    with db.session() as session:
        job = session.get(OfflineJob, job_id)
        assert job.status == 'deferred' and job.result['status'] == 'not_run'
        assert job.attempts == 0


def test_judge_packet_is_blind_and_rejects_invented_evidence(db):
    rid = request_fixture(db)
    sid = select_review_samples(db, 'owner', SamplingInput(request_id=rid))['samples'][0]['sample_id']
    with db.session() as session:
        sample = session.get(ReviewSample, sid)
        packet = blind_packet(sample)
    assert all(key not in json.dumps(packet) for key in ('rank_score', 'owner_session', 'latitude', 'longitude', 'prior_grade'))
    class InvalidProvider:
        models = {'judge': 'fixed-test-model'}
        role_versions = {'judge': '1'}
        calls = 0
        async def complete(self, role, messages):
            self.calls += 1
            return json.dumps({'candidate_id': sample.candidate_id, 'hard_constraint_checks': [],
                'relevance_grade': 3, 'explanation_grounding': 'no_claims', 'evidence_refs': ['invented'],
                'unknown_reasons': [], 'short_reason': 'injection ignored', 'unsupported_claim_ids': []})
    provider = InvalidProvider()
    with pytest.raises(ProviderError, match='validation_error'):
        asyncio.run(judge_sample(db, {'sample_id': sid, 'evidence_hash': digest(packet), 'model': 'fixed-test-model'}, provider))
    assert provider.calls == 2
    with db.session() as session:
        assert not list(session.scalars(select(ReviewAnnotation)))


def test_actual_candidate_config_and_test_scope_rollback(db):
    rid = request_fixture(db)
    manifest = freeze_manifest(db, rid)
    result = compare(db, [manifest['manifest_id']], split='mechanical_demo')
    assert result['status'] == 'insufficient_evidence'
    assert result['cases'][0]['metrics']['baseline']['ndcg_at_5']['value'] is None
    promoted = release(db, result['experiment_id'])
    assert promoted['config'] == {'rent_weight_multiplier': 1.25}
    assert latest_release(db)['config'] == promoted['config']
    release(db, action='rollback')
    assert latest_release(db)['config'] == {}
    with pytest.raises(ValueError):
        release(db, result['experiment_id'], scope='production')


def test_corpus_reuses_at_least_sixty_versioned_existing_cases():
    report = corpus()
    assert report['count'] >= 60 and report['human_gold_count'] == 0
    assert len({r['case_id'] for r in report['cases']}) == report['count']
    assert all(r['synthetic'] and len(r['case_version']) == 64 for r in report['cases'])
