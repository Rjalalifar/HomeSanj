"""Human-signed guardrails are necessary but cannot override missing measured evidence."""
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, new_id, utcnow
from .evaluation_store import Experiment, Release
from .evaluation_replay import digest

GUARDRAILS = {'hard_constraints', 'privacy', 'grounding', 'latency', 'cost', 'coverage', 'index_freshness', 'regression_tests'}


class ReleaseApproval(Base):
    __tablename__ = 'release_guardrail_approvals'
    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String, index=True)
    report_hash: Mapped[str] = mapped_column(String)
    reviewer_id: Mapped[str] = mapped_column(String)
    checks: Mapped[dict] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String)


def approve_guardrails(db, experiment_id, reviewer, checks, evidence_refs):
    if set(checks) != GUARDRAILS or any(type(v) is not bool for v in checks.values()) or not evidence_refs:
        raise ValueError('Every guardrail needs an explicit human check and supporting evidence references')
    with db.session.begin() as session:
        experiment = session.get(Experiment, experiment_id)
        if not experiment:
            raise ValueError('Unknown experiment')
        approval = ReleaseApproval(approval_id=new_id('approval'), experiment_id=experiment_id,
            report_hash=digest(experiment.report), reviewer_id=reviewer, checks=checks,
            evidence_refs=evidence_refs, created_at=utcnow())
        session.add(approval)
    return {'approval_id': approval.approval_id, 'production_changed': False}


def active_production_config(db):
    with db.session() as session:
        release = session.scalar(select(Release).where(Release.scope == 'production').order_by(Release.created_at.desc(), Release.release_id.desc()).limit(1))
        return release.config if release else {}


def verify_promotion(session, experiment, approval_id, reviewer):
    approval = session.get(ReleaseApproval, approval_id) if approval_id else None
    report = experiment.report
    cases = [c for c in report['cases'] if c.get('status') == 'ok']
    return {'human_approval': bool(approval and approval.reviewer_id == reviewer and approval.report_hash == digest(report)),
        'all_guardrails_signed': bool(approval and set(approval.checks) == GUARDRAILS and all(approval.checks.values())),
        'fully_judged_real_cohort': bool(cases) and all(c['actor_cohort'] == 'real_user' and c['metrics']['baseline']['fully_judged_pool'] and c['label_origin'] == 'human' for c in cases),
        'minimum_judged_pool_members': sum(c['metrics']['baseline']['pool_size'] for c in cases) >= 200,
        'minimum_independent_groups': report['uncertainty'].get('independent_tasks', 0) >= 30,
        'positive_paired_lower_bound': bool(report['uncertainty'].get('interval') and report['uncertainty']['interval'][0] > 0),
        'final_holdout': report['split'] == 'holdout'}
