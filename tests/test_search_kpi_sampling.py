"""Shared acquisition preserves trustworthy modes and immutable request evidence."""
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.catalog import SearchAnalysis
from backend.app.config import Settings
from backend.app.contracts import SearchState
from backend.app.db import Database, SearchRequest
from backend.app.evaluation_store import ReplayManifest
from backend.app.feedback import ReviewSample
from backend.app.main import create_app
from backend.app.review_workflow import acquire_batch, list_samples
from backend.app.routing import OTPAdapter, OTPSettings
from tests.test_feedback import request_fixture
from tests.test_phase2_core import setup


def test_normal_and_advanced_api_requests_share_deduplicated_review_queue(setup, monkeypatch):
    class Semantic:
        def __init__(self, *args):
            pass

        async def retrieve(self, text, eligible):
            return {'status': 'ok', 'property_ids': eligible, 'retrieved_count': len(eligible)}

    monkeypatch.setattr('backend.app.integration.SemanticService', Semantic)
    monkeypatch.setenv('LLM_ENABLED', 'false')
    monkeypatch.setenv('AI_JUDGE_ENABLED', 'false')
    monkeypatch.setenv('REVIEW_API_TOKEN', 'shared-review-test-token-only')
    db, geo, _ = setup
    app = create_app(Settings(), database=db, geo=geo, adapter=OTPAdapter(OTPSettings()), start_worker=False)
    state = SearchState(dataset_version='test', property={'max_monthly_rent_toman': 15}).model_dump(mode='json')
    headers = {'x-review-token': 'shared-review-test-token-only'}
    with TestClient(app) as client:
        requests = {}
        sample_ids = {}
        for mode in ('normal', 'advanced'):
            body = {'state': state}
            path = '/api/searches'
            if mode == 'advanced':
                path = '/api/advanced/searches'
                body.update(semantic_text='apartment', confirmed=True)
            submitted = client.post(path, json=body)
            assert submitted.status_code == 201, submitted.text
            result = submitted.json()
            for _ in range(40):
                if result['semantic']['status'] != 'pending':
                    break
                time.sleep(.01)
                result = client.get('/api/searches/' + result['request_id']).json()
            assert result['completion_status'] == 'complete'
            assert result['search_mode'] == mode
            assert result['semantic']['status'] == ('ok' if mode == 'advanced' else 'not_requested')
            requests[mode] = result
            sampling = {'request_id': result['request_id'], 'limit': 1}
            selected = client.post('/api/review/sample', json=sampling)
            assert selected.status_code == 200, selected.text
            sample_ids[mode] = selected.json()['samples'][0]['sample_id']
            assert client.post('/api/review/sample', json=sampling).json()['samples'] == selected.json()['samples']

        queue = client.get('/api/internal/reviews', headers=headers).json()['samples']
        assert len(queue) == 2
        assert len({row['sample_id'] for row in queue}) == 2
        assert len({row['snapshot_id'] for row in queue}) == 2
        for mode, result in requests.items():
            filtered = client.get('/api/internal/reviews', params={'mode': mode}, headers=headers).json()['samples']
            assert len(filtered) == 1
            row = filtered[0]
            assert row['sample_id'] == sample_ids[mode]
            assert row['request_id'] == result['request_id']
            assert row['snapshot_id'] == result['snapshot_id']
            assert row['actor_kind'] == result['actor_kind'] == 'demo'
            assert row['evidence']['search_mode'] == mode
            assert row['evidence']['facts']
            assert all(ref.startswith('property:p1:') for ref in row['evidence']['facts'])
            with db.session() as session:
                manifest = session.get(ReplayManifest, row['evidence']['manifest_id'])
                assert manifest.request_id == result['request_id']
                assert manifest.payload['snapshot_id'] == result['snapshot_id']
                assert manifest.payload['mode'] == mode

        assert client.get('/api/internal/reviews').status_code == 403
        assert client.post('/api/internal/acquire', json={'request_ids': [requests['normal']['request_id']]}).status_code == 403
        assert client.post('/api/internal/reviews/' + sample_ids['normal'] + '/claim', json={'revision': 0}).status_code == 403
        assert client.post('/api/internal/reviews/' + sample_ids['normal'] + '/annotations', json={
            'idempotency_key': 'unauthorized-review', 'revision': 0,
        }).status_code == 403


def test_acquisition_keeps_ambiguous_historical_mode_unknown_without_backfill(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "historical-review.sqlite"}')
    db.migrate()
    rid = request_fixture(db)
    with db.session() as session:
        before = session.get(SearchRequest, rid).state
        assert session.get(SearchAnalysis, rid) is None
    selected = acquire_batch(db, [rid], batch_size=3)
    assert len(selected['sample_ids']) == 3
    assert not list_samples(db, 'reviewer', mode='normal')
    assert len(list_samples(db, 'reviewer', mode='unknown')) == 3
    assert not acquire_batch(db, [rid], batch_size=3)['sample_ids']
    with db.session() as session:
        assert session.get(SearchRequest, rid).state == before
        assert session.get(SearchAnalysis, rid) is None
        assert len(list(session.scalars(select(ReviewSample)))) == 3
