from copy import deepcopy
from types import SimpleNamespace

import pytest
from shapely.geometry import Point, box, mapping, shape

from backend.app.config import Settings
from backend.app.contracts import SearchInput, SearchState
from backend.app.db import Database, Listing
from backend.app.search import create_search, read_search


class TinyGeo:
    dataset_version = 'test'
    neighborhoods = [
        {'type': 'Feature', 'id': 'n1', 'properties': {'id': 'n1'}, 'geometry': mapping(box(0, 0, 2, 2))},
        {'type': 'Feature', 'id': 'n2', 'properties': {'id': 'n2'}, 'geometry': mapping(box(1, 0, 3, 2))},
    ]
    districts = [
        {'type': 'Feature', 'id': 'd1', 'properties': {'id': 'd1'}, 'geometry': mapping(box(0, 0, 1, 2))},
        {'type': 'Feature', 'id': 'd2', 'properties': {'id': 'd2'}, 'geometry': mapping(box(4, 0, 5, 2))},
    ]

    def neighborhood_memberships(self, lon, lat):
        return [f['id'] for f in self.neighborhoods if shape(f['geometry']).covers(Point(lon, lat))]

    def district_memberships(self, lon, lat):
        return [f['id'] for f in self.districts if shape(f['geometry']).covers(Point(lon, lat))]


def listing(pid, lon, rent, parking):
    return {'property_id': pid, 'series_id': 'demo_a', 'neighborhood_id': 'n1',
            'district_membership_status': 'unknown', 'title_fa': 'Demo listing',
            'latitude': 1.0, 'longitude': lon, 'deposit_toman': 100, 'monthly_rent_toman': rent,
            'area_m2': 70, 'bedrooms': 2, 'parking': parking, 'elevator': None,
            'location_accuracy': 'synthetic_exact', 'source_records': [],
            'published_at': None, 'collected_at': None, 'is_synthetic': True, 'dataset_version': 'test', 'seed': 1}



@pytest.fixture
def database(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "test.sqlite3"}')
    db.migrate()
    db.insert_listings([listing('p1', 0.5, 10, True), listing('p2', 1.5, 20, None), listing('p3', 2.5, None, False)])
    return db


def search(db, **kwargs):
    state = SearchState(dataset_version='test', **kwargs)
    rid = create_search(db, TinyGeo(), SearchInput(state=state), Settings(), False)
    return read_search(db, rid, include_snapshot=True)


def test_or_within_group_and_across_groups_use_geometry(database):
    result = search(database, selected_neighborhood_ids=['n1', 'n2'], selected_district_ids=['d1'])
    assert [r['property']['property_id'] for r in result['results']] == ['p1']
    assert result['candidate_count'] == 1
    assert result['candidates'][0]['property_verdicts'][-1]['actual'] == ['d1']


def test_unknown_active_constraints_cannot_pass_and_false_is_not_prohibition(database):
    result = search(database, property={'parking_required': False})
    assert result['candidate_count'] == 3
    assert search(database, property={'parking_required': True})['candidate_count'] == 1
    assert search(database, property={'max_monthly_rent_toman': 100})['candidate_count'] == 2


def test_ambiguous_membership_and_contradiction_are_visible(database):
    result = search(database, selected_neighborhood_ids=['n1'])
    candidate = next(c for c in result['candidates'] if c['property']['property_id'] == 'p2')
    assert candidate['property_verdicts'][0]['membership_status'] == 'ambiguous'
    result = search(database, selected_neighborhood_ids=['n1'], selected_district_ids=['d2'])
    assert result['candidate_count'] == 0 and result['warnings']
    assert result['state']['selected_district_ids'] == ['d2']
    with pytest.raises(ValueError, match='Unknown geographic'):
        search(database, selected_neighborhood_ids=['invented'])


def test_snapshot_survives_listing_changes_and_lineage(database):
    first = search(database)
    with database.session.begin() as session:
        row = session.get(Listing, 'p1')
        row.payload = {**row.payload, 'monthly_rent_toman': 999}
    replay = read_search(database, first['request_id'], include_snapshot=True)
    assert replay['results'][0]['property']['monthly_rent_toman'] == 10
    state = SearchState.model_validate(first['state'])
    second_id = create_search(database, TinyGeo(), SearchInput(state=state, parent_request_id=first['request_id'], task_id=first['task_id']), Settings(), False)
    second = read_search(database, second_id)
    assert second['task_id'] == first['task_id']
    assert second['state']['state_revision'] == 1
    changed = state.model_copy(update={'travel': state.travel.model_validate({'destination': {'latitude': 1, 'longitude': 1, 'confirmed': True}, 'date': '2026-01-01', 'time': '08:00:00'})})
    third_id = create_search(database, TinyGeo(), SearchInput(state=changed, parent_request_id=second_id), Settings(), False)
    third = read_search(database, third_id)
    assert third['task_id'] != first['task_id']
    assert third['completion_status'] == 'routing_unavailable'
