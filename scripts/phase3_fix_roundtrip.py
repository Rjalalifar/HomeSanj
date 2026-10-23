"""Preserve portable dataset bytes and assert the intended sample identity."""
from pathlib import Path
p = Path('backend/app/annotation_datasets.py')
s = p.read_text(encoding='utf-8').replace("path.write_text(contents, encoding='utf-8')", "path.write_bytes(contents.encode('utf-8'))")
p.write_text(s, encoding='utf-8')
p = Path('tests/test_phase3_review.py')
s = p.read_text(encoding='utf-8').replace("list_samples(db, 'alice')[0]['initial_blind']", "next(s for s in list_samples(db, 'alice') if s['sample_id'] == sid)['initial_blind']").replace("list_samples(db, 'bob')[0]['initial_blind']", "next(s for s in list_samples(db, 'bob') if s['sample_id'] == sid)['initial_blind']")
p.write_text(s, encoding='utf-8')
