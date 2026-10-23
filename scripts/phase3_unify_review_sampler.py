"""Route legacy acquisition through the extended policy and keep existing table identities."""
from pathlib import Path
p = Path('backend/app/feedback.py')
s = p.read_text(encoding='utf-8')
start = s.index('def select_review_samples(')
end = s.index('\ndef reviewer_identity(', start)
s = s[:start] + '''def select_review_samples(db, owner_session, data: SamplingInput):
    from .review_workflow import acquire_batch
    with db.session() as session:
        existing = list(session.scalars(select(ReviewSample).where(ReviewSample.request_id == data.request_id).order_by(ReviewSample.created_at).limit(data.limit)))
    if len(existing) < data.limit:
        acquire_batch(db, [data.request_id], batch_size=data.limit-len(existing), owner_session=owner_session)
    with db.session() as session:
        rows = list(session.scalars(select(ReviewSample).where(ReviewSample.request_id == data.request_id).order_by(ReviewSample.created_at).limit(data.limit)))
        output = [{'sample_id': row.sample_id, 'candidate_id': row.candidate_id, 'status': row.status, 'reasons': row.reasons} for row in rows]
    for row in output:
        record_system_event(db, owner_session, data.request_id, 'active_learning_sample_selected', suffix=row['sample_id'])
    return {'samples': output, 'sampler_version': rows[0].sampler_version if rows else SAMPLER_VERSION,
        'uncertainty': 'unavailable_without_a_calibrated_model', 'capacity_remaining': max(0, int(os.getenv('REVIEW_QUEUE_MAX', '100')) - len(rows))}

''' + s[end:]
p.write_text(s, encoding='utf-8')
p = Path('backend/app/review_workflow.py')
s = p.read_text(encoding='utf-8').replace('def acquire_batch(db, request_ids, seed=17, batch_size=20):', "def acquire_batch(db, request_ids, seed=17, batch_size=20, owner_session='internal_acquisition'):")
s = s.replace("owner_session='internal_acquisition', candidate_id=pid", "owner_session=owner_session, candidate_id=pid")
s = s.replace("propensity=probability, evidence=evidence", "propensity=None, evidence=evidence")
s = s.replace("'confirmed_state': frozen['confirmed_state'], 'search_mode'", "'uncertainty': 'unavailable_without_a_calibrated_model', 'confirmed_state': frozen['confirmed_state'], 'search_mode'")
s = s.replace("'ranking_scope': frozen['ranking_scope'], 'retrieval': {'status': 'frozen_reference', 'analysis_hash': frozen['analysis_hash']}", "'ranking_scope': frozen['ranking_scope'], 'retrieval': frozen.get('retrieval') or {},\n                'actual_rank': next((i+1 for i, r in enumerate(frozen['original_ranking']) if r['property_id'] == pid), None),\n                'utility_components': next((r['factors'] for r in frozen['original_ranking'] if r['property_id'] == pid), {}),\n                'original_explanations': frozen.get('explanations', [])")
s = s.replace("    if not initial:\n        for key", "    if not initial:\n        for key in ('actual_rank', 'utility_components', 'original_explanations'):\n            evidence.pop(key, None)\n        for key")
p.write_text(s, encoding='utf-8')
