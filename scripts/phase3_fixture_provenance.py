"""Mark automated browser annotations as fixtures, never independent human reviews."""
from pathlib import Path
p = Path('backend/app/review_workflow.py')
s = p.read_text(encoding='utf-8')
s = s.replace("        metadata = {'type': data.annotation_type, 'grade': data.grade, 'origin': 'human',", "        fixture_review = os.getenv('REVIEW_ANNOTATION_SOURCE') == 'automated_test'\n        metadata = {'type': data.annotation_type, 'grade': data.grade, 'origin': 'test_fixture' if fixture_review else 'human',")
s = s.replace("'review_status': 'independent_human', 'blind_initial'", "'review_status': 'automated_fixture' if fixture_review else 'independent_human', 'blind_initial'")
s = s.replace("content_hash=hashed, annotation_kind='human_confirmed',", "content_hash=hashed, annotation_kind='fixture_reviewed' if fixture_review else 'human_confirmed',")
p.write_text(s, encoding='utf-8')
p = Path('scripts/serve_phase3_browser.py')
s = p.read_text(encoding='utf-8').replace("os.environ['REVIEW_API_TOKEN'] = token", "os.environ['REVIEW_API_TOKEN'] = token\nos.environ['REVIEW_ANNOTATION_SOURCE'] = 'automated_test'")
s = s.replace("settings, False, catalog=catalog)", "settings, False, versions={'inventory': catalog.version, 'boundary_assignments': catalog.boundary_version}, catalog=catalog)")
p.write_text(s, encoding='utf-8')
