"""Explicit real-Qdrant relevance checks on an isolated authored Persian fixture."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

from .db import Database, utcnow
from .normalize import normalize_text
from .semantic import SemanticService, SemanticSettings, reciprocal_rank_fusion


class FixtureGeography:
    def __init__(self, names):
        self.names = names

    def feature(self, identifier):
        return {'properties': {'name_fa': self.names[identifier]}}

    def district_memberships(self, longitude, latitude):
        return []


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


async def benchmark(fixture_path, report_path):
    fixture = json.loads(Path(fixture_path).read_text(encoding='utf-8-sig'))
    settings = replace(SemanticSettings.from_env(), collection='homesanj_relevance_fixture_v1', candidates=8, enabled=True)
    db = Database('sqlite:///:memory:')
    db.migrate()
    defaults = {'district_membership_status': 'unknown', 'title_fa': 'آگهی آزمون مصنوعی',
        'latitude': None, 'longitude': None, 'source_records': [], 'published_at': None, 'collected_at': None,
        'is_synthetic': True, 'dataset_version': fixture['fixture_version'], 'seed': 0}
    db.insert_listings([{**defaults, **item} for item in fixture['properties']])
    service = SemanticService(db, FixtureGeography(fixture['neighborhoods']), settings)
    index_report = await asyncio.to_thread(service.reconcile, index=True)
    canonical = service.canonical()
    lexical = sqlite3.connect(':memory:')
    lexical.execute('CREATE VIRTUAL TABLE descriptions USING fts5(property_id UNINDEXED, description)')
    lexical.executemany('INSERT INTO descriptions VALUES (?, ?)',
                       [(identifier, item['description']) for identifier, item in canonical.items()])
    rows = []
    # The benchmark measures raw retrieval; it does not treat retrieval as eligibility.
    for query in fixture['queries']:
        semantic = await service.retrieve(query['text'], list(canonical))
        started = time.perf_counter()
        terms = re.findall(r'\w+', normalize_text(query['text']))[:30]
        expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
        fts_ids = [row[0] for row in lexical.execute(
            'SELECT property_id FROM descriptions WHERE descriptions MATCH ? ORDER BY bm25(descriptions), property_id LIMIT 8',
            (expression,))]
        fts_ms = round((time.perf_counter() - started) * 1000, 2)
        vector_ids = semantic['property_ids']
        hybrid_ids, _ = reciprocal_rank_fusion(vector_ids, fts_ids)
        relevant = set(query['relevant_ids'])
        entry = {'query_id': query['query_id'], 'query_text': query['text'], 'relevant_ids': sorted(relevant),
                 'semantic_status': semantic['status'], 'semantic_latency_ms': semantic['latency_ms'],
                 'fts_latency_ms': fts_ms, 'vector_ids': vector_ids, 'fts_ids': fts_ids, 'hybrid_ids': hybrid_ids}
        for name, ids in [('vector', vector_ids), ('fts', fts_ids), ('hybrid', hybrid_ids)]:
            entry[name + '_recall_at_3'] = len(relevant.intersection(ids[:3])) / len(relevant)
            entry[name + '_recall_at_5'] = len(relevant.intersection(ids[:5])) / len(relevant)
        rows.append(entry)
    lexical.close()
    result = {'status': 'passed' if all(row['semantic_status'] == 'ok' for row in rows) else 'failed',
        'measured_at': utcnow(), 'fixture_version': fixture['fixture_version'], 'label_origin': fixture['label_origin'],
        'collection': settings.collection, 'model': settings.model, 'model_revision': settings.revision,
        'index_version': settings.index_version, 'fixture_properties': len(canonical), 'query_count': len(rows),
        'policy': 'Cosine vector ranking; FTS5 BM25 OR terms; RRF constant 60 over each full fixture ranking',
        'limitations': ['Small authored synthetic fixture; not user relevance labels or a production holdout.',
                       'Measures paraphrase retrieval only; does not establish Hit Rate improvement or hard eligibility.',
                       'The encoder may be warm from indexing; latency includes actual service work.'],
        'summary': {name + f'_recall_at_{k}': sum(row[name + f'_recall_at_{k}'] for row in rows) / len(rows)
                    for name in ('vector', 'fts', 'hybrid') for k in (3, 5)},
        'latency_ms': {'semantic_p50': percentile([row['semantic_latency_ms'] for row in rows], .5),
                       'semantic_p95': percentile([row['semantic_latency_ms'] for row in rows], .95),
                       'fts_p50': percentile([row['fts_latency_ms'] for row in rows], .5),
                       'fts_p95': percentile([row['fts_latency_ms'] for row in rows], .95)},
        'index_report': {key: value for key, value in index_report.items() if key not in ('changed_property_ids', 'orphan_point_ids')},
        'queries': rows}
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('queries', 'index_report')},
                     ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', default='tests/fixtures/persian-semantic-relevance.json')
    parser.add_argument('--report', default='docs/semantic-benchmark.json')
    args = parser.parse_args()
    asyncio.run(benchmark(args.fixture, args.report))
