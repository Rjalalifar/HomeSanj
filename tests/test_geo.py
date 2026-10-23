import json
import random
from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape

from backend.app.geo import GeometryStore, convert_feature, stable_id
from backend.app.seed import generate_listings, sample_metric_point


def feature(identifier, geometry):
    return {'type': 'Feature', 'id': identifier, 'properties': {'id': identifier, 'name_fa': identifier, 'district_no': 1, 'quality_flags': []}, 'geometry': mapping(geometry)}


def store(features):
    return GeometryStore(neighborhoods=features, districts=[feature('d1', box(50, 34, 53, 38))], dataset_version='test')


def test_holes_are_not_sampled_and_multipart_uses_metric_area():
    hole = Polygon([(51, 35), (51.04, 35), (51.04, 35.04), (51, 35.04)], [[(51.01, 35.01), (51.03, 35.01), (51.03, 35.03), (51.01, 35.03)]])
    rng = random.Random(10)
    assert all(hole.contains(sample_metric_point(hole, rng)) for _ in range(100))
    multi = MultiPolygon([box(51, 35, 51.01, 35.01), box(51.1, 35, 51.13, 35.01)])
    rng = random.Random(123)
    points = [sample_metric_point(multi, rng) for _ in range(600)]
    large_share = sum(point.x > 51.05 for point in points) / len(points)
    assert .67 < large_share < .83
    assert all(multi.contains(point) for point in points)


def test_stable_ids_are_not_index_or_name_only():
    a = box(51, 35, 51.01, 35.01)
    reordered = Polygon(list(a.exterior.coords)[::-1])
    assert stable_id('neighborhood', 1, 'كيان', a) == stable_id('neighborhood', 1, 'کیان', reordered)
    assert stable_id('neighborhood', 1, 'n', a) != stable_id('neighborhood', 2, 'n', a)
    assert stable_id('neighborhood', 1, 'n', a) != stable_id('neighborhood', 1, 'n', box(51, 35, 51.02, 35.01))


def test_repairs_preserve_original_and_prepared_identity():
    bowtie = Polygon([(51, 35), (51.02, 35.02), (51, 35.02), (51.02, 35), (51, 35)])
    raw = {'type': 'Feature', 'properties': {'name': 'n', 'district': 1}, 'geometry': mapping(bowtie)}
    converted, report = convert_feature(raw, 'neighborhood')
    assert shape(converted['geometry']).is_valid
    assert report['original_geometry'] == mapping(bowtie)
    converted['properties']['provenance'] = {'custom': 'preserved'}
    again, _ = convert_feature(converted, 'neighborhood')
    assert again['id'] == converted['id']
    assert again['properties']['provenance'] == {'custom': 'preserved'}


def test_overlap_is_ambiguous_and_seed_rejects_it():
    geo = store([feature('n1', box(51, 35, 51.02, 35.02)), feature('n2', box(51.01, 35, 51.03, 35.02))])
    assert geo.neighborhood_memberships(51.015, 35.01) == ['n1', 'n2']
    items, report = generate_listings(geo, 7, 'test', 3)
    assert len(items) == 18 and not report['shortages']
    for item in items:
        assert geo.neighborhood_memberships(item['longitude'], item['latitude']) == [item['neighborhood_id']]


def test_fully_overlapped_neighborhood_has_bounded_shortage(monkeypatch):
    import backend.app.seed as module
    monkeypatch.setattr(module, 'MAX_ATTEMPTS_PER_POINT', 5)
    geo = store([feature('n1', box(51, 35, 51.01, 35.01)), feature('n2', box(51, 35, 51.01, 35.01))])
    items, report = generate_listings(geo, 7, 'test', 1)
    assert items == [] and len(report['shortages']) == 6
    assert report['attempts'] == 30


def test_seed_is_reproducible_across_order_and_sample_count():
    features = [feature('n1', box(51, 35, 51.01, 35.01)), feature('n2', box(51.1, 35, 51.11, 35.01))]
    first, report = generate_listings(store(features), 8, 'test', 2)
    again, again_report = generate_listings(store(features[::-1]), 8, 'test', 2)
    assert first == again and report == again_report
    bigger, _ = generate_listings(store(features), 8, 'test', 3)
    lookup = {item['property_id']: item for item in bigger}
    assert all(lookup[item['property_id']] == item for item in first)


def test_actual_boundary_counts_quality_and_seed_report():
    root = Path('data')
    if not (root / 'validation-report.json').exists():
        pytest.skip('Prepared data not downloaded; fixture geometry tests remain offline')
    report = json.loads((root / 'validation-report.json').read_text(encoding='utf-8'))
    assert report['neighborhood_count'] == 377 and report['district_count'] == 22
    assert report['repair_count'] == 2 and report['overlap_pairs_over_1m2'] == 120
    assert report['outside_assigned_district_over_1pct'] == 108
    if (root / 'seed-report.json').exists():
        seed = json.loads((root / 'seed-report.json').read_text(encoding='utf-8'))
        assert seed['generated_count'] == sum(seed['series_counts'].values())
        assert seed['expected_count'] == 377 * 3 * 5


def test_prepared_top_level_id_and_provenance_are_preserved():
    raw = {'type': 'Feature', 'id': 'provided-stable-id', 'properties': {'name_fa': 'provided', 'district_no': 1, 'provenance': {'original': True}}, 'geometry': mapping(box(51, 35, 51.01, 35.01))}
    converted, _ = convert_feature(raw, 'neighborhood')
    assert converted['id'] == 'provided-stable-id'
    assert converted['properties']['provenance'] == {'original': True}
