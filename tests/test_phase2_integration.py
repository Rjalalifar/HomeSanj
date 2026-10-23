import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import SearchState
from backend.app.db import Database
from backend.app.main import create_app
from backend.app.routing import OTPAdapter, OTPSettings
from tests.test_search import TinyGeo, listing


def client_app(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "integration.sqlite3"}')
    db.migrate()
    db.insert_listings([listing('p1', .5, 10, True), listing('p2', 1.5, 100, False)])
    return create_app(Settings(), database=db, geo=TinyGeo(), adapter=OTPAdapter(OTPSettings()), start_worker=False)


def test_qdrant_candidates_cannot_bypass_filters_and_scope_is_exhaustive(tmp_path, monkeypatch):
    class Semantic:
        def __init__(self, *args):
            pass
        async def retrieve(self, text, eligible):
            await asyncio.sleep(.01)
            assert eligible == ['p1']
            return {'status': 'ok', 'property_ids': ['p2', 'invented', 'p1'], 'retrieved_count': 3, 'coverage': 1}
    monkeypatch.setattr('backend.app.integration.SemanticService', Semantic)
    with TestClient(client_app(tmp_path)) as client:
        state = SearchState(dataset_version='test', property={'max_monthly_rent_toman': 20}).model_dump(mode='json')
        response = client.post('/api/advanced/searches', json={'state': state, 'semantic_text': 'خانه با بودجه محدود', 'confirmed': True})
        assert response.status_code == 201, response.text
        result = response.json()
        for _ in range(30):
            result = client.get('/api/searches/' + result['request_id']).json()
            if result['semantic']['status'] != 'pending':
                break
            time.sleep(.02)
        assert result['semantic']['status'] == 'ok', result['semantic']
        assert result['candidate_count'] == 1
        assert [row['property']['property_id'] for row in result['results']] == ['p1']
        assert result['semantic']['structured_coverage'] == 1
        explanation = client.post(f"/api/searches/{result['request_id']}/explanation", json={'use_ai': False})
        assert explanation.status_code == 200
        assert explanation.json()['recommended_property_id'] == 'p1'


def test_semantic_outage_keeps_normal_and_advanced_structured_results(tmp_path, monkeypatch):
    class Down:
        def __init__(self, *args):
            pass
        async def retrieve(self, *args):
            raise ConnectionError('offline fixture')
    monkeypatch.setattr('backend.app.integration.SemanticService', Down)
    with TestClient(client_app(tmp_path)) as client:
        state = client.get('/api/state/default').json()
        normal = client.post('/api/searches', json={'state': state}).json()
        assert normal['semantic']['status'] == 'not_requested'
        advanced = client.post('/api/advanced/searches', json={'state': state, 'semantic_text': 'خانه', 'confirmed': True}).json()
        for _ in range(30):
            advanced = client.get('/api/searches/' + advanced['request_id']).json()
            if advanced['semantic']['status'] != 'pending':
                break
            time.sleep(.02)
        assert advanced['semantic']['status'] == 'degraded'
        assert advanced['result_count'] == normal['result_count'] == 2
        assert not advanced['evaluated_count']


def test_short_concurrent_sqlite_writes_keep_distinct_snapshots(tmp_path):
    with TestClient(client_app(tmp_path)) as client:
        state = client.get('/api/state/default').json()
        def submit(_):
            response = client.post('/api/searches', json={'state': state})
            assert response.status_code == 201, response.text
            return response.json()['snapshot_id']
        with ThreadPoolExecutor(max_workers=3) as pool:
            snapshots = list(pool.map(submit, range(6)))
        assert len(set(snapshots)) == 6


def test_unavailable_routes_are_not_qualified_results(tmp_path):
    with TestClient(client_app(tmp_path)) as client:
        state = client.get('/api/state/default').json()
        state['accessibility'] = None
        state['travel'].update(destination={'latitude': 1, 'longitude': 1, 'confirmed': True}, date='2026-10-20', time='08:00:00')
        response = client.post('/api/searches', json={'state': state}).json()
        assert response['completion_status'] == 'routing_unavailable'
        assert response['results'] == []
        assert response['unverified_count'] == 2
        assert all(row['selected_itinerary'] is None for row in response['unverified_results'])
