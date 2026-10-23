"""Pure versioned metrics over frozen evidence, independent of search and providers."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import random
import statistics

METRIC_VERSION = 'graded-fixed-pool-1'
RUBRIC_VERSION = 'hard-pass-relevance-0-3-1'
QS_VERSION = 'first-final-explicit-24h-1'


def ratio(numerator, denominator, reason=None):
    return {'value': numerator / denominator if numerator is not None and denominator else None,
            'numerator': numerator, 'denominator': denominator,
            'reason': reason if reason else ('zero_denominator' if not denominator else None)}


def relevant(item):
    if item and item.get('hard') == 'fail':
        return False
    if not item or item.get('grade') is None or item.get('hard') != 'pass':
        return None
    return item['grade'] >= 2 and item.get('hard') == 'pass'


def ranking_metrics(order, pool):
    if len(order) != len(set(order)):
        raise ValueError('Ranking contains duplicate canonical IDs')
    if any(v.get('grade') not in (None, 0, 1, 2, 3) for v in pool.values()):
        raise ValueError('Grade must be 0..3 or null')
    top = order[:5]
    labels = [relevant(pool.get(pid)) for pid in top]
    complete_top = all(v is not None for v in labels)
    complete_pool = bool(pool) and all(relevant(v) is not None for v in pool.values()) and set(order) <= set(pool)
    precision = ratio(sum(v is True for v in labels) if complete_top else None, 5,
                      None if complete_top else 'unjudged_displayed_card')
    reciprocal = 0.0
    for rank, value in enumerate(labels, 1):
        if value is None:
            reciprocal = None
            break
        if value:
            reciprocal = 1 / rank
            break
    gains = lambda pid: 2 ** pool[pid]['grade'] - 1 if pool[pid]['hard'] == 'pass' else 0
    ideal = sum(g / math.log2(i + 2) for i, g in enumerate(sorted((gains(p) for p in pool), reverse=True)[:5])) if complete_pool else None
    dcg = sum(gains(p) / math.log2(i + 2) for i, p in enumerate(top)) if complete_pool else None
    positives = sum(relevant(v) is True for v in pool.values()) if complete_pool else None
    hits = sum(relevant(pool.get(p)) is True for p in order[:20]) if complete_pool else None
    def hit(origin):
        vals = [relevant(pool.get(p)) if pool.get(p, {}).get('origin') == origin else None for p in top]
        value = 1 if True in vals else (0 if all(v is not None for v in vals) else None)
        return ratio(value, 1, 'unjudged_origin' if value is None else None)
    return {'ndcg_at_5': ratio(dcg, ideal, 'unjudged_pool' if ideal is None else ('idcg_zero' if ideal == 0 else None)),
            'precision_at_5': precision, 'mrr_at_5': ratio(reciprocal, 1, 'earlier_unjudged' if reciprocal is None else None),
            'recall_at_20_fixed_pool': ratio(hits, positives, 'unjudged_pool' if not complete_pool else None),
            'human_hit_rate_at_5': hit('human'), 'judge_hit_rate_at_5': hit('ai_weak'),
            'judged_coverage': ratio(sum(relevant(v) is not None for v in pool.values()), len(pool)),
            'pool_size': len(pool), 'fully_judged_pool': complete_pool, 'metric_version': METRIC_VERSION}


def qualified_success(tasks, now=None, window_hours=24):
    now = now or datetime.now(timezone.utc)
    counts = dict(S=0, F=0, U=0, pending=0)
    for task in tasks:
        deadline = datetime.fromisoformat(task['created_at']) + timedelta(hours=window_hours)
        if now < deadline:
            counts['pending'] += 1
            continue
        events = [f for f in task['feedback'] if not f.get('created_at') or datetime.fromisoformat(f['created_at']) <= deadline]
        valid = set(task['frozen_ids']) & set(task['hard_pass_ids'])
        success = failure = False
        confirmed = set()
        for event in events:
            ids = set(event['candidate_ids'])
            if event['label'] == 'positive':
                if ids & valid:
                    confirmed = ids & valid
                    success, failure = True, False
                elif event['kind'] == 'top5':
                    success = failure = False
            elif event['kind'] == 'top5' and not ids:
                success, failure, confirmed = False, True, set()
            elif ids & confirmed:
                confirmed -= ids
                success = bool(confirmed)
        terminal_empty = not task['frozen_ids'] and task['completion_status'] in ('complete', 'failed', 'deadline_no_result')
        counts['S' if success else 'F' if failure or terminal_empty else 'U'] += 1
    s, f, u = counts['S'], counts['F'], counts['U']
    n = s + f + u
    return {**counts, 'N': n, 'qs_at_5': ratio(s, s+f), 'coverage': ratio(s+f, n),
            'confirmed_success_over_all_tasks': ratio(s, n),
            'missing_outcome_bounds': [s/n, (s+u)/n] if n else None,
            'bounds_are_confidence_interval': False, 'policy_version': QS_VERSION,
            'window_hours': window_hours, 'status': 'ok' if s+f else 'insufficient_data'}


def grouped_bootstrap(pairs, seed=17, repetitions=2000):
    groups = defaultdict(list)
    for group, difference in pairs:
        if difference is not None:
            groups[group].append(difference)
    values = [statistics.mean(v) for v in groups.values()]
    if len(values) < 2:
        return {'status': 'insufficient_evidence', 'independent_tasks': len(values), 'interval': None}
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(repetitions))
    return {'status': 'ok', 'independent_tasks': len(values), 'mean_difference': statistics.mean(values),
            'interval': [samples[int(repetitions*.025)], samples[min(repetitions-1, int(repetitions*.975))]],
            'method': 'paired_intent_group_percentile_bootstrap', 'seed': seed, 'repetitions': repetitions}


def hard_constraint_rates(rows):
    checks = [r.get('property_verdicts', []) + r.get('travel_verdicts', []) for r in rows]
    return {'hard_violation': ratio(sum(any(v['verdict'] == 'fail' for v in c) for c in checks), len(checks)),
            'unknown_shown_verified': ratio(sum(any(v['verdict'] == 'unknown' for v in c) for c in checks), len(checks))}
