"""Phase-two APIs preserve the phase-one state and durable routing contracts."""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import threading

from fastapi import HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import select

from .catalog import Catalog, SearchAnalysis
from .contracts import SearchInput
from .db import Candidate
from .feedback import register_feedback_routes, touch_measurement, record_system_event
from .intent import IntentInput, interpret
from .llm import ProviderError
from .routing import ADAPTER_VERSION
from .search import create_search, read_search
from .semantic import SemanticService, reciprocal_rank_fusion
from .session import install_sessions, assert_owned, assert_task_owned, claim_request


class AdvancedInput(SearchInput):
    semantic_text: str = Field(min_length=1, max_length=2000)
    confirmed: bool


class PhaseTwo:
    def __init__(self, app, db, geography, settings, adapter, provider):
        self.db, self.geography, self.settings = db, geography, settings
        self.adapter, self.provider = adapter, provider
        self._catalog = None
        self.catalog_lock = threading.Lock()
        self.semantic = None
        self.background = set()
        self.jobs = {}
        self.maintenance_task = None
        self.maintenance_status = 'not_started'
        self.semaphore = asyncio.Semaphore(2)
        install_sessions(app, db)
        app.add_middleware(GZipMiddleware, minimum_size=1000)
        register_feedback_routes(app, db, provider)
        with db.session.begin() as session:
            for row in session.scalars(select(SearchAnalysis).where(SearchAnalysis.status == 'pending')):
                row.status = 'degraded'
                row.metadata_json = {'reason': 'process_restarted', 'candidate_policy': 'all_structured_eligible_retained'}
        self.mount(app)

    def catalog(self):
        with self.catalog_lock:
            if self._catalog is None:
                self._catalog = Catalog(self.db, self.geography())
            return self._catalog

    def info(self):
        return {'ai_enabled': os.getenv('ADVANCED_AI_ENABLED', 'false').lower() == 'true' and self.provider.info()['enabled'],
                'semantic_configured': os.getenv('QDRANT_ENABLED', 'true').lower() == 'true',
                'status': 'checked_on_advanced_request', 'measurement_sweep': self.maintenance_status}

    def result(self, request_id, owner, offset=0, limit=100, sort=None):
        snapshot = read_search(self.db, request_id, offset, limit)
        touch_measurement(self.db, request_id, owner)
        if snapshot['completion_status'] == 'complete' and snapshot['semantic']['status'] != 'pending':
            record_system_event(self.db, owner, request_id, 'search_completed')
            from .evaluation_replay import capture_delivery
            capture_delivery(self.db, snapshot)
        return read_search(self.db, request_id, offset, limit, sort=sort) if sort is not None else snapshot

    def submit(self, body, owner, mode='normal'):
        if body.parent_request_id:
            assert_owned(self.db, body.parent_request_id, owner)
        if body.task_id:
            assert_task_owned(self.db, body.task_id, owner)
        if body.state.dataset_version != self.geography().dataset_version:
            raise HTTPException(422, 'State dataset_version must match the loaded boundary dataset')
        modes = set(self.adapter.settings.supported_modes or [])
        if body.state.travel.modes and not set(body.state.travel.modes) <= modes:
            raise HTTPException(422, 'Requested modes are not verified against the installed OTP API')
        started = time.perf_counter()
        rid = create_search(self.db, self.geography(), body, self.settings, self.adapter.configured,
            {'inventory': self.catalog().version, 'boundary_assignments': self.catalog().boundary_version, 'adapter': ADAPTER_VERSION, 'graph': getattr(self.adapter.settings, 'graph_version', None),
             'llm_provider': self.provider.info()['provider_version'], 'llm_role_models': self.provider.models,
             'llm_role_versions': self.provider.role_versions}, catalog=self.catalog())
        claim_request(self.db, rid, owner)
        with self.db.session.begin() as session:
            session.add(SearchAnalysis(request_id=rid, search_mode=mode,
                status='pending' if mode == 'advanced' else 'not_requested',
                metadata_json={'candidate_policy': 'all_structured_eligible_union', 'retrieved_count': 0}, priority_ids=[]))
        record_system_event(self.db, owner, rid, 'search_submitted', payload={'mode': mode, 'duration_ms': (time.perf_counter() - started) * 1000})
        if mode == 'advanced':
            record_system_event(self.db, owner, rid, 'advanced_search_submitted')
        return rid

    async def retrieve(self, request_id, text_value, owner):
        started = time.perf_counter()
        try:
            async with self.semaphore:
                with self.db.session() as session:
                    eligible = list(session.scalars(select(Candidate.property_id).where(Candidate.request_id == request_id).order_by(Candidate.ordinal)))
                if self.semantic is None:
                    self.semantic = SemanticService(self.db, self.geography())
                semantic = await self.semantic.retrieve(text_value, eligible)
                lexical = await asyncio.to_thread(self.catalog().lexical, text_value, 500, True)
                allowed = set(eligible)
                lexical = [pid for pid in lexical if pid in allowed]
                vector = [pid for pid in semantic.get('property_ids', []) if pid in allowed]
                priority, fusion = reciprocal_rank_fusion(vector, lexical, eligible)
                metadata = {key: value for key, value in semantic.items() if key not in ('property_ids', 'scores', 'status')}
                metadata.update(lexical_count=len(lexical), structured_count=len(eligible),
                    semantic_query_hash=hashlib.sha256(text_value.encode()).hexdigest(),
                    retrieval_signals={pid: {'vector_score': semantic.get('scores', {}).get(pid),
                        'vector_rank': vector.index(pid) + 1 if pid in vector else None,
                        'lexical_rank': lexical.index(pid) + 1 if pid in lexical else None,
                        'fusion_score': fusion[pid], 'is_property_fact': False}
                        for pid in set(vector) | set(lexical)},
                    candidate_policy='RRF k=60 priority; all structured eligible retained; utility ties only',
                    structured_coverage=1.0, retrieval_scope='approximate_vector_union_exhaustive_structured')
                with self.db.session.begin() as session:
                    row = session.get(SearchAnalysis, request_id)
                    row.status, row.metadata_json, row.priority_ids = semantic['status'], metadata, priority
                    row.latency_ms = (time.perf_counter() - started) * 1000
                record_system_event(self.db, owner, request_id, 'semantic_retrieval_completed' if semantic['status'] == 'ok' else 'semantic_retrieval_failed',
                    payload={'duration_ms': (time.perf_counter() - started) * 1000, 'status': semantic['status']})
        except asyncio.CancelledError:
            with self.db.session.begin() as session:
                row = session.get(SearchAnalysis, request_id)
                if row and row.status == 'pending':
                    row.status = 'cancelled'
                    row.metadata_json = {'reason': 'cancelled', 'candidate_policy': 'all_structured_eligible_retained'}
            raise
        except Exception as exc:
            with self.db.session.begin() as session:
                row = session.get(SearchAnalysis, request_id)
                row.status = 'degraded'
                row.metadata_json = {'reason': type(exc).__name__, 'candidate_policy': 'all_structured_eligible_retained'}
            record_system_event(self.db, owner, request_id, 'semantic_retrieval_failed', payload={'status': 'degraded'})

    def cancel_retrieval(self, request_id):
        pending = self.jobs.get(request_id)
        if pending:
            pending.get_loop().call_soon_threadsafe(pending.cancel)

    def start(self):
        self.maintenance_task = asyncio.create_task(self.maintain())

    async def maintain(self):
        from .measurement_worker import sweep_due_measurements
        while True:
            try:
                await asyncio.to_thread(sweep_due_measurements, self.db, 20)
                self.maintenance_status = 'ok'
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.maintenance_status = type(exc).__name__
            await asyncio.sleep(5)

    async def stop(self):
        pending = list(self.background)
        if self.maintenance_task:
            pending.append(self.maintenance_task)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def mount(self, app):
        @app.get('/api/inventory')
        def inventory(request: Request):
            current = self.catalog()
            current.refresh()
            tag = '"' + current.version + '"'
            headers = {'ETag': tag, 'Cache-Control': 'private, max-age=0, must-revalidate'}
            if request.headers.get('if-none-match') == tag:
                return Response(status_code=304, headers=headers)
            return JSONResponse(current.public, headers=headers)

        @app.post('/api/intent')
        async def intent(body: IntentInput):
            try:
                return await interpret(body, self.geography(), self.provider, self.adapter.settings.supported_modes)
            except ProviderError as exc:
                raise HTTPException(503, {'provider_status': exc.status, 'state_changed': False}) from exc

        @app.post('/api/advanced/searches', status_code=201)
        async def advanced_search(body: AdvancedInput, request: Request):
            if not body.confirmed:
                raise HTTPException(422, 'Confirm the extracted hard constraints before searching')
            if len(self.background) >= 8:
                raise HTTPException(429, 'Advanced retrieval queue is full; retry shortly')
            try:
                rid = await asyncio.to_thread(self.submit, body, request.state.session_id, 'advanced')
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            task = asyncio.create_task(self.retrieve(rid, body.semantic_text, request.state.session_id))
            self.background.add(task)
            self.jobs[rid] = task
            task.add_done_callback(self.background.discard)
            task.add_done_callback(lambda _: self.jobs.pop(rid, None))
            return self.result(rid, request.state.session_id)
