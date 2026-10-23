"""Local FastAPI application with explicit service health and replayable evidence."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from sqlalchemy import func, select

from .config import Settings
from .contracts import Contract, ParseInput, PatchOperation, SearchInput, SearchState, apply_patch
from .db import Database, Listing, SearchRequest
from .geo import GeometryStore
from .llm import AvalAIProvider, ProviderError
from .routing import ADAPTER_VERSION, OTPAdapter, OTPSettings
from .search import create_search, read_search, validate_geography
from .worker import RoutingWorker
from .integration import PhaseTwo
from .session import assert_owned
from .llm import limited_parse
from .state_audit import record_change
from .phase3_api import install_phase3


class PatchInput(Contract):
    state: SearchState
    operations: list[PatchOperation] = Field(max_length=40)


def create_app(settings=None, database=None, geo=None, adapter=None, start_worker=True):
    settings = settings or Settings.from_env()
    db = database or Database(settings.database_url)
    db.migrate()
    adapter = adapter or OTPAdapter(OTPSettings.from_env())
    context = {'geo': geo}
    provider = AvalAIProvider(db)
    worker = RoutingWorker(db, adapter, settings)

    def geography():
        if context['geo'] is None:
            try:
                context['geo'] = GeometryStore(settings.data_dir)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(503, 'Boundary data is missing; run python -m backend.app.geo') from exc
        return context['geo']

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            phase2.start()
        task = asyncio.create_task(worker.run()) if start_worker else None
        offline_task = asyncio.create_task(offline_worker.run()) if start_worker else None
        yield
        offline_worker.stopped = True
        if offline_task:
            offline_task.cancel()
            await asyncio.gather(offline_task, return_exceptions=True)
        await phase2.stop()
        if task:
            await worker.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        close = getattr(adapter, 'close', None)
        if close:
            await close()

    app = FastAPI(title='Khaneh Sanj', version='2.0.0', lifespan=lifespan)
    app.state.db, app.state.worker = db, worker
    phase2 = PhaseTwo(app, db, geography, settings, adapter, provider)

    @app.get('/api/health')
    def health():
        g = geography()
        with db.session() as session:
            count = session.scalar(select(func.count()).select_from(Listing).where(Listing.dataset_version == g.dataset_version))
        report = {}
        for path in [Path('data/otp/connection-report.json'), Path('data/otp/probe-report.json')]:
            if path.exists():
                report = json.loads(path.read_text(encoding='utf-8-sig'))
                break
        fixture = bool(getattr(adapter.settings, 'fixture_mode', False))
        return {'status': 'ok', 'schema_version': '1.0.0', 'dataset_version': g.dataset_version, 'listing_count': count,
                'otp': {'configured': adapter.configured, 'status': 'configured' if adapter.configured else 'not_configured',
                        'supported_modes': list(getattr(adapter.settings, 'supported_modes', []) or []),
                        'fixture_mode': fixture, 'root_reachable': report.get('root_reachable'),
                        'routing_api_verified': bool(adapter.settings.api_verified and not fixture and report.get('routing_api_verified', False) and report.get('base_url') == adapter.settings.base_url and report.get('api_path') == adapter.settings.api_path),
                        'test_status': report.get('contract_test_status', 'not_run'),
                        'verified_at': report.get('checked_at'),
                        'schedule_basis': adapter.settings.schedule_basis,
                        'transfer_count_available': adapter.settings.api_type != 'transmodel_v3'}, 'llm': provider.info(), 'advanced': phase2.info()}

    @app.get('/api/neighborhoods')
    def neighborhoods():
        g = geography()
        return {'type': 'FeatureCollection', 'features': g.neighborhoods, 'dataset_version': g.dataset_version}

    @app.get('/api/districts')
    def districts():
        g = geography()
        return {'type': 'FeatureCollection', 'features': g.districts, 'dataset_version': g.dataset_version}

    @app.get('/api/state/default')
    def default_state():
        return SearchState(dataset_version=geography().dataset_version, accessibility={'enabled': True})

    @app.get('/api/schema')
    def schema():
        return SearchState.model_json_schema()

    @app.post('/api/state/patch')
    def patch_state(body: PatchInput, request: Request):
        try:
            updated = apply_patch(body.state, body.operations)
            validate_geography(updated, geography())
            record_change(db, request.state.session_id, body.state, updated, body.operations)
            return updated
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/api/parse')
    async def parse(body: ParseInput):
        try:
            return await provider.parse(body.text) if os.getenv('INTENT_LLM_ENABLED', 'false').lower() == 'true' else limited_parse(body.text)
        except ProviderError as exc:
            raise HTTPException(503, {'provider_status': exc.status, 'state_changed': False}) from exc

    @app.post('/api/searches', status_code=201)
    def search(body: SearchInput, request: Request):
        try:
            rid = phase2.submit(body, request.state.session_id)
            return phase2.result(rid, request.state.session_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/api/searches/{request_id}')
    def get_search(request_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), sort: str | None = None):
        assert_owned(db, request_id, request.state.session_id)
        try:
            return phase2.result(request_id, request.state.session_id, offset, limit, sort=sort)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, 'Unknown request') from exc

    @app.get('/api/searches/{request_id}/snapshot')
    def snapshot(request_id: str, request: Request):
        assert_owned(db, request_id, request.state.session_id)
        try:
            return read_search(db, request_id, limit=200, include_snapshot=True)
        except KeyError as exc:
            raise HTTPException(404, 'Unknown request') from exc

    @app.post('/api/searches/{request_id}/replay')
    def replay(request_id: str, request: Request):
        assert_owned(db, request_id, request.state.session_id)
        # Replay reads saved inputs and evaluations; it performs no network request.
        try:
            return {'replay_source': 'stored_snapshot', **read_search(db, request_id, limit=200, include_snapshot=True)}
        except KeyError as exc:
            raise HTTPException(404, 'Unknown request') from exc

    @app.post('/api/searches/{request_id}/cancel')
    def cancel(request_id: str, request: Request):
        assert_owned(db, request_id, request.state.session_id)
        phase2.cancel_retrieval(request_id)
        with db.session.begin() as session:
            req = session.get(SearchRequest, request_id)
            if req is None:
                raise HTTPException(404, 'Unknown request')
            if req.completion_status in ('queued', 'running', 'partial'):
                req.cancel_requested, req.completion_status = True, 'cancelled'
        return read_search(db, request_id)

    @app.post('/api/searches/{request_id}/continue')
    def continue_search(request_id: str, request: Request):
        assert_owned(db, request_id, request.state.session_id)
        with db.session.begin() as session:
            req = session.get(SearchRequest, request_id)
            if req is None:
                raise HTTPException(404, 'Unknown request')
            if not adapter.configured:
                raise HTTPException(409, 'Routing is not configured')
            if req.completion_status in ('partial', 'cancelled'):
                if req.lease_owner is not None:
                    raise HTTPException(409, 'Cancellation is still draining; retry after the worker releases its lease')
                req.cancel_requested, req.completion_status, req.lease_until = False, 'queued', 0
        return read_search(db, request_id)

    offline_worker = install_phase3(app, db, provider)

    frontend = Path('frontend/dist')
    if frontend.exists():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
    return app
