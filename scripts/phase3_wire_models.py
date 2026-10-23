"""Apply additive Phase-3 model wiring without changing existing table identities."""
from pathlib import Path

path = Path('backend/app/db.py')
source = path.read_text(encoding='utf-8')
source = source.replace('state_audit, feedback\n', 'state_audit, feedback, evaluation_store\n')
source = source.replace('        feedback.migrate_feedback(self)\n', '        feedback.migrate_feedback(self)\n        evaluation_store.migrate_evaluation(self)\n') if 'evaluation_store.migrate_evaluation' not in source else source
path.write_text(source, encoding='utf-8')
path = Path('backend/app/feedback.py')
source = path.read_text(encoding='utf-8')
if 'workflow: Mapped' not in source:
    source = source.replace("    __tablename__ = 'review_samples'\n", "    __tablename__ = 'review_samples'\n    workflow: Mapped[dict] = mapped_column(JSON, default=dict)\n")
    source = source.replace("    __tablename__ = 'review_annotations'\n", "    __tablename__ = 'review_annotations'\n    annotation_data: Mapped[dict] = mapped_column(JSON, default=dict)\n")
path.write_text(source, encoding='utf-8')
