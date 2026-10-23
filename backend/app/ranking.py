"""Stable utility and exact tie-breaks; scores are costs, never probabilities."""
from .contracts import RANKER_VERSION

FIELDS = ('monthly_rent_toman', 'deposit_toman', 'total_duration_seconds', 'walk_duration_seconds', 'transfers')
REFERENCES = (30_000_000, 1_000_000_000, 3600, 900, 3)
WEIGHTS = {
    'balanced': (.30, .20, .25, .15, .10),
    'lower_rent': (.60, .20, .10, .06, .04),
    'faster_commute': (.15, .10, .55, .12, .08),
    'less_walking': (.15, .10, .15, .52, .08),
    'fewer_transfers': (.15, .10, .15, .10, .50),
}


def nullable(value):
    return (value is None, value if value is not None else 0)


def policy(state, config=None):
    if getattr(state, 'accessibility', None) and state.accessibility.enabled:
        from .accessibility_ranking import policy as accessibility_policy
        return accessibility_policy(state, config)
    weights = list(WEIGHTS[state.preference])
    multiplier = (config or {}).get('rent_weight_multiplier', 1.0)
    if set(config or {}) - {'rent_weight_multiplier'} or not isinstance(multiplier, (int, float)) or not 0.1 <= multiplier <= 4:
        raise ValueError('Unsupported ranking configuration')
    weights[0] *= multiplier
    for soft in state.soft_preferences:
        position = {'lower_rent': 0, 'faster_commute': 2, 'less_walking': 3, 'fewer_transfers': 4}.get(soft)
        if position is not None and soft != state.preference:
            weights[position] *= 1.5
    if state.travel.destination is None:
        weights[2:] = [0, 0, 0]
    total = sum(weights)
    scales = [state.property.max_monthly_rent_toman, state.property.max_deposit_toman,
              state.travel.max_duration_seconds, state.travel.max_walk_seconds, state.travel.max_transfers]
    return {'version': RANKER_VERSION, 'configuration': config or {}, 'weights': dict(zip(FIELDS, [w / total for w in weights])),
            'scales': dict(zip(FIELDS, [v if v is not None and v > 0 else ref for v, ref in zip(scales, REFERENCES)])),
            'mode': 'finance_only' if state.travel.destination is None else 'finance_and_verified_travel',
            'soft_amenity_bonus': 0.025, 'unknown_penalty': 1.0,
            'normalization': 'min(value / explicit_cap_or_reference, 1); unknown=1',
            'semantic_policy': 'retrieval_priority_and_exact_utility_ties_only',
            'score_meaning': 'lower cost is better; not a probability'}


def rank_rows(rows, state, semantic_ids=None, config=None):
    if getattr(state, 'accessibility', None) and state.accessibility.enabled:
        from .accessibility_ranking import rank_rows as accessibility_rank_rows
        return accessibility_rank_rows(rows, state, semantic_ids, config)
    ranking = policy(state, config)
    priority = {pid: index for index, pid in enumerate(semantic_ids or [])}
    for row in rows:
        facts = {**row['property'], **(row.get('selected_itinerary') or {})}
        factors = {}
        for field in FIELDS:
            actual = facts.get(field)
            normalized = 1.0 if actual is None else min(actual / ranking['scales'][field], 1.0)
            factors[field] = {'value': actual, 'scale': ranking['scales'][field],
                              'weight': ranking['weights'][field], 'cost': normalized * ranking['weights'][field],
                              'unknown': actual is None}
        bonus = sum(0.025 for key in ('parking', 'elevator') if key in state.soft_preferences and facts.get(key) is True)
        row['rank_score'] = sum(f['cost'] for f in factors.values()) - bonus
        row['ranking_factors'] = factors
        row['soft_amenity_bonus'] = bonus
        row['ranking_policy_version'] = RANKER_VERSION
    field_orders = {
        'rent_asc': ('monthly_rent_toman', 'deposit_toman'),
        'deposit_asc': ('deposit_toman', 'monthly_rent_toman'),
        'travel_time_asc': ('total_duration_seconds', 'walk_duration_seconds', 'transfers', 'monthly_rent_toman'),
        'walk_time_asc': ('walk_duration_seconds', 'total_duration_seconds', 'monthly_rent_toman'),
        'transfers_asc': ('transfers', 'total_duration_seconds', 'walk_duration_seconds'),
    }
    def key(row):
        pid = row['property']['property_id']
        if state.sort == 'recommended':
            return (row['rank_score'], priority.get(pid, len(priority)), pid)
        facts = {**row['property'], **(row.get('selected_itinerary') or {})}
        return (*[nullable(facts.get(field)) for field in field_orders[state.sort]], pid)
    return sorted(rows, key=key)
