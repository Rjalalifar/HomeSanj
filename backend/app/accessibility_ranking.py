"""Transparent profile costs derived only from the chosen accessibility result.

Destination weights are rent 0.30, deposit 0.20, itinerary time 0.35 and all
walking time 0.15. Nearby-stop weights are rent 0.30, deposit 0.20, walking
time 0.35 and straight-line distance 0.15. Positive explicit caps replace
the fixed scale references. Each component is min(value / scale, 1);
unknown evidence costs 1. These costs are not relevance probabilities.
"""
from math import isfinite


RANKER_VERSION = 'accessibility-ranker-1'
PROFILES = {
    'destination': {
        'monthly_rent_toman': (0.30, 30_000_000),
        'deposit_toman': (0.20, 1_000_000_000),
        'total_duration_seconds': (0.35, 3600),
        'walk_duration_seconds': (0.15, 900),
    },
    'nearby_stop': {
        'monthly_rent_toman': (0.30, 30_000_000),
        'deposit_toman': (0.20, 1_000_000_000),
        'walk_duration_seconds': (0.35, 900),
        'straight_line_meters': (0.15, 1000),
    },
}
SORT_FIELDS = {
    'rent_asc': 'monthly_rent_toman',
    'deposit_asc': 'deposit_toman',
    'travel_time_asc': 'total_duration_seconds',
    'walk_time_asc': 'walk_duration_seconds',
    'stop_walk_time_asc': 'walk_duration_seconds',
    'stop_distance_asc': 'straight_line_meters',
}


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if isfinite(value) and value >= 0 else None


def policy(state, config=None):
    access = _get(state, 'accessibility')
    mode = _get(access, 'mode') or ('destination' if _get(_get(state, 'travel'), 'destination') else 'nearby_stop')
    if mode not in PROFILES:
        raise ValueError('Unsupported accessibility ranking profile')
    configuration = dict(config or {})
    multiplier = _number(configuration.get('rent_weight_multiplier', 1.0))
    if set(configuration) - {'rent_weight_multiplier'} or multiplier is None or not 0.1 <= multiplier <= 4:
        raise ValueError('Unsupported ranking configuration')
    profile = PROFILES[mode]
    weights = {field: weight for field, (weight, _) in profile.items()}
    weights['monthly_rent_toman'] *= multiplier
    total = sum(weights.values())
    property_rules = _get(state, 'property')
    travel = _get(state, 'travel')
    caps = {
        'monthly_rent_toman': _get(property_rules, 'max_monthly_rent_toman'),
        'deposit_toman': _get(property_rules, 'max_deposit_toman'),
        'total_duration_seconds': _get(travel, 'max_duration_seconds') if mode == 'destination' else None,
        'walk_duration_seconds': _get(travel, 'max_walk_seconds') if mode == 'destination' else _get(access, 'max_walk_seconds'),
        'straight_line_meters': _get(access, 'max_straight_line_meters'),
    }
    scales = {}
    for field, (_, reference) in profile.items():
        cap = _number(caps[field])
        scales[field] = cap if cap is not None and cap > 0 else reference
    return {
        'version': RANKER_VERSION,
        'mode': mode,
        'configuration': configuration,
        'weights': {field: weight / total for field, weight in weights.items()},
        'scales': scales,
        'unknown_penalty': 1.0,
        'normalization': 'min(value / explicit_positive_cap_or_reference, 1); unknown=1',
        'soft_amenity_bonus': 0.0,
        'semantic_policy': 'exact_utility_ties_only',
        'tie_break': 'property_id after requested sort metric; semantic priority only for recommended cost ties',
        'score_meaning': 'lower cost is better; not a probability',
        'route_metrics': 'same chosen accessibility result with status=ok; no selected-itinerary fallback',
        'distance_metric': 'straight-line meters to an identified stop; independent of route availability',
    }


def _facts(row, mode):
    listing = row['property']
    result = row.get('accessibility') or {}
    same_mode = result.get('mode') == mode
    route_ok = same_mode and result.get('status') == 'ok'
    stop = result.get('nearest_stop') or {}
    stop_id = stop.get('stop_id')
    facts = {
        'monthly_rent_toman': listing.get('monthly_rent_toman'),
        'deposit_toman': listing.get('deposit_toman'),
        'total_duration_seconds': result.get('total_duration_seconds') if route_ok and mode == 'destination' else None,
        'walk_duration_seconds': result.get('walk_duration_seconds') if route_ok else None,
        'straight_line_meters': result.get('straight_line_meters') if same_mode and mode == 'nearby_stop' and stop_id else None,
    }
    return {field: _number(value) for field, value in facts.items()}


def rank_rows(rows, state, semantic_ids=None, config=None):
    ranking = policy(state, config)
    priority = {pid: index for index, pid in enumerate(dict.fromkeys(semantic_ids or []))}
    for row in rows:
        facts = _facts(row, ranking['mode'])
        factors = {}
        for field, weight in ranking['weights'].items():
            actual = facts[field]
            scale = ranking['scales'][field]
            normalized = 1.0 if actual is None else min(actual / scale, 1.0)
            factors[field] = {'value': actual, 'scale': scale, 'weight': weight,
                              'cost': normalized * weight, 'unknown': actual is None}
        row['rank_score'] = sum(factor['cost'] for factor in factors.values())
        row['ranking_factors'] = factors
        row['soft_amenity_bonus'] = 0.0
        row['ranking_policy_version'] = RANKER_VERSION
    sort = _get(state, 'sort', 'recommended')
    if sort != 'recommended' and sort not in SORT_FIELDS:
        raise ValueError('Unsupported accessibility sort')

    def key(row):
        pid = row['property']['property_id']
        if sort == 'recommended':
            return (row['rank_score'], priority.get(pid, len(priority)), pid)
        value = _facts(row, ranking['mode'])[SORT_FIELDS[sort]]
        return (value is None, value if value is not None else 0, pid)

    return sorted(rows, key=key)
