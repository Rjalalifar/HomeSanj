"""Evidence-linked operational issues on the existing review queue."""
from collections import defaultdict
from sqlalchemy import select, text
from fastapi import HTTPException
from .db import utcnow
from .feedback import ReviewSample, ReviewAnnotation

ISSUE_TRACKS = {
    'hard_constraint_violation': 'preference', 'human_judge_disagreement': 'judge',
    'explicit_feedback_conflict': 'preference', 'ranking_judge_disagreement': 'preference',
    'parser_or_evidence_uncertain': 'preference', 'judge_instability': 'judge',
    'novel_pattern': 'preference', 'semantic_retrieval_miss': 'preference',
    'vector_lexical_disagreement': 'preference', 'qdrant_stale_or_missing_item': 'infrastructure',
    'advanced_explanation_unsupported': 'judge', 'client_server_filter_disagreement': 'infrastructure',
    'coverage_failure': 'infrastructure', 'random_audit': 'audit',
}
ISSUE_POLICY_VERSION = 'evidence-linked-review-issues-1'


def add_issue(db, sample_id, issue, evidence_refs, actor):
    if issue not in ISSUE_TRACKS:
        raise ValueError('Unsupported issue code')
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        sample = session.get(ReviewSample, sample_id)
        if not sample:
            raise HTTPException(404, 'Unknown sample')
        if not evidence_refs:
            raise ValueError('An issue requires evidence references')
        annotation_ids = set(session.scalars(select(ReviewAnnotation.annotation_id).where(ReviewAnnotation.sample_id == sample_id)))
        allowed = set(sample.evidence.get('facts', {})) | annotation_ids
        if not set(evidence_refs) <= allowed:
            raise ValueError('Issue evidence is outside the sample')
        workflow = dict(sample.workflow or {})
        history = list(workflow.get('issue_history', []))
        if any(row['code'] == issue and row['evidence_refs'] == sorted(evidence_refs) for row in history):
            return {'status': 'duplicate', 'sample_id': sample_id}
        history.append({'code': issue, 'track': ISSUE_TRACKS[issue], 'evidence_refs': sorted(evidence_refs),
            'recorded_by': actor, 'created_at': utcnow(), 'policy_version': ISSUE_POLICY_VERSION})
        sample.workflow = workflow | {'issue_history': history, 'priority': 'critical' if issue == 'hard_constraint_violation' else 'high'}
        sample.reasons = list(dict.fromkeys(sample.reasons + [issue]))
        if sample.status in ('resolved', 'human_reviewed'):
            sample.status = 'pending'
        session.commit()
    return {'status': 'recorded', 'sample_id': sample_id, 'track': ISSUE_TRACKS[issue]}


def refresh_disagreements(db):
    with db.session() as session:
        annotations = list(session.scalars(select(ReviewAnnotation).order_by(ReviewAnnotation.created_at)))
    groups = defaultdict(list)
    superseded = {a.annotation_data.get('supersedes') for a in annotations}
    for a in annotations:
        if a.annotation_id not in superseded:
            groups[a.sample_id].append(a)
    issues = []
    for sid, values in groups.items():
        humans = [a for a in values if a.annotation_kind == 'human_confirmed' and a.annotation_data.get('grade') is not None]
        judges = [a for a in values if a.annotation_data.get('origin') == 'ai_weak' and a.annotation_data.get('grade') is not None]
        if not humans or not judges:
            continue
        h, j = humans[-1], judges[-1]
        hg, jg = h.annotation_data['grade'], j.annotation_data['grade']
        if (hg >= 2) != (jg >= 2) or abs(hg-jg) >= 2:
            issues.append(add_issue(db, sid, 'human_judge_disagreement', [h.annotation_id, j.annotation_id], 'deterministic_issue_rule'))
    return {'issues': issues, 'policy_version': ISSUE_POLICY_VERSION}


def assign(db, sample_id, actor, reviewer_id, revision):
    import time
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        sample = session.get(ReviewSample, sample_id)
        if not sample:
            raise HTTPException(404, 'Unknown sample')
        w = dict(sample.workflow or {})
        if w.get('revision', 0) != revision or w.get('lease_until', 0) > time.time():
            raise HTTPException(409, 'Assignment requires current revision and no active lease')
        history = list(w.get('assignment_history', [])) + [{'actor': actor, 'assigned_to': reviewer_id, 'at': utcnow()}]
        sample.workflow = w | {'assigned_to': reviewer_id, 'revision': revision+1, 'assignment_history': history}
        session.commit()
    return {'status': 'assigned', 'revision': revision+1, 'reviewer_id': reviewer_id}
