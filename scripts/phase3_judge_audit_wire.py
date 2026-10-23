"""Connect optional grounding and reproducible audit selection to durable jobs."""
from pathlib import Path
p = Path('backend/app/offline_evaluation.py')
s = p.read_text(encoding='utf-8').replace("('judge', 'pairwise', 'improvement', 'acquisition', 'export')", "('judge', 'grounding', 'pairwise', 'improvement', 'acquisition', 'export')")
s = s.replace("            elif job.kind == 'pairwise':", "            elif job.kind == 'grounding':\n                from .judge_grounding import audit_explanation\n                result = await audit_explanation(self.db, job.payload['cache_key'], self.provider)\n            elif job.kind == 'pairwise':")
s = s.replace("                result = await asyncio.to_thread(acquire_batch, self.db, **job.payload)", "                result = await asyncio.to_thread(acquire_batch, self.db, **job.payload)\n                rate = max(0, min(1, float(os.getenv('JUDGE_SAMPLE_RATE', '0.10'))))\n                audits = []\n                if self.provider.role_enabled('judge'):\n                    with self.db.session() as session:\n                        samples = [session.get(ReviewSample, sid) for sid in result['sample_ids']]\n                    for sample in samples:\n                        draw = int(digest({'sample_id': sample.sample_id, 'policy': 'judge-audit-1'})[:8], 16) / 0xffffffff\n                        if 'critical' in sample.reasons or draw < rate:\n                            audits.append(enqueue_judge(self.db, sample.sample_id, self.provider))\n                result['judge_audit'] = {'job_ids': audits, 'random_rate': rate, 'policy': 'judge-audit-1', 'enabled': self.provider.role_enabled('judge')}")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/phase3_api.py')
s = p.read_text(encoding='utf-8')
route = '''    @app.post('/api/internal/explanations/{cache_key}/judge')
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

'''
if "@app.post('/api/internal/explanations/" not in s:
    s = s.replace('    return worker\n', route + '    return worker\n')
p.write_text(s, encoding='utf-8')
