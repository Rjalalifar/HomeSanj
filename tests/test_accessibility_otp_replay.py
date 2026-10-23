"""Verified pedestrian request shape and immutable accessibility replay evidence."""
import asyncio
import httpx
from sqlalchemy import select

from backend.app.db import Candidate
from backend.app.routing import OTPAdapter, OTPSettings
from backend.app.evaluation_replay import freeze_manifest, replay_manifest
from tests.test_search import database
from tests.test_accessibility import auto_state, submit, process, Routes


def test_pedestrian_profile_explicitly_disallows_transit():
    bodies = []

    def handle(request):
        import json
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'data': {'trip': {'tripPatterns': [], 'routingErrors': []}}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            adapter = OTPAdapter(OTPSettings(api_path='/otp/transmodel/v3', api_type='transmodel_v3',
                api_verified=True, supported_modes=['BUS']), client)
            result = await adapter.route({'latitude': 35.7, 'longitude': 51.4}, {
                'destination': {'latitude': 35.701, 'longitude': 51.401}, 'date': '2026-10-21',
                'time': '12:00:00', 'routing_profile': 'walk_only', 'modes': ['WALK'], 'include_walk_only': True})
            assert result['status'] == 'no_route_returned'

    asyncio.run(run())
    assert bodies[0]['variables']['modes'] == {'directMode': 'foot', 'transportModes': []}


def test_new_snapshot_replay_retains_accessibility_and_detects_modified_stop(database):
    rid = submit(database, auto_state(property={'parking_required': True}))
    process(database, Routes())
    manifest = freeze_manifest(database, rid)
    replay = replay_manifest(database, manifest['manifest_id'])
    assert replay['rows']['p1']['accessibility']['nearest_stop']['stop_id'] == 'fixture-stop'
    assert replay['rows']['p1']['accessibility']['walk_duration_seconds'] == 120
    assert replay['network_calls'] == 0
    assert 'routing_travel' not in replay['rows']['p1']
    with database.session.begin() as session:
        candidate = session.get(Candidate, (rid, 'p1'))
        candidate.accessibility_snapshot = {**candidate.accessibility_snapshot, 'straight_line_meters': 9}
    assert replay_manifest(database, manifest['manifest_id'])['status'] == 'partial_replay'


def test_automatic_nearby_recommended_profile_is_not_legacy_destination(database):
    from backend.app.ranking import policy
    assert policy(auto_state())['mode'] == 'nearby_stop'
    assert 'straight_line_meters' in policy(auto_state())['weights']
