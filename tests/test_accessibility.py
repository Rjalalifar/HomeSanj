"""Automatic property accessibility shares snapshots, cache and the durable worker."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.app.contracts import SearchInput, SearchState
from backend.app.config import Settings
from backend.app.db import Evaluation, RouteCache, SearchRequest
from backend.app.routing import OTPSettings, request_datetime
from backend.app.search import create_search, read_search
from backend.app.worker import RoutingWorker
from tests.test_search import TinyGeo, database


class Stops:
    version = 'fixture-stops-v1'
    status = 'ok'

    def nearest(self, latitude, longitude, limit=1):
        return [{'stop_id': 'fixture-stop', 'name': 'Fixture bus stop', 'stop_type': 'bus',
            'latitude': latitude + .001, 'longitude': longitude, 'straight_line_meters': 111.2,
            'dataset_version': self.version}][:limit]


class Routes:
    configured = True

    def __init__(self, status='ok'):
        self.settings = OTPSettings(supported_modes=['BUS'], graph_version='fixture-graph')
        self.calls = []
        self.status = status

    async def route(self, origin, travel):
        self.calls.append((origin, travel))
        instant = request_datetime(travel).isoformat()
        walk = travel.get('routing_profile') == 'walk_only'
        item = {'itinerary_id': 'fixture-itinerary', 'total_duration_seconds': 120,
            'walk_duration_seconds': 120 if walk else 50, 'walk_distance_meters': 150,
            'start_datetime': instant, 'end_datetime': instant, 'request_datetime': instant,
            'legs': [{'mode': 'WALK', 'is_transit': False}] + ([] if walk else [{'mode': 'BUS', 'is_transit': True}]),
            'source_kind': 'synthetic_fixture', 'fetched_at': instant, 'graph_version': 'fixture-graph'}
        return {'status': self.status, 'itineraries': [item] if self.status == 'ok' else []}


def auto_state(destination=None, **kwargs):
    return SearchState(dataset_version='test', accessibility={'enabled': True},
        travel={'destination': destination}, **kwargs)


def submit(db, state, stops=None):
    return create_search(db, TinyGeo(), SearchInput(state=state), Settings(batch_limit=2), True,
        stops=stops or Stops())


def process(db, routes):
    worker = RoutingWorker(db, routes, Settings(batch_limit=2))
    asyncio.run(worker.run_once())
    return worker


def test_without_destination_keeps_candidates_and_persists_stop_evidence(database):
    rid = submit(database, auto_state(sort='stop_distance_asc'))
    result = read_search(database, rid)
    assert result['candidate_count'] == 3
    assert len(result['results']) == 3
    assert result['completion_status'] == 'queued'
    assert result['results'][0]['accessibility']['straight_line_meters'] == 111.2
    assert result['results'][0]['accessibility']['walk_duration_seconds'] is None
    assert result['accessibility']['mode'] == 'nearby_stop'


def test_automatic_destination_time_and_legacy_time_requirement(database):
    dest = {'latitude': 1.1, 'longitude': 0.5, 'confirmed': True}
    before = datetime.now(timezone.utc).replace(microsecond=0)
    rid = submit(database, auto_state(destination=dest, property={'parking_required': True}))
    result = read_search(database, rid)
    effective = datetime.fromisoformat(result['state']['accessibility']['effective_at'])
    assert before <= effective <= datetime.now(timezone.utc)
    assert effective.utcoffset().total_seconds() == 12600
    assert result['candidate_count'] == 1
    routes = Routes()
    process(database, routes)
    assert routes.calls[0][0] == {'latitude': 1.0, 'longitude': .5}
    assert routes.calls[0][1]['destination']['latitude'] == 1.1
    assert read_search(database, rid)['results'][0]['accessibility']['status'] == 'ok'
    with pytest.raises(ValueError, match='explicit date'):
        SearchState(dataset_version='test', travel={'destination': dest})


def test_walking_cache_survives_sort_and_new_search(database):
    state = auto_state(property={'parking_required': True}, sort='stop_walk_time_asc')
    rid = submit(database, state)
    routes = Routes()
    process(database, routes)
    initial = read_search(database, rid)
    assert routes.calls[0][1]['routing_profile'] == 'walk_only'
    assert initial['results'][0]['accessibility']['walk_duration_seconds'] == 120
    sorted_view = read_search(database, rid, sort='stop_distance_asc')
    assert sorted_view['state']['sort'] == 'stop_distance_asc'
    assert read_search(database, rid)['state']['sort'] == 'stop_walk_time_asc'
    rid2 = submit(database, state)
    process(database, routes)
    assert len(routes.calls) == 1
    assert read_search(database, rid2)['cache_hits'] == 1


def test_destination_change_isolated_from_stop_cache(database):
    routes = Routes()
    submit(database, auto_state(property={'parking_required': True}))
    process(database, routes)
    for longitude in (.5, .6):
        submit(database, auto_state(destination={'latitude': 1.1, 'longitude': longitude, 'confirmed': True},
            property={'parking_required': True}))
        process(database, routes)
    assert len(routes.calls) == 3
    rid = submit(database, auto_state(property={'parking_required': True}))
    process(database, routes)
    assert len(routes.calls) == 3 and read_search(database, rid)['cache_hits'] == 1


def test_timeout_preserves_proximity_and_unknown_walk(database):
    rid = submit(database, auto_state(property={'parking_required': True}))
    process(database, Routes('timeout'))
    row = read_search(database, rid)['results'][0]
    assert row['accessibility']['status'] == 'timeout'
    assert row['accessibility']['straight_line_meters'] == 111.2
    assert row['accessibility']['walk_duration_seconds'] is None


def test_missing_stops_do_not_dispatch_otp_and_partial_is_not_global(database):
    empty = SimpleNamespace(version=None, status='unavailable', nearest=lambda *args, **kw: [])
    rid = submit(database, auto_state(), empty)
    routes = Routes()
    process(database, routes)
    result = read_search(database, rid)
    assert routes.calls == []
    assert result['evaluated_count'] == 2
    assert result['completion_status'] == 'partial'
    assert result['ranking_scope'] == 'evaluated_subset'
    assert result['results'][0]['accessibility']['status'] == 'stops_unavailable'


def test_expired_cache_is_not_reused(database):
    routes = Routes()
    state = auto_state(property={'parking_required': True})
    submit(database, state)
    process(database, routes)
    with database.session.begin() as session:
        for cache in session.scalars(select(RouteCache)):
            cache.expires_at = 0
    submit(database, state)
    process(database, routes)
    assert len(routes.calls) == 2


def test_cancelled_worker_cannot_store_stale_evaluation(database):
    rid = submit(database, auto_state(property={'parking_required': True}))
    routes = Routes()
    original = routes.route

    async def cancel_during_route(origin, travel):
        with database.session.begin() as session:
            request = session.get(SearchRequest, rid)
            request.cancel_requested = True
        return await original(origin, travel)

    routes.route = cancel_during_route
    process(database, routes)
    with database.session() as session:
        assert session.get(Evaluation, (rid, 'p1')) is None
        assert session.get(SearchRequest, rid).completion_status == 'cancelled'
