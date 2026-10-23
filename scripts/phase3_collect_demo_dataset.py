"""Export browser-generated fixture review evidence without promoting it to human gold."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.db import Database
from backend.app.annotation_datasets import export_dataset, import_dataset
from backend.app.evaluation import write_report
from backend.app.feedback import ReviewAnnotation
from sqlalchemy import select

configuration = json.loads(Path('runtime/phase3-browser-config.json').read_text(encoding='utf-8'))
db = Database('sqlite:///' + configuration['database'])
db.migrate()
with db.session() as session:
    records = list(session.scalars(select(ReviewAnnotation)))
    if any(r.annotation_kind == 'human_confirmed' for r in records):
        raise ValueError('Browser fixture must not be labeled independent human review')
result = export_dataset(db, 'data/evaluation/demo-review')
result['roundtrip'] = import_dataset(db, result['path'])
result['data_origin'] = 'automated_browser_review_of_synthetic_listings'
result['independent_human_review_count'] = 0
write_report('docs/phase-3-dataset-report.json', result)
print(json.dumps({'dataset_id': result['dataset_id'], 'count': result['count'], 'independent_human_review_count': 0}))
