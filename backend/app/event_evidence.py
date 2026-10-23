"""Indexed event evidence lookup without reranking the complete candidate set."""
from fastapi import HTTPException
from sqlalchemy import select

from .db import Candidate, Evaluation, SearchRequest


def request_actor(session, request_id):
    synthetic = session.scalar(select(Candidate.property_id).where(
        Candidate.request_id == request_id,
        Candidate.property_snapshot['is_synthetic'].as_boolean().is_(True)).limit(1))
    fixture = session.scalar(select(Evaluation.property_id).where(
        Evaluation.request_id == request_id,
        Evaluation.result['selected_itinerary']['source_kind'].as_string() == 'synthetic_fixture').limit(1))
    return 'demo' if synthetic is not None or fixture is not None else 'real_user'


def event_snapshot(db, request_id, candidate_id):
    with db.session() as session:
        req = session.get(SearchRequest, request_id)
        if req is None:
            raise HTTPException(404, 'Unknown request')
        rows = []
        if candidate_id:
            candidate = session.get(Candidate, (request_id, candidate_id))
            evaluation = session.get(Evaluation, (request_id, candidate_id))
            result = evaluation.result if evaluation else {}
            if candidate is not None and all(v['verdict'] == 'pass' for v in candidate.property_verdicts):
                if (req.state.get('accessibility') or {}).get('enabled') or not req.state['travel'].get('destination') or result.get('status') == 'ok':
                    rows.append({'property': candidate.property_snapshot,
                                 'selected_itinerary': result.get('selected_itinerary')})
        return {'task_id': req.task_id, 'request_id': request_id,
                'snapshot_id': req.snapshot_id, 'state': req.state, 'results': rows,
                'actor_kind': request_actor(session, request_id)}, rows


def qualifying_alternatives(evaluation):
    if not evaluation:
        return []
    accepted = {item['itinerary_id'] for item in evaluation.get('itinerary_evaluations', [])
                if item.get('verdicts') and all(v['verdict'] == 'pass' for v in item['verdicts'])}
    return [item for item in evaluation.get('itineraries', []) if item['itinerary_id'] in accepted]
