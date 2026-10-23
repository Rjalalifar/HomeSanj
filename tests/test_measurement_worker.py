from datetime import datetime, timedelta, timezone

from backend.app.db import Database
from backend.app.feedback import Measurement, migrate_feedback, touch_measurement
from backend.app.measurement_worker import sweep_due_measurements
from tests.test_feedback import request_fixture


def test_expired_partial_search_is_frozen_without_client_poll(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "deadline.sqlite3"}')
    db.migrate()
    request_fixture(db, status='partial')
    measurement = touch_measurement(db, 'req_first', 'owner')
    assert measurement.freeze_at is None
    with db.session.begin() as session:
        row = session.get(Measurement, measurement.measurement_id)
        row.deadline = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert sweep_due_measurements(db)['processed'] == 1
    with db.session() as session:
        row = session.get(Measurement, measurement.measurement_id)
        assert row.freeze_at is not None
        assert row.completion_status == 'deadline_no_result'
        assert row.top_k_snapshot == []
    assert sweep_due_measurements(db)['processed'] == 0
