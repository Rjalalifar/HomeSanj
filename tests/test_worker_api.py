import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.contracts import SearchInput, SearchState
from backend.app.db import Database, SearchRequest
from backend.app.main import create_app
from backend.app.routing import OTPSettings
from backend.app.search import create_search, read_search
from backend.app.worker import RoutingWorker
from tests.test_search import TinyGeo, listing


class FakeOTP:
    configured = True

    def __init__(self, delay=0):
        self.settings = OTPSettings.from_env()
        self.delay = delay
        self.calls = 0
        self.cancelled_calls = 0

    async def route(self, origin, travel):
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled_calls += 1
            raise
        return {"status": "no_route_returned", "itineraries": [], "raw_response": {"plan": {"itineraries": []}}}


def setup(tmp_path, batch=2, count=5):
    db = Database(f"sqlite:///{tmp_path / 'api.sqlite3'}")
    db.migrate()
    db.insert_listings([listing(f"p{i}", 0.1 + i * 0.1, 10 + i, True) for i in range(count)])
    settings = Settings(batch_limit=batch)
    state = SearchState(
        dataset_version="test",
        travel={"destination": {"latitude": 1.0, "longitude": 1.0, "confirmed": True},
                "date": "2026-01-01", "time": "08:00:00"},
    )
    return db, settings, state


def test_batch_cap_cache_and_resume_preserve_evidence(tmp_path):
    db, settings, state = setup(tmp_path)
    adapter = FakeOTP()
    rid = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    worker = RoutingWorker(db, adapter, settings)
    asyncio.run(worker.run_once())
    result = read_search(db, rid, include_snapshot=True)
    assert result["evaluated_count"] == 2
    assert result["candidate_count"] == 5
    assert result["completion_status"] == "partial"
    assert len(result["evaluations"]) == 2
    assert adapter.calls == 2
    with db.session.begin() as session:
        session.get(SearchRequest, rid).completion_status = "queued"
    asyncio.run(RoutingWorker(db, adapter, settings).run_once())
    assert read_search(db, rid)["evaluated_count"] == 4
    changed = state.model_copy(update={"preference": "lower_rent"})
    rid2 = create_search(db, TinyGeo(), SearchInput(state=changed, parent_request_id=rid), settings, True)
    before = adapter.calls
    asyncio.run(RoutingWorker(db, adapter, settings).run_once())
    assert read_search(db, rid2)["evaluated_count"] == 2
    assert adapter.calls == before


def test_active_cancellation_stops_calls_and_can_resume(tmp_path):
    db, settings, state = setup(tmp_path, batch=3)
    adapter = FakeOTP(delay=1)
    rid = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    worker = RoutingWorker(db, adapter, settings)

    async def scenario():
        pending = asyncio.create_task(worker.run_once())
        for _ in range(100):
            if adapter.calls:
                break
            await asyncio.sleep(0.01)
        with db.session.begin() as session:
            req = session.get(SearchRequest, rid)
            req.cancel_requested = True
        await pending

    asyncio.run(scenario())
    result = read_search(db, rid)
    assert result["completion_status"] == "cancelled"
    assert result["evaluated_count"] == 0
    assert adapter.cancelled_calls > 0
    with db.session() as session:
        assert session.get(SearchRequest, rid).lease_owner is None


def test_expired_lease_can_be_recovered(tmp_path):
    db, settings, state = setup(tmp_path, count=1)
    adapter = FakeOTP()
    rid = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    with db.session.begin() as session:
        req = session.get(SearchRequest, rid)
        req.completion_status, req.lease_owner, req.lease_until = "running", "dead-worker", 1
    asyncio.run(RoutingWorker(db, adapter, settings).run_once())
    assert read_search(db, rid)["completion_status"] == "complete"


def test_api_manual_search_patch_replay_and_unknown_ids(tmp_path):
    db, settings, _ = setup(tmp_path)
    adapter = FakeOTP()
    app = create_app(settings, db, TinyGeo(), adapter, start_worker=False)
    with TestClient(app) as client:
        default = client.get("/api/state/default").json()
        assert client.get("/api/health").json()["listing_count"] == 5
        invalid = client.post("/api/state/patch", json={"state": default, "operations": [{"field": "schema_version", "value": "bad"}]})
        assert invalid.status_code == 422
        default["selected_district_ids"] = ["missing"]
        assert client.post("/api/searches", json={"state": default}).status_code == 422
        default["selected_district_ids"] = []
        response = client.post("/api/searches", json={"state": default})
        assert response.status_code == 201
        value = response.json()
        assert value["candidate_count"] == 5
        replay = client.post(f"/api/searches/{value['request_id']}/replay").json()
        assert len(replay["candidates"]) == 5
        assert adapter.calls == 0
        assert replay["state"] == value["state"]


def test_only_one_database_lease_can_route_across_workers(tmp_path):
    db, settings, state = setup(tmp_path)
    first = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    worker_a, worker_b = RoutingWorker(db, FakeOTP(), settings), RoutingWorker(db, FakeOTP(), settings)
    assert worker_a.claim() == first
    assert worker_b.claim() is None


def test_worker_rechecks_default_supported_modes(tmp_path):
    from backend.app.routing import normalize_itinerary
    from tests.test_routing import raw_itinerary, ORIGIN, TRAVEL
    db, settings, _ = setup(tmp_path, count=1)
    state = SearchState(dataset_version='test', travel={**TRAVEL, 'modes': []})
    adapter = FakeOTP()
    adapter.settings.supported_modes = ['BUS']
    wrong = normalize_itinerary(raw_itinerary(), ORIGIN, TRAVEL, 'wrong-mode', adapter.settings)
    for leg in wrong['legs']:
        if leg['mode'] == 'BUS':
            leg['mode'] = 'METRO'
    async def route(origin, travel):
        return {'status': 'ok', 'itineraries': [wrong]}
    adapter.route = route
    rid = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    asyncio.run(RoutingWorker(db, adapter, settings).run_once())
    assert read_search(db, rid)['excluded_evaluations'][0]['status'] == 'no_feasible_returned_itinerary'
