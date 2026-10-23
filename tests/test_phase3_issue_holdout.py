"""Assignments and holdout safeguards remain enforceable outside the browser."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from backend.app.db import Database
from backend.app.feedback import ReviewSample, ReviewAnnotation, SamplingInput, select_review_samples
from backend.app.review_workflow import claim, acquire_batch
from backend.app.review_issues import assign, add_issue
from backend.app.evaluation_store import DatasetVersion
from tests.test_feedback import request_fixture


def test_assignment_cannot_be_overwritten_by_claim_or_active_lease(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "assign.sqlite"}')
    db.migrate()
    rid = request_fixture(db)
    sid = select_review_samples(db, 'owner', SamplingInput(request_id=rid, limit=1))['samples'][0]['sample_id']
    assign(db, sid, 'admin', 'alice', 0)
    with pytest.raises(HTTPException):
        claim(db, sid, 'bob', 1)
    claim(db, sid, 'alice', 1)
    with pytest.raises(HTTPException):
        assign(db, sid, 'admin', 'bob', 2)


def test_issue_requires_same_sample_evidence_and_is_idempotent(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "issues.sqlite"}')
    db.migrate()
    rid = request_fixture(db)
    sid = select_review_samples(db, 'owner', SamplingInput(request_id=rid, limit=1))['samples'][0]['sample_id']
    with db.session() as session:
        ref = next(iter(session.get(ReviewSample, sid).evidence['facts']))
    with pytest.raises(ValueError):
        add_issue(db, sid, 'coverage_failure', ['wrong'], 'human')
    assert add_issue(db, sid, 'coverage_failure', [ref], 'human')['status'] == 'recorded'
    assert add_issue(db, sid, 'coverage_failure', [ref], 'human')['status'] == 'duplicate'


def test_exported_holdout_is_excluded_from_active_acquisition(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "holdout.sqlite"}')
    db.migrate()
    rid = request_fixture(db)
    with db.session.begin() as session:
        session.add(DatasetVersion(dataset_id='fixed', created_at='2026-01-01', manifest={'task_groups': {'task_first': {'group_id': 'group', 'split': 'holdout'}}}))
    result = acquire_batch(db, [rid])
    assert result['sample_ids'] == [] and result['holdout_requests_excluded'] == 1
