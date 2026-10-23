"""Structured candidate filtering, immutable snapshots, and transparent ranking."""
from __future__ import annotations

from copy import deepcopy
from sqlalchemy import func, select

from .contracts import SearchInput, SearchState, PARSER_VERSION, RANKER_VERSION, SCHEMA_VERSION
from .db import Candidate, Evaluation, Listing, SearchRequest, Task, new_id, utcnow
from .ranking import rank_rows, policy
from .event_evidence import qualifying_alternatives, request_actor
from .catalog import ListingAssignment, LocationMember, SearchAnalysis, keyword_match


def feature_id(feature):
    p = feature.get('properties', {})
    return str(feature.get('id') or p.get('id') or p.get('neighborhood_id') or p.get('district_id'))


def property_verdicts(item, state, geo, assignment=None):
    evidence = []
    for field, feature, direction in [
        ('max_deposit_toman', 'deposit_toman', 'max'),
        ('max_monthly_rent_toman', 'monthly_rent_toman', 'max'),
        ('min_area_m2', 'area_m2', 'min'), ('min_bedrooms', 'bedrooms', 'min')]:
        expected, actual = getattr(state.property, field), item.get(feature)
        if expected is not None:
            verdict = 'unknown' if actual is None else 'pass' if (actual <= expected if direction == 'max' else actual >= expected) else 'fail'
            evidence.append({'condition': field, 'verdict': verdict, 'actual': actual, 'expected': expected})
    for field, feature in [('parking_required', 'parking'), ('elevator_required', 'elevator')]:
        if getattr(state.property, field) is True:
            actual = item.get(feature)
            evidence.append({'condition': field, 'verdict': 'unknown' if actual is None else 'pass' if actual is True else 'fail', 'actual': actual, 'expected': True})
    lon, lat = item.get('longitude'), item.get('latitude')
    for field, lookup in [('selected_neighborhood_ids', geo.neighborhood_memberships), ('selected_district_ids', geo.district_memberships)]:
        expected = getattr(state, field)
        if expected:
            if assignment is not None and lon is not None and lat is not None:
                actual = assignment.neighborhood_ids if field == 'selected_neighborhood_ids' else assignment.district_ids
            else:
                actual = lookup(lon, lat) if lon is not None and lat is not None else None
            evidence.append({'condition': field, 'verdict': 'unknown' if actual is None else 'pass' if set(actual) & set(expected) else 'fail', 'actual': actual, 'expected_any': expected,
                             'membership_status': 'unknown' if actual is None else 'ambiguous' if len(actual) > 1 else 'unique' if actual else 'outside'})
    return evidence


def validate_geography(state, geo):
    for selected, features in [(state.selected_neighborhood_ids, geo.neighborhoods), (state.selected_district_ids, geo.districts)]:
        unknown = set(selected) - {feature_id(feature) for feature in features}
        if unknown:
            raise ValueError('Unknown geographic IDs: ' + ', '.join(sorted(unknown)))
    warnings = []
    if state.selected_neighborhood_ids and state.selected_district_ids:
        from shapely.geometry import shape
        neighborhoods = [shape(f['geometry']) for f in geo.neighborhoods if feature_id(f) in state.selected_neighborhood_ids]
        districts = [shape(f['geometry']) for f in geo.districts if feature_id(f) in state.selected_district_ids]
        if not any(n.intersection(d).area > 0 for n in neighborhoods for d in districts):
            warnings.append('محله‌ها و مناطق انتخاب‌شده اشتراک سطحی ندارند؛ هیچ فیلتری حذف نشده است.')
    return warnings


def create_search(db, geo, request: SearchInput, settings, routing_available: bool, versions=None, catalog=None, stops=None):
    from .accessibility import enabled, prepare_state, initial_accessibility, VERSION
    state = prepare_state(request.state.model_copy(deep=True))
    automatic = enabled(state)
    if automatic and stops is None:
        from .transit_stops import StopCatalog
        stops = StopCatalog()
    if automatic:
        versions = {**(versions or {}), 'accessibility': VERSION, 'accessibility_ranker': 'accessibility-ranker-1',
                    'stop_dataset': stops.version, 'time_policy': 'request_execution'}
    warnings = validate_geography(state, geo)
    if state.sort in ('travel_time_asc', 'walk_time_asc', 'transfers_asc') and not state.travel.destination:
        raise ValueError('Travel sorting requires a confirmed destination, date and time')
    if catalog:
        catalog.refresh()
    with db.session.begin() as session:
        parent = session.get(SearchRequest, request.parent_request_id) if request.parent_request_id else None
        if request.parent_request_id and parent is None:
            raise ValueError('Unknown parent_request_id')
        if request.task_id and session.get(Task, request.task_id) is None:
            raise ValueError('Unknown task_id')
        if parent and request.task_id and parent.task_id != request.task_id:
            raise ValueError('Parent belongs to another task')
        task = session.get(Task, request.task_id or parent.task_id) if request.task_id or parent else None
        destination = state.travel.destination.model_dump(mode='json') if state.travel.destination else None
        # A changed confirmed destination represents a new independent need.
        if task is None or request.new_need or task.destination != destination:
            task = Task(task_id=new_id('task'), destination=destination, created_at=utcnow())
            session.add(task)
        state.state_revision = parent.state['state_revision'] + 1 if parent else 0
        count = session.scalar(select(func.count()).select_from(Listing).where(Listing.dataset_version == state.dataset_version))
        if count == 0:
            raise ValueError('Dataset has no stored listings; run the seed command first')
        query = select(Listing).where(Listing.dataset_version == state.dataset_version)
        # SQLAlchemy binds every user value; dynamic SQL is never interpolated.
        for field, column, operator in [('max_deposit_toman', Listing.deposit_toman, 'max'), ('max_monthly_rent_toman', Listing.monthly_rent_toman, 'max'), ('min_area_m2', Listing.area_m2, 'min'), ('min_bedrooms', Listing.bedrooms, 'min')]:
            value = getattr(state.property, field)
            if value is not None:
                query = query.where(column <= value if operator == 'max' else column >= value)
        if state.property.parking_required:
            query = query.where(Listing.parking.is_(True))
        if state.property.elevator_required:
            query = query.where(Listing.elevator.is_(True))
        assignments = {}
        if catalog:
            for kind, ids in [('neighborhood', state.selected_neighborhood_ids), ('district', state.selected_district_ids)]:
                if ids:
                    query = query.where(Listing.property_id.in_(select(LocationMember.property_id).where(
                        LocationMember.kind == kind, LocationMember.area_id.in_(ids))))
            assignments = {a.property_id: a for a in session.scalars(select(ListingAssignment))}
            if state.query.strip():
                query = query.where(Listing.property_id.in_(catalog.lexical(state.query, limit=100_000)))
        candidates = []
        for row in session.scalars(query):
            if state.query.strip() and catalog is None and not keyword_match(state.query, row.payload.get('title_fa', '')):
                continue
            verdicts = property_verdicts(row.payload, state, geo, assignments.get(row.property_id))
            if all(e['verdict'] == 'pass' for e in verdicts):
                candidates.append((deepcopy(row.payload), verdicts))
        sort_field = 'deposit_toman' if state.sort == 'deposit_asc' else 'monthly_rent_toman'
        candidates.sort(key=lambda pair: (pair[0].get(sort_field) is None, pair[0].get(sort_field) or 0, pair[0]['property_id']))
        routing = destination is not None
        status = 'queued' if automatic and candidates else 'queued' if routing and routing_available and candidates else 'routing_unavailable' if routing and candidates else 'complete'
        if status == 'routing_unavailable':
            warnings.append('مسیریابی پیکربندی یا تأیید نشده است؛ نتایج زیر فقط شروط ملک را گذرانده‌اند.')
        if not candidates:
            warnings.append('هیچ آگهی ذخیره‌شده‌ای با همهٔ شروط ملک و مکان منطبق نیست؛ انتخاب‌ها حفظ شده‌اند.')
        rid = new_id('req')
        record = SearchRequest(request_id=rid, task_id=task.task_id, parent_request_id=parent.request_id if parent else None,
            snapshot_id=new_id('snap'), state=state.model_dump(mode='json'),
            versions={'schema': SCHEMA_VERSION, 'dataset': state.dataset_version, 'parser': PARSER_VERSION, 'ranker': RANKER_VERSION, **(versions or {})},
            candidate_count=len(candidates), evaluated_count=0, completion_status=status,
            subset_method=f'{sort_field} ascending; null last; property_id tie-break; first batch_limit',
            batch_limit=settings.batch_limit, warnings=warnings, created_at=utcnow())
        session.add(record)
        for index, (item, verdicts) in enumerate(candidates):
            session.add(Candidate(request_id=rid, property_id=item['property_id'], ordinal=index,
                                  property_snapshot=item, property_verdicts=verdicts,
                                  accessibility_snapshot=initial_accessibility(item, state, stops) if automatic else {}))
    return rid


def read_search(db, request_id, offset=0, limit=100, include_snapshot=False, sort=None):
    with db.session() as session:
        req = session.get(SearchRequest, request_id)
        if req is None:
            raise KeyError(request_id)
        state = SearchState.model_validate(req.state)
        from .accessibility import enabled, select_result
        automatic = enabled(state)
        if sort is not None:
            state = SearchState.model_validate({**req.state, 'sort': sort})
            if sort in ('travel_time_asc', 'walk_time_asc') and not state.travel.destination:
                raise ValueError('Destination sort requires a destination')
        evaluations = {e.property_id: e.result for e in session.scalars(select(Evaluation).where(Evaluation.request_id == request_id))}
        rows, excluded, unverified = [], [], []
        candidates = list(session.scalars(select(Candidate).where(Candidate.request_id == request_id).order_by(Candidate.ordinal)))
        routing = state.travel.destination is not None
        for candidate in candidates:
            result = evaluations.get(candidate.property_id)
            if automatic and result:
                preference = 'less_walking' if state.sort in ('walk_time_asc', 'stop_walk_time_asc') else 'faster_commute'
                result = select_result(result, preference)
            row = {'property': candidate.property_snapshot, 'property_verdicts': candidate.property_verdicts,
                   'route_status': result.get('status') if result else 'not_evaluated',
                   'selected_itinerary': result.get('selected_itinerary') if result else None,
                   'travel_verdicts': result.get('verdicts', []) if result else [],
                   'qualifying_itineraries': qualifying_alternatives(result),
                   'qualification': 'verified_travel' if routing and result and result.get('status') == 'ok' else 'unverified_travel' if routing else 'property_only'}
            if automatic:
                row['accessibility'] = result['accessibility'] if result else candidate.accessibility_snapshot
                row['qualification'] = 'verified_accessibility' if result and result.get('status') == 'ok' else 'property_only'
                if not result or result.get('status') != 'ok':
                    unverified.append(row)
                rows.append(row)
                continue
            if routing and (not result or result.get('status') != 'ok'):
                unverified.append(row)
                if result:
                    excluded.append({'property_id': candidate.property_id, **result})
                continue
            rows.append(row)
        analysis = session.get(SearchAnalysis, request_id)
        from .release_control import active_production_config
        release_config = active_production_config(db)
        rows = rank_rows(rows, state, analysis.priority_ids if analysis else [], config=release_config)
        output = {'actor_kind': request_actor(session, request_id), 'task_id': req.task_id, 'request_id': req.request_id, 'parent_request_id': req.parent_request_id,
                  'snapshot_id': req.snapshot_id, 'state': state.model_dump(mode='json'), 'versions': req.versions,
                  'candidate_count': req.candidate_count, 'evaluated_count': req.evaluated_count,
                  'completion_status': req.completion_status,
                  'subset_method': 'reciprocal rank fusion of vector/lexical/all structured IDs; bounded batch; no candidate discarded' if analysis and analysis.priority_ids else req.subset_method,
                  'ranking_scope': 'property_only' if not routing or req.completion_status == 'routing_unavailable' else 'all_candidates' if req.completion_status == 'complete' else 'evaluated_subset',
                  'warnings': req.warnings, 'results': rows[offset:offset + limit], 'result_count': len(rows),
                  'eligible_count': len(rows), 'unverified_count': len(unverified),
                  'retrieved_count': analysis.metadata_json.get('retrieved_count', 0) if analysis else 0,
                  'coverage': {'structured': 1.0, 'routing': req.evaluated_count / req.candidate_count if routing and req.candidate_count else None},
                  'unverified_results': unverified[offset:offset + limit], 'ranking_policy': policy(state, release_config),
                  'search_mode': analysis.search_mode if analysis else 'normal',
                  'semantic': {'status': analysis.status, **analysis.metadata_json} if analysis else {'status': 'not_requested'},
                  'cache_hits': sum(bool(e.get('cache_hit')) for e in evaluations.values()),
                  'cache_misses': sum(not bool(e.get('cache_hit')) for e in evaluations.values()),
                  'offset': offset, 'limit': limit, 'excluded_evaluations': excluded,
                  'created_at': req.created_at}
        if automatic:
            output['accessibility'] = {**state.accessibility.model_dump(mode='json'),
                'mode': 'destination' if routing else 'nearby_stop', 'stop_dataset_version': req.versions.get('stop_dataset'),
                'stops_status': candidates[0].accessibility_snapshot.get('stops_status') if candidates else 'not_required'}
            output['ranking_scope'] = 'all_candidates' if req.completion_status == 'complete' else 'evaluated_subset'
            output['coverage']['routing'] = req.evaluated_count / req.candidate_count if req.candidate_count else None
            output['view_sort'] = state.sort
        if include_snapshot:
            output['candidates'] = [{'property': c.property_snapshot, 'property_verdicts': c.property_verdicts, 'ordinal': c.ordinal, 'accessibility': c.accessibility_snapshot} for c in candidates]
            output['evaluations'] = evaluations
        return output
