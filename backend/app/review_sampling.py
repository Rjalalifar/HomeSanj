"""Seeded stratified acquisition with an explicitly conditional random probability."""
from collections import defaultdict, deque
import random


def classify(row, replay, feedback_labels):
    verdicts = row.get('property_verdicts', []) + row.get('travel_verdicts', [])
    if any(v['verdict'] == 'fail' for v in verdicts):
        return 'critical', 'hard_constraint_violation'
    if len(feedback_labels) > 1:
        return 'disagreement', 'explicit_feedback_disagreement'
    pid = row['property']['property_id']
    retrieval = replay.get('retrieval') or {}
    signal = retrieval.get('retrieval_signals', {}).get(pid, {})
    if bool(signal.get('vector_rank')) != bool(signal.get('lexical_rank')):
        return 'disagreement', 'vector_lexical_disagreement'
    if row.get('route_status') in ('timeout', 'api_error', 'invalid_response'):
        return 'uncertainty', 'infrastructure_issue'
    if any(v['verdict'] == 'unknown' for v in verdicts):
        return 'uncertainty', 'missing_evidence'
    if retrieval.get('stale_hit_count', 0) or retrieval.get('reason') in ('stale_index_hits_rejected', 'qdrant_index_version_mismatch'):
        return 'uncertainty', 'index_stale'
    if any(row['property'].get(k) is None for k in ('monthly_rent_toman', 'deposit_toman', 'parking', 'elevator')):
        return 'uncertainty', 'missing_optional_evidence'
    return 'novelty', 'low_label_coverage'


def select_batch(frames, strata, batch_size, seed):
    rng = random.Random(seed)
    def stratified(keys):
        buckets = defaultdict(list)
        for key in sorted(set(keys)):
            frozen, _, _ = frames[key]
            buckets[(frozen['mode'], frozen['task_id'])].append(key)
        for values in buckets.values():
            rng.shuffle(values)
        order = sorted(buckets)
        rng.shuffle(order)
        output = []
        queues = [deque(buckets[k]) for k in order]
        while any(queues):
            for queue in queues:
                if queue:
                    output.append(queue.popleft())
        return output
    critical = stratified(strata.get('critical', []))
    picked = [(key, 'critical', None) for key in critical]
    taken = set(critical)
    quotas = {'disagreement': batch_size*10//20, 'uncertainty': batch_size*4//20, 'novelty': batch_size*4//20}
    for category, quota in quotas.items():
        selected = [k for k in stratified(strata.get(category, [])) if k not in taken][:quota]
        picked.extend((key, category, None) for key in selected)
        taken.update(selected)
    remaining = sorted(set(frames)-taken)
    count = min(len(remaining), max(0, batch_size - sum(kind != 'critical' for _, kind, _ in picked)))
    picked.extend((key, 'random', count/len(remaining)) for key in rng.sample(remaining, count))
    return picked
