"""Versioned automatic accessibility on existing snapshots and SQLite route cache."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import time

from sqlalchemy import inspect, text

from .db import Migration, RouteCache, utcnow
from .routing import ADAPTER_VERSION, evaluate_itineraries

VERSION = 'accessibility-1'
CACHE_VERSION = 'accessibility-cache-1'


def enabled(state):
    access = state.get('accessibility') if isinstance(state, dict) else state.accessibility
    return bool(access and (access.get('enabled') if isinstance(access, dict) else access.enabled))


def migrate_accessibility(db):
    with db.engine.begin() as connection:
        columns = {c['name'] for c in inspect(connection).get_columns('snapshot_candidates')}
        if 'accessibility_snapshot' not in columns:
            connection.execute(text("ALTER TABLE snapshot_candidates ADD COLUMN accessibility_snapshot JSON NOT NULL DEFAULT '{}'"))
    with db.session.begin() as session:
        if session.get(Migration, 5) is None:
            session.add(Migration(version=5, applied_at=utcnow()))


def prepare_state(state):
    """Materialize time on execution; callers cannot replay a stale automatic timestamp."""
    if not enabled(state):
        return state
    from .contracts import SearchState
    data = state.model_dump(mode='json')
    now = datetime.now(ZoneInfo('Asia/Tehran')).replace(microsecond=0)
    data['accessibility']['effective_at'] = now.isoformat()
    destination = data['travel']['destination']
    data['travel'] = {'destination': destination}
    if destination:
        data['travel'].update(date=now.date().isoformat(), time=now.time().isoformat(),
            time_mode='DEPART_AT')
    return SearchState.model_validate(data)


def initial_accessibility(item, state, stops):
    mode = 'destination' if state.travel.destination else 'nearby_stop'
    nearby = []
    if mode == 'nearby_stop' and item.get('latitude') is not None and item.get('longitude') is not None:
        nearby = stops.nearest(item['latitude'], item['longitude'], limit=1)
    nearest = nearby[0] if nearby else None
    return {'semantics_version': VERSION, 'mode': mode, 'status': 'not_evaluated',
        'nearest_stop': nearest, 'walking_stop': None,
        'stop_dataset_version': stops.version if mode == 'nearby_stop' else None,
        'stops_status': stops.status if mode == 'nearby_stop' else 'not_required',
        'straight_line_meters': nearest['straight_line_meters'] if nearest else None,
        'walk_duration_seconds': None, 'walk_distance_meters': None, 'total_duration_seconds': None,
        'effective_at': state.accessibility.effective_at, 'calculated_at': None,
        'cache_policy_version': CACHE_VERSION, 'walking_scope': 'nearest_geographic_stop_only'}


def cache_identity(item, travel, access, settings):
    """Separate timeless pedestrian inputs from the short scheduled-transit window."""
    window = max(1, min(300, int(os.getenv('ACCESSIBILITY_TRANSIT_CACHE_SECONDS', '60'))))
    pedestrian = access['mode'] == 'nearby_stop'
    instant = datetime.fromisoformat(access['effective_at'])
    identity = {'cache_policy_version': CACHE_VERSION, 'semantics_version': VERSION,
        'property_id': item['property_id'], 'property_dataset_version': item.get('dataset_version'),
        'origin': {k: item.get(k) for k in ('latitude', 'longitude')},
        'mode': access['mode'], 'destination': {k: travel['destination'][k] for k in ('latitude', 'longitude')},
        'stop_id': (access.get('nearest_stop') or {}).get('stop_id'),
        'stop_dataset_version': access.get('stop_dataset_version'),
        'graph_version': settings.graph_version, 'adapter_version': ADAPTER_VERSION,
        'api': [settings.base_url, settings.api_path, settings.api_type],
        'routing_profile': 'walk_only' if pedestrian else 'transit_and_walk',
        'modes': [] if pedestrian else sorted(settings.supported_modes),
        'fixture_mode': settings.fixture_mode, 'schedule_basis': settings.schedule_basis,
        'effective_time_window': None if pedestrian else int(instant.timestamp()) // window,
        'window_seconds': None if pedestrian else window, 'include_walk_only': True}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return key, identity


def select_result(result, preference='balanced'):
    """Select only from the same cached response, preserving its effective request time."""
    output = deepcopy(result)
    if result.get('itineraries') and result.get('routing_travel'):
        output.update(evaluate_itineraries(result['itineraries'], result['routing_travel'], preference))
    access = output['accessibility']
    access['status'] = output.get('status', 'not_evaluated')
    itinerary = output.get('selected_itinerary') if output['status'] == 'ok' else None
    for key in ('total_duration_seconds', 'walk_duration_seconds', 'walk_distance_meters'):
        access[key] = itinerary.get(key) if itinerary else None
    access['walking_stop'] = access['nearest_stop'] if itinerary and access['mode'] == 'nearby_stop' else None
    return output


async def evaluate_accessibility(worker, request_id, candidate, state, preference):
    access = deepcopy(candidate.accessibility_snapshot)
    item = candidate.property_snapshot
    base = {'status': 'not_evaluated', 'itineraries': [], 'selected_itinerary': None,
            'verdicts': [], 'cache_hit': False, 'accessibility': access}
    if item.get('latitude') is None or item.get('longitude') is None:
        base['status'] = 'origin_unknown'
        return candidate.property_id, '', select_result(base)
    if access['mode'] == 'nearby_stop' and not access['nearest_stop']:
        base['status'] = 'stops_unavailable'
        return candidate.property_id, '', select_result(base)
    travel = deepcopy(state['travel'])
    if access['mode'] == 'nearby_stop':
        instant = datetime.fromisoformat(access['effective_at'])
        stop = access['nearest_stop']
        travel = {'destination': {k: stop[k] for k in ('latitude', 'longitude')},
            'date': instant.date().isoformat(), 'time': instant.time().isoformat(),
            'timezone': 'Asia/Tehran', 'time_mode': 'DEPART_AT', 'include_walk_only': True,
            'modes': ['WALK'], 'routing_profile': 'walk_only'}
    else:
        travel['modes'] = worker.adapter.settings.supported_modes
        travel['include_walk_only'] = True
    key, identity = cache_identity(item, travel, access, worker.adapter.settings)
    with worker.db.session() as session:
        cache = session.get(RouteCache, key)
        cached = deepcopy(cache.payload) if cache and cache.expires_at > time.time() else None
    if cached and cached.get('accessibility_cache_identity') == identity and cached.get('status') == 'ok':
        cached['cache_hit'] = True
        for itinerary in cached.get('itineraries', []):
            if itinerary.get('source_kind') == 'live_otp':
                itinerary['source_kind'] = 'recorded_otp'
        return candidate.property_id, key, select_result(cached, preference)
    origin = {k: item[k] for k in ('latitude', 'longitude')}
    started = time.perf_counter()
    result = await worker.adapter.route(origin, travel)
    result = {**base, **result, 'routing_travel': travel, 'accessibility_cache_identity': identity,
        'routing_latency_ms': (time.perf_counter() - started) * 1000,
        'origin_location_accuracy': item.get('location_accuracy', 'unknown')}
    result['accessibility']['calculated_at'] = utcnow()
    result = select_result(result, preference)
    if result['status'] == 'ok' and not worker.cancelled(request_id):
        ttl = (min(604800, max(1, int(os.getenv('ACCESSIBILITY_WALK_CACHE_SECONDS', '86400'))))
               if access['mode'] == 'nearby_stop' else identity['window_seconds'])
        if not worker.adapter.settings.graph_version:
            ttl = min(ttl, 300)
        with worker.db.session.begin() as session:
            cached = session.get(RouteCache, key)
            if cached:
                cached.payload, cached.expires_at = result, time.time() + ttl
            else:
                session.add(RouteCache(cache_key=key, payload=result, expires_at=time.time() + ttl))
    return candidate.property_id, key, result
