"""Behavioral checks for separate access ranking without fabricated metrics."""
from copy import deepcopy
from importlib import import_module, util
from types import SimpleNamespace

import pytest


def ranking():
    assert util.find_spec('backend.app.accessibility_ranking') is not None, 'Access ranking is not implemented'
    return import_module('backend.app.accessibility_ranking')


def state(mode='destination', sort='recommended', preference='balanced'):
    return SimpleNamespace(
        accessibility=SimpleNamespace(enabled=True, mode=mode),
        property=SimpleNamespace(max_monthly_rent_toman=None, max_deposit_toman=None),
        travel=SimpleNamespace(max_duration_seconds=None, max_walk_seconds=None),
        preference=preference, soft_preferences=[], sort=sort,
    )


def row(pid, *, rent=15_000_000, deposit=500_000_000, mode='destination', status='ok',
        duration=1800, walk=450, distance=None, stop_id=None):
    return {
        'property': {'property_id': pid, 'monthly_rent_toman': rent, 'deposit_toman': deposit},
        'accessibility': {'mode': mode, 'status': status, 'total_duration_seconds': duration,
                          'walk_duration_seconds': walk, 'straight_line_meters': distance,
                          'nearest_stop': {'stop_id': stop_id, 'name': 'Public test stop'} if stop_id else None},
        'selected_itinerary': {'total_duration_seconds': 1, 'walk_duration_seconds': 1, 'transfers': 0},
    }


def test_destination_cost_uses_one_accessibility_result_and_excludes_transfers():
    rows = [row('half')]
    result = ranking().rank_rows(rows, state())[0]
    assert result['rank_score'] == pytest.approx(0.5)
    assert result['ranking_factors']['total_duration_seconds']['value'] == 1800
    assert result['ranking_factors']['walk_duration_seconds']['value'] == 450
    assert 'transfers' not in result['ranking_factors']
    assert result['ranking_policy_version'] == 'accessibility-ranker-1'


@pytest.mark.parametrize('sort,mode', [
    ('travel_time_asc', 'destination'), ('walk_time_asc', 'destination'),
    ('stop_walk_time_asc', 'nearby_stop'),
])
def test_access_sorts_require_ok_route_and_use_id_for_exact_metric_ties(sort, mode):
    rows = [row('b', mode=mode, rent=1), row('a', mode=mode, rent=30_000_000),
            row('failed', mode=mode, status='timeout', duration=0, walk=0),
            row('unknown', mode=mode, duration=None, walk=None)]
    assert [r['property']['property_id'] for r in ranking().rank_rows(rows, state(mode, sort))] == ['a', 'b', 'failed', 'unknown']
    assert rows[2]['ranking_factors']['walk_duration_seconds']['unknown'] is True


def test_stop_distance_is_independent_of_route_failure_but_requires_real_stop():
    rows = [row('unproven', mode='nearby_stop', distance=0),
            row('far', mode='nearby_stop', distance=600, stop_id='feed:far'),
            row('near', mode='nearby_stop', status='timeout', distance=50, stop_id='feed:near')]
    ranked = ranking().rank_rows(rows, state('nearby_stop', 'stop_distance_asc'))
    assert [r['property']['property_id'] for r in ranked] == ['near', 'far', 'unproven']
    assert ranked[0]['ranking_factors']['straight_line_meters']['value'] == 50
    assert ranked[0]['ranking_factors']['walk_duration_seconds']['value'] is None
    assert 'total_duration_seconds' not in ranked[0]['ranking_factors']


def test_missing_and_nonfinite_values_are_unknown_not_zero():
    rows = [row('unknown', rent=None, deposit=None, duration=None, walk=None),
            row('invalid', rent=float('nan'), deposit=-1, duration=float('inf'), walk=True),
            row('known', rent=0, deposit=0, duration=0, walk=0)]
    ranked = ranking().rank_rows(rows, state())
    assert [r['property']['property_id'] for r in ranked] == ['known', 'invalid', 'unknown']
    assert ranked[0]['rank_score'] == 0
    for item in ranked[1:]:
        assert item['rank_score'] == pytest.approx(1)
        assert all(f['unknown'] and f['value'] is None for f in item['ranking_factors'].values())


def test_profile_mismatch_never_borrows_route_or_distance_from_other_mode():
    item = row('other', mode='nearby_stop', duration=0, walk=0, distance=0, stop_id='feed:stop')
    result = ranking().rank_rows([item], state('destination'))[0]
    assert result['ranking_factors']['total_duration_seconds']['value'] is None
    assert result['ranking_factors']['walk_duration_seconds']['value'] is None


def test_recommended_semantic_priority_only_breaks_exact_cost_ties():
    rows = [row('b'), row('a'), row('cheap', rent=0)]
    ranked = ranking().rank_rows(rows, state(), ['b', 'a'])
    assert [r['property']['property_id'] for r in ranked] == ['cheap', 'b', 'a']
    assert [r['property']['property_id'] for r in ranking().rank_rows(rows, state())] == ['cheap', 'a', 'b']


def test_financial_sort_preserves_unknown_and_uses_id_after_requested_value():
    rows = [row('b', rent=1, deposit=1), row('a', rent=1, deposit=100), row('c', rent=None)]
    ranked = ranking().rank_rows(rows, state(sort='rent_asc'), ['b'])
    assert [r['property']['property_id'] for r in ranked] == ['a', 'b', 'c']


def test_explicit_caps_and_experiment_multiplier_are_visible_and_normalized():
    current = state()
    current.property.max_monthly_rent_toman = 20_000_000
    current.travel.max_duration_seconds = 1200
    policy = ranking().policy(current, {'rent_weight_multiplier': 1.25})
    assert policy['scales']['monthly_rent_toman'] == 20_000_000
    assert policy['scales']['total_duration_seconds'] == 1200
    assert sum(policy['weights'].values()) == pytest.approx(1)
    rows = [row('cheap', rent=0), row('costlier')]
    baseline = ranking().rank_rows(deepcopy(rows), current)
    candidate = ranking().rank_rows(deepcopy(rows), current, config={'rent_weight_multiplier': 1.25})
    assert candidate[0]['rank_score'] < baseline[0]['rank_score']
    assert candidate[0]['ranking_factors']['monthly_rent_toman']['weight'] > baseline[0]['ranking_factors']['monthly_rent_toman']['weight']


@pytest.mark.parametrize('config', [{'unknown': 1}, {'rent_weight_multiplier': True},
                                    {'rent_weight_multiplier': 0}, {'rent_weight_multiplier': float('nan')}])
def test_invalid_experiment_configuration_is_rejected(config):
    with pytest.raises(ValueError):
        ranking().policy(state(), config)
