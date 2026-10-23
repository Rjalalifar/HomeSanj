"""Bounded deadline processing, independent of a browser remaining open."""
from sqlalchemy import select

from .db import utcnow
from .feedback import Measurement, touch_measurement


def sweep_due_measurements(db, limit=20):
    with db.session() as session:
        due = list(session.scalars(select(Measurement).where(
            Measurement.freeze_at.is_(None), Measurement.deadline <= utcnow()
        ).order_by(Measurement.deadline).limit(max(1, min(100, limit)))))
    failures = []
    completed = 0
    for row in due:
        try:
            touch_measurement(db, row.evaluation_request_id, row.owner_session)
            completed += 1
        except Exception as exc:
            failures.append({'measurement_id': row.measurement_id, 'error_kind': type(exc).__name__})
    return {'processed': completed, 'failures': failures}
