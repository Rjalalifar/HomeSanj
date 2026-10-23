"""Expose explicit internal controls without bypassing evidence or identity checks."""
from pathlib import Path
p = Path('backend/app/phase3_api.py')
s = p.read_text(encoding='utf-8')
pos = s.index('\ndef install_phase3(')
classes = '''

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
'''
if 'class ApprovalInput' not in s:
    s = s[:pos] + classes + s[pos:]
routes = '''
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
        return {'job_id': enqueue(db, 'pairwise', body.model_dump())}

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

'''
if "@app.post('/api/internal/approvals')" not in s:
    s = s.replace('    return worker\n', routes + '    return worker\n')
p.write_text(s, encoding='utf-8')
p = Path('backend/app/feedback.py')
s = p.read_text(encoding='utf-8')
old = "    configured = os.getenv('REVIEW_API_TOKEN', '')\n    supplied = request.headers.get('x-review-token', '')"
new = """    configured = os.getenv('REVIEW_API_TOKEN', '')
    supplied = request.headers.get('x-review-token', '')
    try:
        reviewers = json.loads(os.getenv('REVIEWER_TOKENS_JSON', '{}'))
    except ValueError:
        reviewers = {}
    for identity, token in reviewers.items():
        if isinstance(token, str) and len(token) >= 16 and supplied and secrets.compare_digest(supplied, token):
            return 'reviewer_' + hashlib.sha256(identity.encode()).hexdigest()[:16]"""
if 'REVIEWER_TOKENS_JSON' not in s:
    s = s.replace(old, new)
p.write_text(s, encoding='utf-8')
p = Path('backend/app/review_workflow.py')
s = p.read_text(encoding='utf-8')
s = s.replace("a.annotation_data.get('type') == 'relevance_grade' for a in annotations", "a.annotation_data.get('type') == 'relevance_grade' and a.annotation_data.get('action') == 'annotate' for a in annotations")
s = s.replace("'blind_initial': not any(a.reviewer_id == reviewer for a in existing)", "'blind_initial': not any(a.reviewer_id == reviewer and a.annotation_kind == 'human_confirmed' and a.annotation_data.get('type') == 'relevance_grade' and a.annotation_data.get('action') == 'annotate' for a in existing)")
p.write_text(s, encoding='utf-8')
