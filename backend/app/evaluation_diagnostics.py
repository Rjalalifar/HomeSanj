"""Diagnostic rates with explicit denominators and no invented missing evidence."""
from collections import Counter
import math
from .evaluation_metrics import ratio


def percentiles(values):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    def quantile(p):
        if not values:
            return None
        index = (len(values)-1)*p
        lo, hi = math.floor(index), math.ceil(index)
        return values[lo] + (values[hi]-values[lo])*(index-lo)
    return {'count': len(values), 'p50': quantile(.5), 'p95': quantile(.95), 'unit': 'ms'}


def state_accuracy(expected, actual):
    def flatten(value, prefix=''):
        output = {}
        for key, item in value.items():
            path = prefix + key
            if isinstance(item, dict):
                output.update(flatten(item, path + '.'))
            else:
                output[path] = item
        return output
    truth, predicted = flatten(expected), flatten(actual)
    keys = set(truth) | set(predicted)
    fields = {k: k in truth and k in predicted and truth[k] == predicted[k] for k in sorted(keys)}
    return {'exact_state': int(all(fields.values())), 'field_accuracy': ratio(sum(fields.values()), len(fields)), 'fields': fields}


def groundedness(explanation):
    from .explanations import TypedClaim, render_claim
    facts = explanation.get('evidence', {})
    allowed = {key.split(':')[1] for key in facts if key.startswith('property:')}
    claims = list(explanation.get('ai_selected_claims', []))
    for recommendation in explanation.get('recommendations', []):
        for kind in ('strengths', 'tradeoffs', 'unknowns'):
            claims += recommendation.get(kind, [])
    counts = Counter(correct=0, unsupported=0, contradicted=0, unknown=0)
    for item in claims:
        if not item.get('claim') or not item.get('evidence_refs') or not set(item['evidence_refs']) <= set(facts):
            counts['unsupported'] += 1
            continue
        try:
            canonical = render_claim(TypedClaim.model_validate(item['claim']), facts, allowed)
            if canonical['evidence_refs'] != item['evidence_refs'] or canonical['text'] != item.get('text'):
                counts['contradicted'] += 1
            else:
                counts['correct'] += 1
                counts['unknown'] += item['claim'].get('operator') == 'unknown'
        except (ValueError, KeyError):
            counts['contradicted'] += 1
    return {**dict(counts), 'no_claim': len(claims) == 0, 'groundedness': ratio(counts['correct'], len(claims)),
            'recommended_id_valid': explanation.get('recommended_property_id') in allowed if explanation.get('recommended_property_id') else None}


def human_judge_agreement(pairs):
    known = [(h, j) for h, j in pairs if h is not None and j is not None]
    return {'common_independent_annotations': len(known),
        'binary_mismatch': ratio(sum((h >= 2) != (j >= 2) for h, j in known), len(known)),
        'grade_difference_at_least_two': ratio(sum(abs(h-j) >= 2 for h, j in known), len(known)),
        'confusion': dict(Counter(f'human_{h}_judge_{j}' for h, j in known)),
        'selection_bias': 'Review acquisition is not a representative random user sample'}
