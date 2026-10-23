import asyncio
from copy import deepcopy

from backend.app.contracts import SearchInput, SearchState
from backend.app.routing import normalize_itinerary
from backend.app.search import create_search, read_search
from backend.app.worker import RoutingWorker
from tests.test_routing import ORIGIN, TRAVEL, raw_itinerary
from tests.test_search import TinyGeo
from tests.test_worker_api import setup, FakeOTP


def test_sort_selects_one_qualifying_alternative_without_new_route_call(tmp_path):
    db, settings, _ = setup(tmp_path, count=1)
    adapter = FakeOTP()
    adapter.settings.supported_modes = ['BUS']
    fast = normalize_itinerary(raw_itinerary(), ORIGIN, TRAVEL, 'fast', adapter.settings)
    slow = deepcopy(fast)
    slow.update(itinerary_id='less-walking', total_duration_seconds=fast['total_duration_seconds'] + 300,
                walk_duration_seconds=fast['walk_duration_seconds'] / 2)
    async def route(origin, travel):
        adapter.calls += 1
        return {'status': 'ok', 'itineraries': [fast, slow]}
    adapter.route = route
    state = SearchState(dataset_version='test', travel=TRAVEL, sort='travel_time_asc')
    first = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    asyncio.run(RoutingWorker(db, adapter, settings).run_once())
    assert read_search(db, first)['results'][0]['selected_itinerary']['itinerary_id'] == fast['itinerary_id']
    state.sort = 'walk_time_asc'
    second = create_search(db, TinyGeo(), SearchInput(state=state, parent_request_id=first), settings, True)
    asyncio.run(RoutingWorker(db, adapter, settings).run_once())
    result = read_search(db, second)
    assert adapter.calls == 1
    assert result['cache_hits'] == 1
    chosen = result['results'][0]['selected_itinerary']
    assert chosen['itinerary_id'] == 'less-walking'
    assert chosen['total_duration_seconds'] == slow['total_duration_seconds']
    assert chosen['walk_duration_seconds'] == slow['walk_duration_seconds']
