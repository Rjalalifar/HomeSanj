"""Measure real stored-data accessibility, bounded OTP calls and cache reuse."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.app.catalog import Catalog
from backend.app.config import Settings
from backend.app.contracts import SearchState, SearchInput
from backend.app.db import Database, Listing, SearchRequest
from backend.app.geo import GeometryStore
from backend.app.routing import OTPAdapter, OTPSettings
from backend.app.search import create_search, read_search
from backend.app.worker import RoutingWorker
from backend.app.transit_stops import StopCatalog
from backend.app.evaluation_replay import freeze_manifest, replay_manifest


async def main():
    settings = Settings.from_env()
    settings.batch_limit = 3
    source = Database(settings.database_url)
    with source.session() as session:
        listings = [r.payload for r in session.scalars(select(Listing).where(Listing.is_synthetic.is_(True)))]
    target = Path('runtime/accessibility-verification') / uuid4().hex
    target.mkdir(parents=True)
    db = Database('sqlite:///' + str(target / 'test.sqlite'))
    db.migrate()
    db.insert_listings(listings)
    geo = GeometryStore(settings.data_dir)
    catalogue = Catalog(db, geo)
    catalogue.refresh()
    stops = StopCatalog()
    adapter = OTPAdapter(OTPSettings.from_env())
    original_route, requests, active, peak = adapter.route, 0, 0, 0

    async def measured_route(origin, travel):
        nonlocal requests, active, peak
        requests += 1
        active += 1
        peak = max(active, peak)
        try:
            return await original_route(origin, travel)
        finally:
            active -= 1

    adapter.route = measured_route
    worker = RoutingWorker(db, adapter, settings)
    state = SearchState(dataset_version=geo.dataset_version, accessibility={'enabled': True})
    begin = perf_counter()
    rid = create_search(db, geo, SearchInput(state=state), settings, adapter.configured, catalog=catalogue, stops=stops)
    create_ms = (perf_counter() - begin) * 1000
    begin = perf_counter()
    await worker.run_once()
    walk_ms = (perf_counter() - begin) * 1000
    result = read_search(db, rid, limit=100000)
    before_sort = requests
    begin = perf_counter()
    sorted_view = read_search(db, rid, sort='stop_walk_time_asc')
    sort_ms = (perf_counter() - begin) * 1000
    after_sort = requests
    rid2 = create_search(db, geo, SearchInput(state=state), settings, adapter.configured, catalog=catalogue, stops=stops)
    begin = perf_counter()
    await worker.run_once()
    cached_ms = (perf_counter() - begin) * 1000
    cached = read_search(db, rid2)
    after_cached = requests
    origin = sorted_view['results'][0]['property']
    nearest = stops.nearest(origin['latitude'], origin['longitude'])[0]
    destination_state = SearchState(dataset_version=geo.dataset_version, accessibility={'enabled': True},
        travel={'destination': {'latitude': nearest['latitude'], 'longitude': nearest['longitude'], 'confirmed': True}})
    rid3 = create_search(db, geo, SearchInput(state=destination_state), settings, adapter.configured, catalog=catalogue, stops=stops)
    begin = perf_counter()
    await worker.run_once()
    destination_ms = (perf_counter() - begin) * 1000
    destination = read_search(db, rid3)
    manifest = freeze_manifest(db, rid)
    replay = replay_manifest(db, manifest['manifest_id'])
    known = [r for r in result['results'] if r['accessibility']['status'] == 'ok']
    destination_known = [r for r in destination['results'] if r['accessibility']['status'] == 'ok']
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': 'isolated copied synthetic listings; existing real local OTP; no LLM',
        'property_count': len(listings), 'candidate_count': result['candidate_count'],
        'evaluated_count': result['evaluated_count'], 'completion_status': result['completion_status'],
        'stop_count': len(stops.stops), 'stop_dataset_version': stops.version,
        'timing_ms': {'filtered_snapshot_with_proximity': create_ms, 'three_walking_routes': walk_ms,
            'sort_full_candidate_set': sort_ms, 'cached_three_routes': cached_ms, 'three_destination_routes': destination_ms},
        'otp_requests': requests, 'concurrency_peak': peak, 'configured_concurrency': adapter.settings.max_concurrency,
        'sort_otp_requests': after_sort - before_sort, 'repeat_stop_search_otp_requests': after_cached - after_sort,
        'cached_stop_hits': cached['cache_hits'], 'walking_known_count': len(known), 'destination_known_count': len(destination_known),
        'destination_statuses': dict(Counter(r['accessibility']['status'] for r in destination['results'])),
        'walking_sources': sorted({r['selected_itinerary']['source_kind'] for r in known}),
        'destination_sources': sorted({r['selected_itinerary']['source_kind'] for r in destination_known}),
        'example_measured_walk': {k: known[0]['accessibility'][k] for k in ('straight_line_meters','walk_distance_meters','walk_duration_seconds')} if known else None,
        'snapshot_replay_status': replay['status'], 'snapshot_replay_network_calls': replay['network_calls'],
        'graph_version': adapter.settings.graph_version, 'schedule_basis': adapter.settings.schedule_basis,
        'full_city_routing_performed': False, 'price_and_coordinates_resampled': False,
        'status': 'pass' if known and destination_known and after_cached == after_sort == before_sort and cached['cache_hits'] == 3 and peak <= adapter.settings.max_concurrency and replay['status'] == 'ok' else 'fail'}
    Path('docs/accessibility-live-performance-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    await adapter.close()
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    asyncio.run(main())
