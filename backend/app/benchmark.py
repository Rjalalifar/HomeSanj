"""Explicit reproducible local SQLite/API benchmarks; no paid model calls."""
import argparse
import json
import math
import statistics
import time
from pathlib import Path

import httpx
from sqlalchemy import text

from .catalog import Catalog
from .config import Settings
from .db import Database, utcnow
from .geo import GeometryStore


def percentiles(values):
    ordered = sorted(values)
    return {'samples': len(values), 'p50_ms': statistics.median(ordered),
            'p95_ms': ordered[max(0, math.ceil(len(ordered) * .95) - 1)]}


def run(base_url, count):
    settings = Settings.from_env()
    db = Database(settings.database_url)
    db.migrate()
    catalog = Catalog(db, GeometryStore(settings.data_dir))
    catalog.refresh()
    query = 'SELECT property_id FROM listings WHERE dataset_version=:version AND monthly_rent_toman<=:rent ORDER BY monthly_rent_toman,deposit_toman,property_id LIMIT 100'
    args = {'version': catalog.geo.dataset_version, 'rent': 20_000_000}
    sql_times, fts_times = [], []
    with db.engine.connect() as connection:
        plan = [list(row) for row in connection.execute(text('EXPLAIN QUERY PLAN ' + query), args)]
        for _ in range(count):
            started = time.perf_counter()
            list(connection.execute(text(query), args))
            sql_times.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            catalog.lexical('پارکینگ', 100)
            fts_times.append((time.perf_counter() - started) * 1000)
    api_times = []
    with httpx.Client(base_url=base_url, timeout=120) as client:
        state = client.get('/api/state/default').json()
        state['property']['max_monthly_rent_toman'] = 20_000_000
        state['selected_neighborhood_ids'] = [catalog.public['properties'][0]['neighborhood_ids'][0]]
        for _ in range(min(count, 10)):
            started = time.perf_counter()
            response = client.post('/api/searches', json={'state': state})
            response.raise_for_status()
            api_times.append((time.perf_counter() - started) * 1000)
            assert response.json()['evaluated_count'] == 0
            assert response.json()['semantic']['status'] == 'not_requested'
    return {'checked_at': utcnow(), 'inventory_count': catalog.public['count'],
            'sqlite_indexed': percentiles(sql_times), 'fts5': percentiles(fts_times), 'query_plan': plan,
            'normal_api_snapshot_creation': percentiles(api_times),
            'api_workload': 'one actual neighborhood, rent <= 20m, no destination; immutable snapshot and measurement',
            'fts5_available': catalog.fts, 'paid_requests': 0,
            'limitations': 'Local warm-process serial measurements; not a concurrent throughput claim.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--report', default='docs/sqlite-phase-2-benchmark.json')
    args = parser.parse_args()
    result = run(args.base_url, max(3, min(100, args.count)))
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
