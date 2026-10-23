"""Phase-3 evaluation CLI reusing production search, encoder, index and snapshots."""
import argparse
import ast
import asyncio
import json
import random
import time
from pathlib import Path
from sqlalchemy import select
from .config import Settings
from .db import Database, SearchRequest, utcnow
from .evaluation_replay import digest, freeze_manifest
from .evaluation_experiments import compare, release, latest_release
from .evaluation_dashboard import dashboard
from .annotation_datasets import export_dataset, import_dataset, group_split
from .evaluation_metrics import ratio, METRIC_VERSION, RUBRIC_VERSION


def write_report(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(value, indent=2, ensure_ascii=False).encode('utf-8'))


def corpus():
    cases = []
    for path in sorted(Path('tests').glob('test_*.py')):
        source = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                group = path.stem
                cases.append({'case_id': f'{path.as_posix()}::{node.name}',
                    'case_version': digest(ast.get_source_segment(source, node)),
                    'synthetic': True, 'source': 'existing_offline_regression_test',
                    'review_status': 'programmatic_hard_rule_expectations_not_human_gold',
                    'task_group': group, 'split': group_split(group), 'split_seed': 17,
                    'subjective_grade': None})
    if len(cases) < 60:
        raise ValueError('At least 60 versioned cases are required')
    return {'dataset_version': 'regression_' + digest(cases)[:20], 'count': len(cases), 'cases': cases,
        'split_policy': 'test_module_groups_keep_related_tests_together', 'human_gold_count': 0,
        'execution': 'python -m pytest -q --junitxml=docs/phase-3-pytest.xml',
        'note': 'Tests are referenced, not cloned. Split tags do not turn assertion fixtures into human relevance labels.'}


def demo(db):
    with db.session() as session:
        requests = list(session.scalars(select(SearchRequest).where(SearchRequest.completion_status == 'complete',
            SearchRequest.candidate_count.between(3, 100)).order_by(SearchRequest.created_at.desc()).limit(16)))
    if not requests:
        return {'status': 'not_run', 'reason': 'No existing complete candidate snapshots; create a manual search first'}
    chosen, signatures = [], set()
    for req in requests:
        signature = digest(req.state)
        if signature not in signatures:
            chosen.append(req.request_id)
            signatures.add(signature)
        if len(chosen) == 4:
            break
    manifests = [freeze_manifest(db, rid)['manifest_id'] for rid in chosen]
    experiment = compare(db, manifests, split='mechanical_demo')
    before = latest_release(db)
    promoted = release(db, experiment['experiment_id'])
    after = latest_release(db)
    rolled_back = release(db, scope='test', action='rollback', target_id=before['release_id'])
    restored = latest_release(db)
    assert after['config'] == experiment['candidate_config'] and restored['config'] == before['config']
    return {'status': 'mechanics_verified', 'synthetic': True, 'human_lift': None, 'experiment': experiment,
            'promotion': promoted, 'rollback': rolled_back, 'restored_config': restored['config'],
            'production_changed': False, 'label_provenance': 'existing demo snapshots; no fabricated labels', 'created_at': utcnow()}


def ann_audit(db, settings, k=20):
    from .geo import GeometryStore
    from .semantic import SemanticService, LocalEncoder, QdrantHTTP, point_id
    from .catalog import Catalog
    from .contracts import SearchState, SearchInput
    from .search import create_search, read_search
    geo = GeometryStore(settings.data_dir)
    service = SemanticService(db, geo)
    drift = service.reconcile()
    if drift['status'] != 'healthy':
        return {'status': 'not_run', 'reason': 'Index reconciliation found drift', 'reconciliation': drift}
    catalog = Catalog(db, geo)
    catalog.refresh()
    state = SearchState(dataset_version=geo.dataset_version, property={'max_monthly_rent_toman': 15_000_000, 'min_bedrooms': 1})
    rid = create_search(db, geo, SearchInput(state=state), settings, False, catalog=catalog)
    snapshot = read_search(db, rid, limit=100000)
    eligible = [r['property']['property_id'] for r in snapshot['results']]
    documents = service.canonical(eligible)
    population = sorted(pid for pid, doc in documents.items() if doc['is_active'])
    query_filter = {'must': [{'has_id': [point_id(pid) for pid in population]},
        {'key': 'is_active', 'match': {'value': True}},
        {'key': 'embedding_version', 'match': {'value': service.settings.index_version}}]}
    queries = ['آپارتمان دو اتاق با پارکینگ', 'خانه با آسانسور و اجاره کمتر', 'واحد کوچک یک خوابه', 'آپارتمان بزرگ سه اتاق']
    client = QdrantHTTP(service.settings)
    cases = []
    try:
        encoder = LocalEncoder.get(service.settings)
        info = client.info()
        for index, query in enumerate(queries):
            started = time.perf_counter()
            vector = encoder.encode([query], query=True)[0]
            embedding_ms = (time.perf_counter()-started)*1000
            body = {'query': vector, 'filter': query_filter, 'limit': min(k, len(population)), 'with_payload': ['property_id']}
            results, latencies = {}, {}
            for kind, exact in [('approximate', False), ('exact', True)]:
                started = time.perf_counter()
                answer = client.request('POST', client.path + '/points/query', body=body | {'params': {'exact': exact}})
                results[kind] = [p['payload']['property_id'] for p in answer.get('points', [])]
                latencies[kind] = (time.perf_counter()-started)*1000
            started = time.perf_counter()
            lexical = [pid for pid in catalog.lexical(query, any_token=True) if pid in documents][:k]
            lexical_ms = (time.perf_counter()-started)*1000
            from .semantic import reciprocal_rank_fusion
            hybrid, _ = reciprocal_rank_fusion(results['approximate'], lexical, population)
            independent = random.Random(17 + index).sample(population, min(k, len(population)))
            pool = sorted(set(population) | set(results['approximate']) | set(lexical) | set(hybrid[:k]) | set(independent))
            cases.append({'task_group': f'authored_intent_{index}', 'query': query, 'synthetic': True,
                'review_status': 'unjudged', 'source': 'authored_non_sensitive_query', 'K': k,
                'ann_recall_at_k': ratio(len(set(results['approximate']) & set(results['exact'])), len(results['exact'])),
                'normal_structured_ids': population, 'advanced_fts5_ids': lexical,
                'advanced_vector_ids': results['approximate'], 'advanced_hybrid_ids': hybrid[:k],
                'exact_vector_ids': results['exact'], 'independent_controlled_sample_ids': independent,
                'fixed_reference_pool_ids': pool, 'human_judged_count': 0,
                'semantic_recall': None, 'semantic_recall_status': 'unavailable_without_human_judged_pool',
                'latency_ms': {'embedding': embedding_ms, 'fts5': lexical_ms, **latencies},
                'hard_filter_outside_count': len(set(results['approximate']) - set(eligible)),
                'split': group_split(f'authored_intent_{index}'), 'split_seed': 17})
    finally:
        client.close()
    return {'status': 'ok', 'created_at': utcnow(), 'source_kind': 'actual_local_qdrant',
        'reference': 'https://qdrant.tech/documentation/search/',
        'reconciliation': drift, 'index_version': service.settings.index_version,
        'collection': service.settings.collection, 'collection_vector_config': info.get('config', {}).get('params', {}).get('vectors'),
        'same_vector_filter_population_budget': True, 'population_hash': digest(population),
        'distance': 'Cosine', 'K': k, 'independent_tasks': len(cases),
        'pool_policy': 'union of structured, FTS5, vector, hybrid and seeded independent sample; structured population exhaustive within these hard filters',
        'cases': cases, 'judged_coverage': ratio(0, sum(len(c['fixed_reference_pool_ids']) for c in cases)),
        'metric_version': METRIC_VERSION, 'rubric_version': RUBRIC_VERSION,
        'actor_cohort': 'demo', 'cost': {'avalai_calls': 0, 'external_model_cost': None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['corpus', 'snapshot', 'evaluate', 'demo', 'ann', 'dashboard', 'worker-once', 'export', 'import'])
    parser.add_argument('--request-id')
    parser.add_argument('--manifest-id', action='append', default=[])
    parser.add_argument('--split', choices=['validation', 'holdout', 'mechanical_demo'], default='validation')
    parser.add_argument('--directory', default='runtime/datasets')
    parser.add_argument('--output', default='docs/phase-3-evaluation-report.json')
    args = parser.parse_args()
    settings = Settings.from_env()
    db = Database(settings.database_url)
    db.migrate()
    if args.command == 'corpus':
        result = corpus()
    elif args.command == 'snapshot':
        result = freeze_manifest(db, args.request_id)
    elif args.command == 'evaluate':
        result = compare(db, args.manifest_id, split=args.split)
    elif args.command == 'demo':
        result = demo(db)
    elif args.command == 'ann':
        result = ann_audit(db, settings)
    elif args.command == 'dashboard':
        result = dashboard(db)
    elif args.command == 'export':
        result = export_dataset(db, args.directory)
    elif args.command == 'import':
        result = import_dataset(db, args.directory)
    else:
        from .offline_evaluation import OfflineWorker
        from .llm import AvalAIProvider
        result = {'processed': asyncio.run(OfflineWorker(db, AvalAIProvider(db)).tick())}
    write_report(args.output, result)
    print(json.dumps({'status': result.get('status', 'ok'), 'output': args.output, 'count': result.get('count')}))


if __name__ == '__main__':
    main()
