"""Explicit local acceptance flow; bounded live OTP calls and no paid AI calls."""
import argparse
import json
import time
from copy import deepcopy
from pathlib import Path

import httpx

from .benchmark import percentiles
from .db import utcnow


def wait_result(client, result):
    deadline = time.monotonic() + 90
    while result['completion_status'] in ('queued', 'running') and time.monotonic() < deadline:
        time.sleep(.25)
        result = client.get('/api/searches/' + result['request_id']).json()
    return result


def run(base_url):
    with httpx.Client(base_url=base_url, timeout=90) as client:
        state = client.get('/api/state/default').json()
        inventory = client.get('/api/inventory').json()
        known = json.loads(Path('data/otp/contract-input.json').read_text(encoding='utf-8-sig'))
        origin = known['origin']
        nearest = min(inventory['properties'], key=lambda p: (p['latitude'] - origin['latitude']) ** 2 + (p['longitude'] - origin['longitude']) ** 2)
        neighborhood = nearest['neighborhood_ids'][0]
        items = sorted([p for p in inventory['properties'] if neighborhood in p['neighborhood_ids']], key=lambda p: p['monthly_rent_toman'])
        state['selected_neighborhood_ids'] = [neighborhood]
        state['property']['max_monthly_rent_toman'] = items[min(2, len(items) - 1)]['monthly_rent_toman']
        # The benchmark destination and date were previously verified against this local OTP feed.
        travel = known.get('travel', known)
        state['travel'].update({key: travel[key] for key in ('date', 'time', 'time_mode', 'modes') if key in travel})
        state['travel']['destination'] = {**travel['destination'], 'confirmed': True}
        response = client.post('/api/searches', json={'state': state})
        response.raise_for_status()
        first = wait_result(client, response.json())
        first_snapshot = client.get('/api/searches/' + first['request_id'] + '/snapshot').json()
        next_state = deepcopy(first['state'])
        next_state['sort'] = 'walk_time_asc'
        response = client.post('/api/searches', json={'state': next_state, 'task_id': first['task_id'], 'parent_request_id': first['request_id']})
        response.raise_for_status()
        second = wait_result(client, response.json())
        explanation = client.post('/api/searches/' + second['request_id'] + '/explanation', json={'use_ai': False})
        explanation.raise_for_status()
        latencies = [r['routing_latency_ms'] for r in first_snapshot.get('evaluations', {}).values() if not r.get('cache_hit') and 'routing_latency_ms' in r]
        return {'checked_at': utcnow(), 'status': 'PASS' if first['results'] and second['results'] and second['cache_misses'] == 0 else 'FAIL',
            'candidate_count': first['candidate_count'], 'evaluated_count': first['evaluated_count'],
            'eligible_count': first['eligible_count'], 'completion_status': first['completion_status'],
            'route_statuses': [r['route_status'] for r in first['results']],
            'initial_cache_hits': first['cache_hits'], 'initial_cache_misses': first['cache_misses'],
            'sort_only_cache_hits': second['cache_hits'], 'sort_only_cache_misses': second['cache_misses'],
            'otp_latency': percentiles(latencies) if latencies else {'samples': 0, 'reason': 'all routes already cached'},
            'selected_itinerary_policy': 'walk_time_asc selects least total walking among jointly qualifying returned itineraries',
            'explanation_mode': explanation.json()['mode'], 'paid_requests': 0,
            'schedule_basis': sorted({r['selected_itinerary']['schedule_basis'] for r in first['results']}),
            'transfer_values': [r['selected_itinerary']['transfers'] for r in first['results']],
            'source_kinds': sorted({r['selected_itinerary']['source_kind'] for r in first['results']}),
            'scope': 'three price-selected demo properties near the verified OTP origin; not a global relevance measurement'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--report', default='docs/phase-2-live-acceptance.json')
    args = parser.parse_args()
    result = run(args.base_url)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
