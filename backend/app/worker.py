"""Durable bounded routing worker. All candidate inputs are immutable snapshots."""
from __future__ import annotations

import asyncio
import time
from copy import deepcopy

from sqlalchemy import func, select, text

from .db import Candidate, Evaluation, RouteCache, SearchRequest, new_id, utcnow
from .routing import cache_key, evaluate_itineraries
from .catalog import SearchAnalysis


class RoutingWorker:
    def __init__(self, db, adapter, settings):
        self.db, self.adapter, self.settings = db, adapter, settings
        self.owner = new_id('worker')
        self.stopped = asyncio.Event()
        self.active = set()

    @property
    def lease_seconds(self):
        return max(120, self.adapter.settings.timeout_seconds * (self.adapter.settings.max_retries + 1) + 60)

    def claim(self):
        now = time.time()
        with self.db.session() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            active_lease = session.scalar(select(SearchRequest.request_id).where(SearchRequest.lease_owner.is_not(None), SearchRequest.lease_until > now).limit(1))
            if active_lease is not None:
                session.rollback()
                return None
            req = session.scalar(select(SearchRequest).where(
                SearchRequest.completion_status.in_(['queued', 'running']),
                SearchRequest.request_id.not_in(select(SearchAnalysis.request_id).where(SearchAnalysis.status == 'pending')),
                SearchRequest.cancel_requested.is_(False), SearchRequest.lease_until < now
            ).order_by(SearchRequest.created_at).limit(1))
            if req is None:
                session.rollback()
                return None
            analysis = session.get(SearchAnalysis, req.request_id)
            if analysis and analysis.status == 'pending':
                session.rollback()
                return None
            req.lease_owner, req.lease_until, req.completion_status = self.owner, now + self.lease_seconds, 'running'
            session.commit()
            return req.request_id

    def cancelled(self, request_id):
        with self.db.session() as session:
            req = session.get(SearchRequest, request_id)
            return req is None or req.cancel_requested or req.lease_owner != self.owner

    async def evaluate(self, request_id, candidate, travel, preference):
        item = candidate.property_snapshot
        if item.get('latitude') is None or item.get('longitude') is None:
            return candidate.property_id, '', {'status': 'invalid_response', 'reason': 'origin_location_unknown', 'itineraries': [], 'selected_itinerary': None, 'verdicts': []}
        origin = {key: item[key] for key in ('latitude', 'longitude')}
        key = cache_key(origin, travel, self.adapter.settings)
        with self.db.session() as session:
            cached = session.get(RouteCache, key)
            payload = deepcopy(cached.payload) if cached and cached.expires_at > time.time() else None
        if payload is not None:
            payload['cache_hit'] = True
            for itinerary in payload.get('itineraries', []):
                if itinerary.get('source_kind') == 'live_otp':
                    itinerary['source_kind'] = 'recorded_otp'
        if payload is None:
            started = time.perf_counter()
            payload = await self.adapter.route(origin, travel)
            payload['routing_latency_ms'] = (time.perf_counter() - started) * 1000
            if payload.get('status') in ('ok', 'no_route_returned') and not self.cancelled(request_id):
                with self.db.session.begin() as session:
                    row = session.get(RouteCache, key)
                    if row is None:
                        session.add(RouteCache(cache_key=key, payload=payload, expires_at=time.time() + self.settings.cache_ttl))
                    else:
                        row.payload, row.expires_at = payload, time.time() + self.settings.cache_ttl
        result = dict(payload)
        result.setdefault('cache_hit', False)
        if payload.get('status') == 'ok':
            effective_travel = {**travel, 'modes': travel.get('modes') or self.adapter.settings.supported_modes}
            result.update(evaluate_itineraries(payload.get('itineraries', []), effective_travel, preference))
        result.setdefault('selected_itinerary', None)
        result.setdefault('verdicts', [])
        result['origin_location_accuracy'] = item.get('location_accuracy', 'unknown')
        if result['selected_itinerary']:
            result['selected_itinerary'] = dict(result['selected_itinerary'], location_accuracy=item.get('location_accuracy', 'unknown'))
        return candidate.property_id, key, result

    async def process(self, request_id):
        with self.db.session() as session:
            req = session.get(SearchRequest, request_id)
            state = req.state
            travel, preference, batch_limit = req.state['travel'], req.state['preference'], req.batch_limit
            preference = {'walk_time_asc': 'less_walking', 'travel_time_asc': 'faster_commute', 'transfers_asc': 'fewer_transfers'}.get(req.state['sort'], preference)
            done = set(session.scalars(select(Evaluation.property_id).where(Evaluation.request_id == request_id)))
            candidates = [c for c in session.scalars(select(Candidate).where(Candidate.request_id == request_id).order_by(Candidate.ordinal)) if c.property_id not in done]
            analysis = session.get(SearchAnalysis, request_id)
            if analysis and analysis.priority_ids:
                priorities = {pid: index for index, pid in enumerate(analysis.priority_ids)}
                candidates.sort(key=lambda c: (priorities.get(c.property_id, len(priorities)), c.ordinal))
            candidates = candidates[:batch_limit]
        from .accessibility import enabled, evaluate_accessibility
        automatic = enabled(state)
        width = min(10, max(1, self.adapter.settings.max_concurrency))
        for index in range(0, len(candidates), width):
            if self.cancelled(request_id) or self.stopped.is_set():
                break
            self.active = {asyncio.create_task(evaluate_accessibility(self, request_id, c, state, preference) if automatic else self.evaluate(request_id, c, travel, preference)) for c in candidates[index:index + width]}
            while self.active:
                completed, remaining = await asyncio.wait(self.active, timeout=0.15, return_when=asyncio.FIRST_COMPLETED)
                self.active = remaining
                if self.cancelled(request_id) or self.stopped.is_set():
                    for task in self.active:
                        task.cancel()
                    await asyncio.gather(*self.active, return_exceptions=True)
                    self.active = set()
                    # Completed work remains in the cache but cannot mutate a cancelled snapshot.
                    for task in completed:
                        if not task.cancelled():
                            task.exception()
                    break
                for task in completed:
                    property_id, key, result = task.result()
                    with self.db.session.begin() as session:
                        req = session.get(SearchRequest, request_id)
                        if req.cancel_requested or req.lease_owner != self.owner:
                            continue
                        if session.get(Evaluation, (request_id, property_id)) is None:
                            session.add(Evaluation(request_id=request_id, property_id=property_id, cache_key=key, result=result, created_at=utcnow()))
                            req.evaluated_count += 1
                        req.lease_until = time.time() + self.lease_seconds
        with self.db.session.begin() as session:
            req = session.get(SearchRequest, request_id)
            if req.lease_owner == self.owner:
                req.lease_owner, req.lease_until = None, 0
                req.completion_status = 'cancelled' if req.cancel_requested else 'queued' if self.stopped.is_set() else 'complete' if req.evaluated_count >= req.candidate_count else 'partial'

    async def run_once(self):
        request_id = self.claim()
        if request_id is None:
            return False
        try:
            await self.process(request_id)
        except asyncio.CancelledError:
            with self.db.session.begin() as session:
                req = session.get(SearchRequest, request_id)
                if req and req.lease_owner == self.owner:
                    req.lease_owner, req.lease_until = None, 0
                    req.completion_status = 'cancelled' if req.cancel_requested else 'queued'
            raise
        except Exception as exc:
            for task in self.active:
                task.cancel()
            await asyncio.gather(*self.active, return_exceptions=True)
            self.active = set()
            with self.db.session.begin() as session:
                req = session.get(SearchRequest, request_id)
                req.lease_owner, req.lease_until = None, 0
                req.completion_status = 'partial'
                req.warnings = req.warnings + [f'Worker interrupted: {type(exc).__name__}; stored evaluations are preserved.']
        return True

    async def run(self):
        while not self.stopped.is_set():
            if not await self.run_once():
                try:
                    await asyncio.wait_for(self.stopped.wait(), timeout=0.5)
                except TimeoutError:
                    pass

    async def stop(self):
        self.stopped.set()
        for task in self.active:
            task.cancel()
        await asyncio.gather(*self.active, return_exceptions=True)
