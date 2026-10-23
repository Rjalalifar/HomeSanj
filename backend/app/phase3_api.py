"""Restricted internal APIs sharing the existing FastAPI application and identity guard."""
from typing import Literal
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select
from .explanations import StrictModel
from .feedback import reviewer_identity
from .review_workflow import ReviewInput, list_samples, claim, annotate
from .evaluation_dashboard import dashboard
from .evaluation_replay import freeze_manifest, replay_manifest
from .evaluation_store import OfflineJob, DatasetVersion
from .offline_evaluation import enqueue, enqueue_judge, OfflineWorker
from .evaluation_experiments import compare, release


class ClaimInput(StrictModel):
    revision: int = Field(ge=0)


class AcquireInput(StrictModel):
    request_ids: list[str] = Field(min_length=1, max_length=100)
    seed: int = 17
    batch_size: int = Field(default=20, ge=1, le=100)


class CompareInput(StrictModel):
    manifest_ids: list[str] = Field(min_length=1, max_length=100)
    rent_weight_multiplier: float = Field(default=1.25, ge=.1, le=4)
    split: Literal['validation', 'holdout', 'mechanical_demo'] = 'validation'


class ReleaseInput(StrictModel):
    experiment_id: str | None = None
    action: Literal['promote', 'rollback'] = 'promote'
    scope: Literal['test', 'production'] = 'test'
    target_id: str | None = None
    approval_id: str | None = None



class ApprovalInput(StrictModel):
    experiment_id: str
    checks: dict[str, bool]
    evidence_refs: list[str] = Field(min_length=1, max_length=20)


class ImprovementInput(StrictModel):
    annotation_ids: list[str] = Field(min_length=1, max_length=20)


class PairInput(StrictModel):
    sample_ids: list[str] = Field(min_length=2, max_length=2)
    seed: int = 17
    swap: bool = True


class AssignmentInput(StrictModel):
    reviewer_id: str | None = Field(default=None, max_length=80)
    revision: int = Field(ge=0)


class IssueInput(StrictModel):
    issue: str = Field(max_length=80)
    evidence_refs: list[str] = Field(min_length=1, max_length=40)

def install_phase3(app, db, provider):
    worker = OfflineWorker(db, provider)
    app.state.offline_worker = worker

    @app.get('/internal')
    def internal_page():
        return FileResponse('frontend/dist/index.html', headers={'Cache-Control': 'no-store'})

    @app.get('/api/internal/dashboard')
    def get_dashboard(request: Request):
        reviewer_identity(request)
        return dashboard(db)

    @app.get('/api/internal/reviews')
    def reviews(request: Request, status: str | None = None, mode: str | None = None,
                origin: str | None = None, issue: str | None = None, version: str | None = None, priority: str | None = None):
        return {'samples': list_samples(db, reviewer_identity(request), status=status, mode=mode,
                    origin=origin, issue=issue, version=version, priority=priority)}

    @app.post('/api/internal/reviews/{sample_id}/claim')
    def claim_sample(sample_id: str, body: ClaimInput, request: Request):
        return claim(db, sample_id, reviewer_identity(request), body.revision)

    @app.post('/api/internal/reviews/{sample_id}/annotations')
    def annotation(sample_id: str, body: ReviewInput, request: Request):
        return annotate(db, sample_id, reviewer_identity(request), body)

    @app.post('/api/internal/reviews/{sample_id}/judge')
    def judge(sample_id: str, request: Request):
        reviewer_identity(request)
        return {'job_id': enqueue_judge(db, sample_id, provider)}

    @app.post('/api/internal/acquire')
    def acquire(body: AcquireInput, request: Request):
        reviewer_identity(request)
        return {'job_id': enqueue(db, 'acquisition', body.model_dump())}

    @app.post('/api/internal/datasets/export')
    def export(request: Request):
        reviewer_identity(request)
        from .feedback import ReviewAnnotation
        from .evaluation_replay import digest
        with db.session() as session:
            identity = digest(sorted(session.scalars(select(ReviewAnnotation.annotation_id))))
        return {'job_id': enqueue(db, 'export', {'annotation_revision': identity})}

    @app.get('/api/internal/jobs/{job_id}')
    def job_status(job_id: str, request: Request):
        reviewer_identity(request)
        with db.session() as session:
            job = session.get(OfflineJob, job_id)
            if not job:
                raise HTTPException(404, 'Unknown job')
            return {'job_id': job_id, 'status': job.status, 'attempts': job.attempts, 'result': job.result}

    @app.post('/api/internal/manifests/{request_id}')
    def manifest(request_id: str, request: Request):
        reviewer_identity(request)
        try:
            return freeze_manifest(db, request_id)
        except KeyError:
            raise HTTPException(404, 'Unknown request') from None

    @app.get('/api/internal/replay/{manifest_id}')
    def replay(manifest_id: str, request: Request):
        reviewer_identity(request)
        try:
            return replay_manifest(db, manifest_id)
        except KeyError:
            raise HTTPException(404, 'Unknown manifest') from None

    @app.post('/api/internal/experiments')
    def experiment(body: CompareInput, request: Request):
        reviewer_identity(request)
        return compare(db, body.manifest_ids, {'rent_weight_multiplier': body.rent_weight_multiplier}, split=body.split)

    @app.post('/api/internal/releases')
    def promote(body: ReleaseInput, request: Request):
        reviewer = reviewer_identity(request)
        try:
            return release(db, **body.model_dump(), approved_by=reviewer)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None


    @app.post('/api/internal/approvals')
    def approve(body: ApprovalInput, request: Request):
        from .release_control import approve_guardrails
        try:
            return approve_guardrails(db, reviewer=reviewer_identity(request), **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post('/api/internal/improvement')
    def improvement(body: ImprovementInput, request: Request):
        reviewer_identity(request)
        return {'job_id': enqueue(db, 'improvement', body.model_dump() | {'model': provider.models['improvement'], 'version': provider.role_versions['improvement']})}

    @app.post('/api/internal/pairwise')
    def pairwise(body: PairInput, request: Request):
        reviewer_identity(request)
        from .feedback import ReviewSample
        from .offline_evaluation import blind_packet, JUDGE_PROMPT_VERSION, JUDGE_SCHEMA_VERSION
        from .evaluation_replay import digest
        with db.session() as session:
            samples = [session.get(ReviewSample, sid) for sid in body.sample_ids]
            if any(sample is None for sample in samples):
                raise HTTPException(404, 'Unknown sample')
            hashes = [digest(blind_packet(sample)) for sample in samples]
        return {'job_id': enqueue(db, 'pairwise', {'parameters': body.model_dump(), 'evidence_hashes': hashes, 'model': provider.models['judge'], 'prompt_version': 'blind-pairwise-1', 'schema_version': JUDGE_SCHEMA_VERSION, 'rubric_version': 'hard-pass-relevance-0-3-1'})}

    @app.get('/api/internal/datasets/{dataset_id}/{filename}')
    def download_dataset(dataset_id: str, filename: Literal['annotations.jsonl', 'manifest.json'], request: Request):
        from pathlib import Path
        reviewer_identity(request)
        with db.session() as session:
            if not session.get(DatasetVersion, dataset_id):
                raise HTTPException(404, 'Unknown dataset')
        if not dataset_id.startswith('annotations_') or not dataset_id.removeprefix('annotations_').isalnum():
            raise HTTPException(422, 'Invalid dataset identity')
        path = Path('runtime/datasets') / dataset_id / filename
        if not path.is_file():
            raise HTTPException(404, 'Dataset file is unavailable')
        return FileResponse(path, filename=filename, headers={'Cache-Control': 'no-store'})

    @app.get('/api/internal/reviews/{sample_id}/pair/{candidate_id}')
    def pair_evidence(sample_id: str, candidate_id: str, request: Request):
        from .feedback import ReviewSample, frozen_row
        from .db import Candidate, Evaluation
        reviewer_identity(request)
        with db.session() as session:
            sample = session.get(ReviewSample, sample_id)
            item = session.get(Candidate, (sample.request_id, candidate_id)) if sample else None
            if not item:
                raise HTTPException(404, 'Candidate is outside this snapshot')
            evaluation = session.get(Evaluation, (sample.request_id, candidate_id))
            result = evaluation.result if evaluation else {}
            row = frozen_row({'property': item.property_snapshot, 'property_verdicts': item.property_verdicts,
                'travel_verdicts': result.get('verdicts', []), 'selected_itinerary': result.get('selected_itinerary')}, 0)
            for key in ('rank', 'rank_score'):
                row.pop(key, None)
            return row

    @app.post('/api/internal/explanations/{cache_key}/judge')
    def grounding_audit(cache_key: str, request: Request):
        from .explanations import ExplanationCache
        from .evaluation_replay import digest
        reviewer_identity(request)
        with db.session() as session:
            row = session.get(ExplanationCache, cache_key)
            if row is None:
                raise HTTPException(404, 'Original explanation is unavailable')
            source_hash = digest(row.payload)
        return {'job_id': enqueue(db, 'grounding', {'cache_key': cache_key, 'source_hash': source_hash,
            'model': provider.models['judge'], 'prompt_version': 'original-claims-only-1'})}

    @app.get('/api/internal/reviewers')
    def reviewers(request: Request):
        import hashlib
        import json
        import os
        current = reviewer_identity(request)
        configured = json.loads(os.getenv('REVIEWER_TOKENS_JSON', '{}'))
        choices = [{'reviewer_id': 'reviewer_' + hashlib.sha256(name.encode()).hexdigest()[:16], 'label': name}
                   for name, token in configured.items() if isinstance(token, str) and len(token) >= 16]
        if not any(c['reviewer_id'] == current for c in choices):
            choices.append({'reviewer_id': current, 'label': 'Current reviewer'})
        return {'current': current, 'reviewers': choices}

    @app.post('/api/internal/reviews/{sample_id}/assign')
    def assign_sample(sample_id: str, body: AssignmentInput, request: Request):
        from .review_issues import assign
        identities = reviewers(request)
        if body.reviewer_id and body.reviewer_id not in {r['reviewer_id'] for r in identities['reviewers']}:
            raise HTTPException(422, 'Unknown configured reviewer')
        return assign(db, sample_id, identities['current'], body.reviewer_id, body.revision)

    @app.post('/api/internal/reviews/{sample_id}/issues')
    def issue(sample_id: str, body: IssueInput, request: Request):
        from .review_issues import add_issue
        try:
            return add_issue(db, sample_id, body.issue, body.evidence_refs, reviewer_identity(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post('/api/internal/reviews/refresh-issues')
    def refresh_issues(request: Request):
        from .review_issues import refresh_disagreements
        reviewer_identity(request)
        return refresh_disagreements(db)

    return worker
