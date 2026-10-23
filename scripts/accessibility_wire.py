"""Wire versioned accessibility through the existing application and durable worker."""
from pathlib import Path


def replace(path, old, new):
    target = Path(path)
    source = target.read_text(encoding='utf-8-sig')
    if new and new in source:
        return
    if old not in source:
        raise RuntimeError(f'Expected source not found: {path}: {old[:90]}')
    target.write_text(source.replace(old, new, 1), encoding='utf-8')


p = 'backend/app/contracts.py'
replace(p, "        if self.destination and (self.date is None or self.time is None):\n            raise ValueError('A destination requires an explicit date and local time')\n", '')
replace(p, 'class SearchState(Contract):', """class Accessibility(Contract):
    semantics_version: Literal['accessibility-1'] = 'accessibility-1'
    enabled: bool = True
    time_policy: Literal['request_execution'] = 'request_execution'
    effective_at: str | None = None


class SearchState(Contract):""")
replace(p, '    travel: Travel = Field(default_factory=Travel)', '    travel: Travel = Field(default_factory=Travel)\n    accessibility: Accessibility | None = None')
replace(p, "'walk_time_asc', 'transfers_asc'] = 'recommended'", "'walk_time_asc', 'transfers_asc', 'stop_walk_time_asc', 'stop_distance_asc'] = 'recommended'")
replace(p, '\n\nclass SourceRecord(Contract):', """

    @model_validator(mode='after')
    def accessibility_coherence(self):
        automatic = bool(self.accessibility and self.accessibility.enabled)
        if not automatic and self.travel.destination and (self.travel.date is None or self.travel.time is None):
            raise ValueError('A destination requires an explicit date and local time')
        if self.sort in ('stop_walk_time_asc', 'stop_distance_asc') and (not automatic or self.travel.destination):
            raise ValueError('Stop sorting requires automatic accessibility without a destination')
        if automatic and self.sort == 'transfers_asc':
            raise ValueError('Transfers sort belongs to legacy journey semantics')
        return self


class SourceRecord(Contract):""")
p = 'backend/app/db.py'
replace(p, '    property_verdicts: Mapped[list] = mapped_column(JSON)', '    property_verdicts: Mapped[list] = mapped_column(JSON)\n    accessibility_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)')
replace(p, '        evaluation_store.migrate_evaluation(self)', '        evaluation_store.migrate_evaluation(self)\n        from .accessibility import migrate_accessibility\n        migrate_accessibility(self)')
p = 'backend/app/search.py'
replace(p, 'routing_available: bool, versions=None, catalog=None):', 'routing_available: bool, versions=None, catalog=None, stops=None):')
replace(p, '    state = request.state.model_copy(deep=True)', """    from .accessibility import enabled, prepare_state, initial_accessibility, VERSION
    state = prepare_state(request.state.model_copy(deep=True))
    automatic = enabled(state)
    if automatic and stops is None:
        from .transit_stops import StopCatalog
        stops = StopCatalog()
    if automatic:
        versions = {**(versions or {}), 'accessibility': VERSION, 'accessibility_ranker': 'accessibility-ranker-1',
                    'stop_dataset': stops.version, 'time_policy': 'request_execution'}""")
replace(p, "        routing = destination is not None\n        status =", "        routing = destination is not None\n        status = 'queued' if automatic and candidates else")
replace(p, "property_snapshot=item, property_verdicts=verdicts))", "property_snapshot=item, property_verdicts=verdicts,\n                                  accessibility_snapshot=initial_accessibility(item, state, stops) if automatic else {}))")
replace(p, 'def read_search(db, request_id, offset=0, limit=100, include_snapshot=False):', 'def read_search(db, request_id, offset=0, limit=100, include_snapshot=False, sort=None):')
replace(p, '        state = SearchState.model_validate(req.state)', """        state = SearchState.model_validate(req.state)
        from .accessibility import enabled, select_result
        automatic = enabled(state)
        if sort is not None:
            state = SearchState.model_validate({**req.state, 'sort': sort})
            if sort in ('travel_time_asc', 'walk_time_asc') and not state.travel.destination:
                raise ValueError('Destination sort requires a destination')""")
replace(p, '            result = evaluations.get(candidate.property_id)', """            result = evaluations.get(candidate.property_id)
            if automatic and result:
                preference = 'less_walking' if state.sort in ('walk_time_asc', 'stop_walk_time_asc') else 'faster_commute'
                result = select_result(result, preference)""")
replace(p, "            if routing and (not result or result.get('status') != 'ok'):", """            if automatic:
                row['accessibility'] = result['accessibility'] if result else candidate.accessibility_snapshot
                row['qualification'] = 'verified_accessibility' if result and result.get('status') == 'ok' else 'property_only'
                if not result or result.get('status') != 'ok':
                    unverified.append(row)
                rows.append(row)
                continue
            if routing and (not result or result.get('status') != 'ok'):""")
replace(p, "'snapshot_id': req.snapshot_id, 'state': req.state, 'versions': req.versions,", "'snapshot_id': req.snapshot_id, 'state': state.model_dump(mode='json'), 'versions': req.versions,")
replace(p, '        if include_snapshot:', """        if automatic:
            output['accessibility'] = {**state.accessibility.model_dump(mode='json'),
                'mode': 'destination' if routing else 'nearby_stop', 'stop_dataset_version': req.versions.get('stop_dataset'),
                'stops_status': candidates[0].accessibility_snapshot.get('stops_status') if candidates else 'not_required'}
            output['ranking_scope'] = 'all_candidates' if req.completion_status == 'complete' else 'evaluated_subset'
            output['coverage']['routing'] = req.evaluated_count / req.candidate_count if req.candidate_count else None
            output['view_sort'] = state.sort
        if include_snapshot:""")
replace(p, "'property_verdicts': c.property_verdicts, 'ordinal': c.ordinal}", "'property_verdicts': c.property_verdicts, 'ordinal': c.ordinal, 'accessibility': c.accessibility_snapshot}")
p = 'backend/app/worker.py'
replace(p, '            travel, preference, batch_limit =', '            state = req.state\n            travel, preference, batch_limit =')
replace(p, '        width = min(10, max(1, self.adapter.settings.max_concurrency))', """        from .accessibility import enabled, evaluate_accessibility
        automatic = enabled(state)
        width = min(10, max(1, self.adapter.settings.max_concurrency))""")
replace(p, 'asyncio.create_task(self.evaluate(request_id, c, travel, preference))', 'asyncio.create_task(evaluate_accessibility(self, request_id, c, state, preference) if automatic else self.evaluate(request_id, c, travel, preference))')
p = 'backend/app/ranking.py'
replace(p, 'def policy(state, config=None):\n', """def policy(state, config=None):
    if getattr(state, 'accessibility', None) and state.accessibility.enabled:
        from .accessibility_ranking import policy as accessibility_policy
        return accessibility_policy(state, config)
""")
replace(p, 'def rank_rows(rows, state, semantic_ids=None, config=None):\n', """def rank_rows(rows, state, semantic_ids=None, config=None):
    if getattr(state, 'accessibility', None) and state.accessibility.enabled:
        from .accessibility_ranking import rank_rows as accessibility_rank_rows
        return accessibility_rank_rows(rows, state, semantic_ids, config)
""")
p = 'backend/app/integration.py'
replace(p, 'def result(self, request_id, owner, offset=0, limit=100):', 'def result(self, request_id, owner, offset=0, limit=100, sort=None):')
replace(p, '        return snapshot\n\n    def submit', '        return read_search(self.db, request_id, offset, limit, sort=sort) if sort is not None else snapshot\n\n    def submit')
p = 'backend/app/main.py'
replace(p, 'return SearchState(dataset_version=geography().dataset_version)', "return SearchState(dataset_version=geography().dataset_version, accessibility={'enabled': True})")
replace(p, 'limit: int = Query(100, ge=1, le=200)):', 'limit: int = Query(100, ge=1, le=200), sort: str | None = None):')
replace(p, 'return phase2.result(request_id, request.state.session_id, offset, limit)', 'return phase2.result(request_id, request.state.session_id, offset, limit, sort=sort)\n        except ValueError as exc:\n            raise HTTPException(422, str(exc)) from exc')
print('Wired additive accessibility state, migration, worker, ranking and read-only sort views.')
