"""Review leases, provenance, immutable history and replay privacy regressions."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from backend.app.db import Candidate, Database
from backend.app.feedback import ReviewSample, ReviewAnnotation, SamplingInput, select_review_samples
from backend.app.review_workflow import claim, annotate, ReviewInput, list_samples, acquire_batch
from backend.app.evaluation_replay import freeze_manifest, replay_manifest
from backend.app.annotation_datasets import export_dataset, import_dataset
from tests.test_feedback import request_fixture


@pytest.fixture
def prepared(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "reviews.sqlite"}')
    db.migrate()
    rid = request_fixture(db)
    selected = select_review_samples(db, 'owner', SamplingInput(request_id=rid))
    return db, rid, selected['samples'][0]['sample_id']


def test_lease_conflict_blind_initial_grade_and_immutable_supersession(prepared):
    db, _, sid = prepared
    first = claim(db, sid, 'alice', 0)
    assert first['initial_blind'] and 'rank_score' not in first['evidence']['frozen_candidate']
    with pytest.raises(HTTPException):
        claim(db, sid, 'bob', 1)
    refs = list(first['evidence']['facts'])[:1]
    a = annotate(db, sid, 'alice', ReviewInput(idempotency_key='grade-first', revision=1, grade=2, evidence_refs=refs))
    assert not next(s for s in list_samples(db, 'alice') if s['sample_id'] == sid)['initial_blind']
    assert next(s for s in list_samples(db, 'bob') if s['sample_id'] == sid)['initial_blind']
    claim(db, sid, 'alice', 2)
    annotate(db, sid, 'alice', ReviewInput(idempotency_key='grade-second', revision=3, grade=3, evidence_refs=refs, supersedes=a['annotation_id']))
    with db.session() as session:
        assert session.get(ReviewAnnotation, a['annotation_id']).annotation_data['grade'] == 2


def test_replay_missing_evidence_and_no_destination_disclosure(prepared):
    db, rid, _ = prepared
    manifest = freeze_manifest(db, rid)
    replay = replay_manifest(db, manifest['manifest_id'])
    assert replay['status'] == 'ok' and replay['network_calls'] == 0
    with db.session.begin() as session:
        session.delete(session.get(Candidate, (rid, 'p1')))
    assert replay_manifest(db, manifest['manifest_id'])['status'] == 'partial_replay'


def test_dataset_roundtrip_does_not_fabricate_human_gold(prepared, tmp_path):
    db, _, sid = prepared
    view = claim(db, sid, 'alice', 0)
    annotate(db, sid, 'alice', ReviewInput(idempotency_key='human-grade-1', revision=1, grade=2,
        evidence_refs=list(view['evidence']['facts'])[:1]))
    report = export_dataset(db, tmp_path / 'datasets')
    assert report['human_real_graded'] == 0
    assert import_dataset(db, report['path'])['duplicates'] == 1
    assert export_dataset(db, tmp_path / 'datasets')['dataset_id'] == report['dataset_id']


def test_acquisition_extends_existing_queue_without_duplicate_samples(prepared):
    db, rid, _ = prepared
    result = acquire_batch(db, [rid])
    assert not result['sample_ids']
    with db.session() as session:
        assert len(list(session.scalars(select(ReviewSample)))) == 3
