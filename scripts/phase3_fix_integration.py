"""Close replay, legacy review and dataset job integration gaps."""
from pathlib import Path
p = Path('backend/app/evaluation.py')
s = p.read_text(encoding='utf-8').replace("source = path.read_text(encoding='utf-8')", "source = path.read_text(encoding='utf-8-sig')")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/feedback.py')
s = p.read_text(encoding='utf-8')
start = s.index("    @app.get('/api/review/queue')")
end = s.index("    @app.post('/api/review/{sample_id}/annotation')", start)
s = s[:start] + """    @app.get('/api/review/queue')
    def queue(request: Request, limit: int = 20):
        from .review_workflow import list_samples
        return {'samples': list_samples(db, reviewer_identity(request), limit=max(1, min(100, limit)))}

""" + s[end:]
old = "        return await suggest_annotation(db, sample_id, reviewer_identity(request), provider)"
new = """        reviewer = reviewer_identity(request)
        with db.session() as session:
            prior = session.scalar(select(ReviewAnnotation).where(ReviewAnnotation.sample_id == sample_id,
                ReviewAnnotation.reviewer_id == reviewer, ReviewAnnotation.annotation_kind == 'human_confirmed'))
        if prior is None:
            raise HTTPException(409, 'Record an independent initial review before viewing AI suggestions')
        return await suggest_annotation(db, sample_id, reviewer, provider)"""
s = s.replace(old, new)
p.write_text(s, encoding='utf-8')
p = Path('backend/app/phase3_api.py')
s = p.read_text(encoding='utf-8')
s = s.replace("return {'job_id': enqueue(db, 'export', {})}", "from .feedback import ReviewAnnotation\n        from .evaluation_replay import digest\n        with db.session() as session:\n            identity = digest(sorted(session.scalars(select(ReviewAnnotation.annotation_id))))\n        return {'job_id': enqueue(db, 'export', {'annotation_revision': identity})}")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/offline_evaluation.py')
s = p.read_text(encoding='utf-8')
s = s.replace("            job = session.scalar(select(OfflineJob).where", "            exhausted = session.scalars(select(OfflineJob).where(OfflineJob.status == 'running', OfflineJob.lease_until <= now, OfflineJob.attempts >= 3))\n            for expired in exhausted:\n                expired.status, expired.result = 'failed', {'status': 'error', 'reason': 'lease_retries_exhausted'}\n                expired.lease_owner = None\n            session.flush()\n            job = session.scalar(select(OfflineJob).where")
s = s.replace("            if not job:\n                return None", "            if not job:\n                session.commit()\n                return None")
p.write_text(s, encoding='utf-8')
