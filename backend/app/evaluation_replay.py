"""Content-addressed references to frozen evidence; historical replay has no I/O providers."""
from copy import deepcopy
import hashlib
import json
from sqlalchemy import select
from .db import Candidate, Evaluation, SearchRequest, utcnow
from .catalog import SearchAnalysis
from .explanations import ExplanationCache
from .evaluation_store import ReplayManifest
from .search import read_search


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def safe_state(state):
    result = deepcopy(state)
    result['query'] = ''
    if result.get('travel', {}).get('destination'):
        result['travel']['destination'] = {'reference': 'restricted_request_destination', 'confirmed': True}
    return result


def freeze_manifest(db, request_id, *, delivery_capture=False):
    snapshot = read_search(db, request_id, limit=100000)
    with db.session() as session:
        req = session.get(SearchRequest, request_id)
        candidates = list(session.scalars(select(Candidate).where(Candidate.request_id == request_id).order_by(Candidate.ordinal)))
        evaluations = list(session.scalars(select(Evaluation).where(Evaluation.request_id == request_id)))
        analysis = session.get(SearchAnalysis, request_id)
        explanations = list(session.scalars(select(ExplanationCache).where(ExplanationCache.request_id == request_id)))
        payload = {'manifest_version': 'reference-manifest-1', 'request_id': request_id,
            'task_id': req.task_id, 'snapshot_id': req.snapshot_id, 'parent_request_id': req.parent_request_id,
            'confirmed_state': safe_state(req.state), 'state_hash': digest(req.state), 'versions': req.versions,
            'mode': snapshot['search_mode'], 'actor_cohort': snapshot['actor_kind'],
            'completion_status': req.completion_status, 'ranking_scope': snapshot['ranking_scope'],
            'candidate_count': req.candidate_count, 'evaluated_count': req.evaluated_count,
            'candidate_refs': [{'property_id': c.property_id, 'hash': digest([c.property_snapshot, c.property_verdicts]), **({'accessibility_hash': digest(c.accessibility_snapshot)} if c.accessibility_snapshot else {})} for c in candidates],
            'route_refs': [{'property_id': e.property_id, 'hash': digest(e.result), 'cache_key': e.cache_key} for e in evaluations],
            'analysis_hash': digest(analysis.metadata_json) if analysis else None,
            'retrieval_priority_ids': list(analysis.priority_ids) if analysis else [],
            'explanation_refs': [{'cache_key': e.cache_key, 'hash': digest(e.payload)} for e in explanations],
            'original_ranking': [{'property_id': r['property']['property_id'], 'score': r['rank_score'],
                                  'factors': r['ranking_factors']} for r in snapshot['results']],
            'ranking_policy': snapshot['ranking_policy'], 'capture_semantics': 'delivery_capture' if delivery_capture else 'ranking_at_manifest_capture',
            'historical_original_ranking_verified': delivery_capture}
    manifest_id = 'replay_' + digest(payload)
    with db.session.begin() as session:
        if not session.get(ReplayManifest, manifest_id):
            session.add(ReplayManifest(manifest_id=manifest_id, request_id=request_id, payload=payload, created_at=utcnow()))
    return {'manifest_id': manifest_id, **payload}


def replay_manifest(db, manifest_id, *, include_private=False):
    with db.session() as session:
        manifest = session.get(ReplayManifest, manifest_id)
        if not manifest:
            raise KeyError('Unknown manifest')
        payload = deepcopy(manifest.payload)
        missing, rows, routes = [], {}, {}
        req = session.get(SearchRequest, manifest.request_id)
        if not req or digest(req.state) != payload['state_hash']:
            missing.append('confirmed_state')
        for ref in payload['candidate_refs']:
            row = session.get(Candidate, (manifest.request_id, ref['property_id']))
            if not row or digest([row.property_snapshot, row.property_verdicts]) != ref['hash']:
                missing.append('candidate:' + ref['property_id'])
            elif ref.get('accessibility_hash') and digest(row.accessibility_snapshot) != ref['accessibility_hash']:
                missing.append('accessibility:' + ref['property_id'])
            else:
                facts = deepcopy(row.property_snapshot)
                if not include_private:
                    for key in ('source_records', 'latitude', 'longitude', 'title_fa'):
                        facts.pop(key, None)
                rows[ref['property_id']] = {'property': facts, 'property_verdicts': row.property_verdicts, **({'accessibility': deepcopy(row.accessibility_snapshot)} if ref.get('accessibility_hash') else {})}
        for ref in payload['route_refs']:
            row = session.get(Evaluation, (manifest.request_id, ref['property_id']))
            if not row or digest(row.result) != ref['hash']:
                missing.append('route:' + ref['property_id'])
            else:
                routes[ref['property_id']] = row.result
        analysis = session.get(SearchAnalysis, manifest.request_id)
        if payload['analysis_hash'] and (not analysis or digest(analysis.metadata_json) != payload['analysis_hash']):
            missing.append('retrieval')
        explanations = []
        for ref in payload['explanation_refs']:
            row = session.get(ExplanationCache, ref['cache_key'])
            if not row or digest(row.payload) != ref['hash']:
                missing.append('explanation:' + ref['cache_key'])
            else:
                explanations.append(row.payload)
        for pid, row in rows.items():
            result = routes.get(pid, {})
            if row.get('accessibility') and result.get('accessibility'):
                from .accessibility import select_result
                saved_sort = (req.state if req else payload['confirmed_state']).get('sort')
                result = select_result(result, 'less_walking' if saved_sort in ('walk_time_asc', 'stop_walk_time_asc') else 'faster_commute')
                row['accessibility'] = result['accessibility']
            selected = result.get('selected_itinerary')
            if selected and not include_private:
                allowed_route = ('itinerary_id', 'total_duration_seconds', 'walk_duration_seconds', 'walk_distance_meters', 'transfers', 'source_kind', 'schedule_basis', 'realtime_status', 'location_accuracy')
                selected = {k: selected.get(k) for k in allowed_route}
            row['selected_itinerary'] = selected
            row['route_status'] = result.get('status', 'not_evaluated')
            row['travel_verdicts'] = result.get('verdicts', [])
        return {'manifest_id': manifest_id, **payload, 'status': 'partial_replay' if missing else 'ok',
                'missing_evidence': missing, 'rows': rows,
                'state': deepcopy(req.state) if include_private and req else payload['confirmed_state'],
                'retrieval': analysis.metadata_json if analysis and 'retrieval' not in missing else None,
                'explanations': explanations if include_private else {'count': len(explanations)},
                'network_calls': 0}


def capture_delivery(db, snapshot):
    if snapshot.get('completion_status') != 'complete' or snapshot.get('semantic', {}).get('status') == 'pending':
        return
    with db.session() as session:
        manifests = session.scalars(select(ReplayManifest).where(ReplayManifest.request_id == snapshot['request_id']))
        if any(m.payload.get('historical_original_ranking_verified') for m in manifests):
            return
    freeze_manifest(db, snapshot['request_id'], delivery_capture=True)
