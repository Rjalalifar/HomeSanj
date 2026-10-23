from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.catalog import Catalog, ListingAssignment, keyword_match
from backend.app.config import Settings
from backend.app.contracts import SearchInput, SearchState, apply_patch
from backend.app.db import Database, Listing
from backend.app.intent import propose
from backend.app.main import create_app
from backend.app.ranking import rank_rows
from backend.app.routing import OTPAdapter, OTPSettings
from backend.app.search import create_search, read_search
from tests.test_search import TinyGeo, listing


@pytest.fixture
def setup(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "core.sqlite3"}')
    db.migrate()
    items = [listing('p1', .5, 10, True), listing('p2', 1.5, 20, None), listing('p3', 2.5, None, False)]
    items[0]['title_fa'] = 'خانه روشن با پارکینگ'
    items[1]['title_fa'] = 'آپارتمان بزرگ'
    db.insert_listings(items)
    geo = TinyGeo()
    geo.neighborhoods = deepcopy(geo.neighborhoods)
    geo.neighborhoods[0]['properties']['name_fa'] = 'ونک'
    geo.neighborhoods[1]['properties']['name_fa'] = 'بهار'
    catalog = Catalog(db, geo)
    catalog.refresh()
    return db, geo, catalog


def test_assignments_are_geometry_owned_and_public_snapshot_is_safe(setup):
    db, geo, catalog = setup
    assert catalog.public['count'] == 3
    p2 = catalog.public['properties'][1]
    assert p2['neighborhood_membership_status'] == 'ambiguous'
    assert p2['district_ids'] == []
    assert p2['neighborhood_ids'] == ['n1', 'n2']
    before = catalog.version
    catalog.refresh()
    assert catalog.version == before
    with db.session.begin() as session:
        row = session.get(Listing, 'p1')
        row.payload = {**row.payload, 'title_fa': 'تغییر ثبت شده'}
    catalog.refresh()
    assert catalog.version != before
    assert catalog.lexical('تغییر') == ['p1']


def test_fts_normalization_prefix_and_parameter_safety(setup):
    _, _, catalog = setup
    assert catalog.fts
    assert catalog.lexical('پاركينگ') == ['p1']
    assert catalog.lexical('آپار') == ['p2']
    assert catalog.lexical('" OR *; DROP TABLE listings') == []
    for query in ['پارکینگ', 'خانه روشن', 'ونک', 'آپار', 'ناموجود']:
        expected = [p['property_id'] for p in catalog.public['properties'] if keyword_match(query, p['search_text'])]
        assert set(catalog.lexical(query)) == set(expected)


def test_indexed_filter_and_exact_server_verdict_agree(setup):
    db, geo, catalog = setup
    state = SearchState(dataset_version='test', selected_neighborhood_ids=['n1', 'n2'], selected_district_ids=['d1'])
    rid = create_search(db, geo, SearchInput(state=state), Settings(), False, catalog=catalog)
    assert [r['property']['property_id'] for r in read_search(db, rid)['results']] == ['p1']
    with pytest.raises(ValueError, match='destination'):
        create_search(db, geo, SearchInput(state=SearchState(dataset_version='test', sort='travel_time_asc')), Settings(), False)


def test_ranking_is_stable_and_all_sort_ties_are_explicit():
    state = SearchState(dataset_version='test', sort='rent_asc')
    rows = [{'property': {'property_id': 'a', 'monthly_rent_toman': 10, 'deposit_toman': 300}},
            {'property': {'property_id': 'b', 'monthly_rent_toman': 10, 'deposit_toman': 100}},
            {'property': {'property_id': 'c', 'monthly_rent_toman': None, 'deposit_toman': 0}}]
    assert [r['property']['property_id'] for r in rank_rows(rows, state)] == ['b', 'a', 'c']
    state.sort = 'recommended'
    first = {r['property']['property_id']: r['rank_score'] for r in rank_rows(deepcopy(rows), state)}
    second = rank_rows(deepcopy(rows[:1]), state)
    assert first['a'] == second[0]['rank_score']
    assert second[0]['ranking_factors']['deposit_toman']['weight'] == .4


def test_contextual_parser_preserves_state_and_hard_soft_separation(setup):
    _, geo, _ = setup
    state = SearchState(dataset_version='test', property={'max_monthly_rent_toman': 20_000_000}, selected_neighborhood_ids=['n1'])
    proposed = propose('پارکینگ هم الزامی باشد و پیاده‌روی کمتر مهم‌تر است', state, geo)
    assert not proposed['search_pending']
    updated = apply_patch(state, proposed['operations'])
    assert updated.property.parking_required is True
    assert updated.property.max_monthly_rent_toman == 20_000_000
    assert updated.selected_neighborhood_ids == ['n1']
    assert updated.preference == 'less_walking'
    soft = propose('ترجیحا آسانسور و اجاره کمتر', state, geo)
    assert soft['soft_preferences'] == ['elevator', 'lower_rent']
    assert not any(op['field'] == 'property.elevator_required' for op in soft['operations'])


def test_ambiguity_and_tehran_tomorrow_hold_search(setup):
    _, geo, _ = setup
    state = SearchState(dataset_version='test')
    assert propose('اجاره تا 20 میلیون', state, geo)['search_pending']
    geo.neighborhoods[1]['properties']['name_fa'] = 'ونک'
    result = propose('در ونک', state, geo)
    assert len(result['clarifications'][0]['candidates']) == 2
    result = propose('فردا ساعت 08:30 برسم', state, geo, datetime(2026, 10, 20, 23, 59, tzinfo=ZoneInfo('Asia/Tehran')))
    assert {'field': 'travel.date', 'value': '2026-10-21', 'remove': False} in result['operations']
    assert result['search_pending']


def test_session_ownership_etag_and_no_models_on_normal_search(setup, monkeypatch):
    db, geo, _ = setup
    monkeypatch.setenv('INTENT_LLM_ENABLED', 'false')
    adapter = OTPAdapter(OTPSettings())
    app = create_app(Settings(), database=db, geo=geo, adapter=adapter, start_worker=False)
    with TestClient(app) as one, TestClient(app) as two:
        inventory = one.get('/api/inventory')
        assert inventory.status_code == 200
        assert one.get('/api/inventory', headers={'If-None-Match': inventory.headers['etag']}).status_code == 304
        state = one.get('/api/state/default').json()
        result = one.post('/api/searches', json={'state': state})
        assert result.status_code == 201, result.text
        rid = result.json()['request_id']
        assert one.get(f'/api/searches/{rid}').status_code == 200
        assert two.get(f'/api/searches/{rid}').status_code == 404
        assert two.post('/api/searches', json={'state': state, 'parent_request_id': rid}).status_code == 404
        assert one.post('/api/parse', json={'text': 'پارکینگ الزامی'}).json()['mode'] == 'حالت نمونه بدون LLM'
        assert result.json()['semantic']['status'] == 'not_requested'
        assert result.json()['evaluated_count'] == 0
        assert one.post('/api/searches', json={'state': state}, headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
