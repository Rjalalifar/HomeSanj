"""Explicit maintenance commands; seed and ordinary tests never call a paid provider."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import Settings
from .db import Database


def write_report(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(prog='python -m backend.app.cli')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    seed = sub.add_parser('seed')
    seed.add_argument('--seed', type=int, default=2026)
    seed.add_argument('--dataset-version', default='tehran-2020-v1')
    seed.add_argument('--points-per-series-per-neighborhood', type=int, default=5)
    seed.add_argument('--limit-neighborhoods', type=int)
    seed.add_argument('--report', default='data/seed-report.json')
    imp = sub.add_parser('import')
    imp.add_argument('path')
    imp.add_argument('--kind', choices=['csv_a', 'json_b'], required=True)
    imp.add_argument('--dataset-version', default='tehran-2020-v1')
    imp.add_argument('--real', action='store_true', help='Explicitly mark genuine source data; fixtures remain synthetic by default')
    imp.add_argument('--report', default='runtime/import-report.json')
    sub.add_parser('export-schema')
    sub.add_parser('worker')
    smoke = sub.add_parser('avalai-smoke')
    smoke.add_argument('--allow-paid', action='store_true')
    smoke.add_argument('--max-requests', type=int, default=1)
    smoke.add_argument('--report', default='docs/avalai-smoke-report.json')
    args = parser.parse_args()
    settings = Settings.from_env()
    db = Database(settings.database_url)
    db.migrate()
    if args.command == 'migrate':
        print('Schema migrations 1-4 applied or already current; search, feedback and evaluation tables ready.')
    elif args.command == 'seed':
        from .geo import GeometryStore
        from .seed import generate_listings
        if not 1 <= args.points_per_series_per_neighborhood <= 100:
            parser.error('points-per-series-per-neighborhood must be 1..100')
        if args.limit_neighborhoods is not None and args.limit_neighborhoods < 1:
            parser.error('limit-neighborhoods must be positive')
        geo = GeometryStore(settings.data_dir)
        if geo.dataset_version != args.dataset_version:
            parser.error('dataset-version must match the loaded geometry manifest')
        items, report = generate_listings(geo, args.seed, args.dataset_version,
            args.points_per_series_per_neighborhood, args.limit_neighborhoods)
        report['storage'] = db.insert_listings(items)
        write_report(args.report, report)
        print(json.dumps({'report': args.report, 'generated_count': len(items), **report['storage']}, ensure_ascii=True))
    elif args.command == 'import':
        from .geo import GeometryStore
        from .importers import import_listings
        geo = GeometryStore(settings.data_dir)
        items, report = import_listings(args.path, args.kind, args.dataset_version, geo, synthetic=not args.real)
        report['storage'] = db.insert_listings(items)
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=True))
    elif args.command == 'export-schema':
        from .export_schema import export_schema
        print(export_schema())
    elif args.command == 'worker':
        from .routing import OTPAdapter, OTPSettings
        from .worker import RoutingWorker
        asyncio.run(RoutingWorker(db, OTPAdapter(OTPSettings.from_env()), settings).run())
    elif args.command == 'avalai-smoke':
        from .llm import AvalAIProvider
        if not args.allow_paid:
            report = {'status': 'not_run', 'reason': 'Explicit --allow-paid flag is required; no paid request made.'}
        else:
            provider = AvalAIProvider(db)
            provider.daily_limit = min(provider.daily_limit, max(0, args.max_requests))
            provider.retries = 0
            report = asyncio.run(provider.smoke(max_requests=max(0, args.max_requests)))
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
