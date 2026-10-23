"""Leased, blind human review extending the existing sample and annotation tables."""
from collections import defaultdict
from copy import deepcopy
import os
import random
import time
from typing import Literal
from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select, text
from .contracts import PatchOperation, SearchState, apply_patch
from .db import SearchRequest, new_id, utcnow
from .explanations import StrictModel, evidence_facts
from .feedback import ReviewSample, ReviewAnnotation, Feedback, frozen_row, content_hash
from .evaluation_metrics import RUBRIC_VERSION
from .evaluation_replay import freeze_manifest, replay_manifest, safe_state

SAMPLING_POLICY = 'stratified-10-4-4-2-critical-1'
ANNOTATION_TYPES = Literal['relevance_grade', 'corrected_intent_patch', 'pairwise_preference',
    'grounding_issue', 'explanation_comparison_issue', 'semantic_retrieval_miss',
    'candidate_eligibility_issue', 'data_issue', 'infrastructure_issue']


class ReviewInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    revision: int = Field(ge=0)
    annotation_type: ANNOTATION_TYPES = 'relevance_grade'
    grade: int | None = Field(default=None, ge=0, le=3, strict=True)
    evidence_refs: list[str] = Field(default_factory=list, max_length=40)
    reason: Literal['budget', 'commute', 'amenities', 'location', 'missing_evidence', 'other'] = 'other'
    operations: list[PatchOperation] = Field(default_factory=list, max_length=20)
    preferred_id: str | None = Field(default=None, max_length=120)
    other_id: str | None = Field(default=None, max_length=120)
    supersedes: str | None = Field(default=None, max_length=120)
    action: Literal['annotate', 'skip', 'insufficient_evidence', 'resolve', 'escalate'] = 'annotate'

    @model_validator(mode='after')
    def typed_values(self):
        if self.grade is not None and self.annotation_type != 'relevance_grade':
            raise ValueError('Grade is only valid for relevance_grade')
        if self.operations and self.annotation_type != 'corrected_intent_patch':
            raise ValueError('Patch is only valid for corrected_intent_patch')
        if self.annotation_type == 'corrected_intent_patch' and self.action == 'annotate' and not self.operations:
            raise ValueError('A corrected intent requires operations')
        return self


def sample_view(session, sample, reviewer):
    annotations = list(session.scalars(select(ReviewAnnotation).where(ReviewAnnotation.sample_id == sample.sample_id).order_by(ReviewAnnotation.created_at)))
    initial = any(a.reviewer_id == reviewer and a.annotation_kind == 'human_confirmed' and a.annotation_data.get('type') == 'relevance_grade' and a.annotation_data.get('action') == 'annotate' for a in annotations)
    evidence = deepcopy(sample.evidence)
    if not initial:
        for key in ('actual_rank', 'utility_components', 'original_explanations'):
            evidence.pop(key, None)
        for key in ('rank', 'rank_score', 'ranking_factors', 'utility'):
            evidence.get('frozen_candidate', {}).pop(key, None)
    history = [{'annotation_id': a.annotation_id, 'origin': a.annotation_kind, 'created_at': a.created_at,
                'data': a.annotation_data, 'evidence_refs': a.evidence_refs} for a in annotations
               if initial or (a.reviewer_id == reviewer and a.annotation_kind == 'human_confirmed')]
    workflow = sample.workflow or {}
    return {'sample_id': sample.sample_id, 'request_id': sample.request_id, 'snapshot_id': sample.snapshot_id,
            'candidate_id': sample.candidate_id, 'status': sample.status, 'actor_kind': sample.actor_kind,
            'reasons': sample.reasons, 'evidence': evidence, 'revision': workflow.get('revision', 0),
            'leased_by_you': workflow.get('lease_owner') == reviewer and workflow.get('lease_until', 0) > time.time(),
            'lease_until': workflow.get('lease_until', 0), 'assigned_to': workflow.get('assigned_to'), 'priority': workflow.get('priority', 'critical' if 'critical' in sample.reasons else 'normal'), 'issue_history': workflow.get('issue_history', []), 'initial_blind': not initial,
            'sampling': workflow.get('sampling'), 'history': history, 'rubric_version': RUBRIC_VERSION}


def list_samples(db, reviewer, *, status=None, mode=None, origin=None, issue=None, version=None, priority=None, limit=50):
    with db.session() as session:
        query = select(ReviewSample).order_by(ReviewSample.created_at.desc())
        if status:
            query = query.where(ReviewSample.status == status)
        if origin:
            query = query.where(ReviewSample.actor_kind == origin)
        rows = session.scalars(query.limit(1000))
        result = []
        for row in rows:
            if mode and row.evidence.get('search_mode') != mode:
                continue
            if issue and issue not in row.reasons:
                continue
            if version and row.sampler_version != version:
                continue
            if priority and (row.workflow or {}).get('priority', 'critical' if 'critical' in row.reasons else 'normal') != priority:
                continue
            result.append(sample_view(session, row, reviewer))
            if len(result) >= limit:
                break
        return result


def claim(db, sample_id, reviewer, revision, now=None):
    now = time.time() if now is None else now
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        sample = session.get(ReviewSample, sample_id)
        if sample is None:
            raise HTTPException(404, 'Unknown sample')
        w = dict(sample.workflow or {})
        if w.get('assigned_to') and w['assigned_to'] != reviewer:
            raise HTTPException(409, 'Sample is assigned to another reviewer')
        if w.get('revision', 0) != revision:
            raise HTTPException(409, 'Stale review revision')
        if w.get('lease_until', 0) > now and w.get('lease_owner') != reviewer:
            raise HTTPException(409, 'Sample is leased by another reviewer')
        w.update(lease_owner=reviewer, lease_until=now + 600, revision=revision + 1)
        sample.workflow = w
        session.commit()
        return sample_view(session, sample, reviewer)


def annotate(db, sample_id, reviewer, data: ReviewInput):
    hashed = content_hash({'sample_id': sample_id, **data.model_dump(mode='json')})
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        previous = session.scalar(select(ReviewAnnotation).where(ReviewAnnotation.reviewer_id == reviewer,
            ReviewAnnotation.idempotency_key == data.idempotency_key))
        if previous:
            if previous.content_hash != hashed:
                raise HTTPException(409, 'Idempotency conflict')
            return {'annotation_id': previous.annotation_id, 'status': 'duplicate'}
        sample = session.get(ReviewSample, sample_id)
        if not sample:
            raise HTTPException(404, 'Unknown sample')
        w = dict(sample.workflow or {})
        if w.get('revision', 0) != data.revision or w.get('lease_owner') != reviewer or w.get('lease_until', 0) <= time.time():
            raise HTTPException(409, 'An active lease at the current revision is required')
        if not set(data.evidence_refs) <= set(sample.evidence.get('facts', {})):
            raise HTTPException(422, 'Evidence reference is outside the frozen sample')
        if data.grade is not None and not data.evidence_refs:
            raise HTTPException(422, 'A numeric relevance grade requires evidence')
        existing = list(session.scalars(select(ReviewAnnotation).where(ReviewAnnotation.sample_id == sample_id)))
        if data.supersedes:
            target = next((a for a in existing if a.annotation_id == data.supersedes and a.reviewer_id == reviewer), None)
            if target is None or any(a.annotation_data.get('supersedes') == data.supersedes for a in existing):
                raise HTTPException(409, 'Supersession target is missing, foreign or already superseded')
        fixture_review = os.getenv('REVIEW_ANNOTATION_SOURCE') == 'automated_test'
        metadata = {'type': data.annotation_type, 'grade': data.grade, 'origin': 'test_fixture' if fixture_review else 'human',
                    'synthetic': sample.actor_kind != 'real_user', 'approval_state': 'reviewed',
                    'supersedes': data.supersedes, 'rubric_version': RUBRIC_VERSION, 'action': data.action,
                    'review_status': 'automated_fixture' if fixture_review else 'independent_human', 'blind_initial': not any(a.reviewer_id == reviewer and a.annotation_kind == 'human_confirmed' and a.annotation_data.get('type') == 'relevance_grade' and a.annotation_data.get('action') == 'annotate' for a in existing)}
        if data.annotation_type == 'corrected_intent_patch':
            req = session.get(SearchRequest, sample.request_id)
            if not req:
                raise HTTPException(409, 'Source intent was removed')
            updated = apply_patch(SearchState.model_validate(req.state), data.operations)
            metadata.update(operations=[p.model_dump(mode='json') for p in data.operations], proposed_state=safe_state(updated.model_dump(mode='json')))
        if data.annotation_type == 'pairwise_preference':
            from .db import Candidate
            if data.other_id == sample.candidate_id or not session.get(Candidate, (sample.request_id, data.other_id or '')):
                raise HTTPException(422, 'Pair must reference two candidates from the same snapshot')
            if data.preferred_id not in (sample.candidate_id, data.other_id, None):
                raise HTTPException(422, 'Preferred ID is outside the pair')
            metadata.update(other_id=data.other_id, preferred_id=data.preferred_id)
        annotation = ReviewAnnotation(annotation_id=new_id('annotation'), sample_id=sample_id, reviewer_id=reviewer,
            idempotency_key=data.idempotency_key, content_hash=hashed, annotation_kind='fixture_reviewed' if fixture_review else 'human_confirmed',
            label='uncertain' if data.grade is None else 'positive' if data.grade >= 2 else 'negative',
            reason_code=data.reason, evidence_refs=data.evidence_refs, needs_human_review=False,
            model_version=None, annotation_data=metadata, created_at=utcnow())
        session.add(annotation)
        sample.status = {'skip': 'skipped', 'insufficient_evidence': 'insufficient_evidence',
                         'escalate': 'escalated', 'resolve': 'resolved'}.get(data.action, 'human_reviewed')
        sample.workflow = w | {'revision': data.revision + 1, 'lease_owner': None, 'lease_until': 0}
        session.commit()
        return {'annotation_id': annotation.annotation_id, 'status': sample.status, 'revision': data.revision + 1}


def acquire_batch(db, request_ids, seed=17, batch_size=20, owner_session='internal_acquisition'):
    if not 1 <= batch_size <= 100 or len(request_ids) > 100:
        raise ValueError('Bounded acquisition requires <=100 requests and <=100 samples')
    from .catalog import SearchAnalysis
    from .evaluation_store import DatasetVersion
    with db.session() as session:
        locked_holdout = {task for version in session.scalars(select(DatasetVersion)) for task, group in version.manifest.get('task_groups', {}).items() if group['split'] == 'holdout'}
        blocked_requests = {r.request_id for r in session.scalars(select(SearchRequest).where(SearchRequest.request_id.in_(request_ids))) if r.task_id in locked_holdout}
    request_ids = [rid for rid in request_ids if rid not in blocked_requests]
    frames, strata = {}, defaultdict(list)
    with db.session() as session:
        existing = {(s.request_id, s.candidate_id) for s in session.scalars(select(ReviewSample))}
        feedback_rows = list(session.scalars(select(Feedback).where(Feedback.request_id.in_(request_ids))))
        modes = {row.request_id: row.search_mode for row in session.scalars(
            select(SearchAnalysis).where(SearchAnalysis.request_id.in_(request_ids)))
            if row.search_mode in ('normal', 'advanced')}
    labels = defaultdict(set)
    for f in feedback_rows:
        if f.kind == 'property':
            for pid in f.candidate_ids:
                labels[(f.request_id, pid)].add(f.label)
    for rid in sorted(set(request_ids)):
        manifest = freeze_manifest(db, rid)
        frozen = replay_manifest(db, manifest['manifest_id'], include_private=True)
        # A legacy rendering default is not evidence of the original search mode.
        frozen['mode'] = modes.get(rid, 'unknown')
        for pid, row in frozen['rows'].items():
            if (rid, pid) in existing:
                continue
            from .review_sampling import classify
            kind, reason = classify(row, frozen, labels[(rid, pid)])
            key = (rid, pid)
            frames[key] = (frozen, row, reason)
            strata[kind].append(key)
    from .review_sampling import select_batch
    picked = select_batch(frames, strata, batch_size, seed)
    output = []
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        for (rid, pid), category, probability in picked:
            if session.scalar(select(ReviewSample.sample_id).where(ReviewSample.request_id == rid, ReviewSample.candidate_id == pid)):
                continue
            frozen, row, reason = frames[(rid, pid)]
            row['rank_score'] = next((r['score'] for r in frozen['original_ranking'] if r['property_id'] == pid), None)
            evidence = {'facts': evidence_facts([row]), 'frozen_candidate': frozen_row(row, 0),
                'uncertainty': 'unavailable_without_a_calibrated_model', 'confirmed_state': frozen['confirmed_state'], 'search_mode': frozen['mode'],
                'manifest_id': frozen['manifest_id'], 'versions': frozen['versions'],
                'candidate_count': frozen['candidate_count'], 'evaluated_count': frozen['evaluated_count'],
                'ranking_scope': frozen['ranking_scope'], 'retrieval': frozen.get('retrieval') or {},
                'actual_rank': next((i+1 for i, r in enumerate(frozen['original_ranking']) if r['property_id'] == pid), None),
                'utility_components': next((r['factors'] for r in frozen['original_ranking'] if r['property_id'] == pid), {}),
                'original_explanations': frozen.get('explanations', [])}
            sample = ReviewSample(sample_id=new_id('sample'), request_id=rid, snapshot_id=frozen['snapshot_id'],
                task_id=frozen['task_id'], owner_session=owner_session, candidate_id=pid,
                actor_kind=frozen['actor_cohort'], sampler_version=SAMPLING_POLICY, reasons=[reason, category],
                propensity=None, evidence=evidence, status='pending', created_at=utcnow(),
                workflow={'revision': 0, 'sampling': {'seed': seed, 'policy': SAMPLING_POLICY, 'stratum': category,
                    'frame_size': len(frames), 'frame_hash': content_hash(sorted(frames)),
                    'conditional_random_probability': probability, 'overall_inclusion_probability': None}})
            session.add(sample)
            output.append(sample.sample_id)
        session.commit()
    return {'sample_ids': output, 'frame_size': len(frames), 'critical_outside_quota': len(strata['critical']),
            'batch_size': batch_size, 'policy': SAMPLING_POLICY, 'seed': seed, 'holdout_requests_excluded': len(blocked_requests)}
