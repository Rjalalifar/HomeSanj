"""Task-level rejection must not manufacture per-property relevance labels."""
from backend.app.db import Database
from backend.app.feedback import FeedbackInput, touch_measurement, submit_feedback, measurement_metrics
from tests.test_feedback import request_fixture


def test_none_suitable_does_not_label_every_frozen_candidate(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "policy.sqlite"}')
    db.migrate()
    rid = request_fixture(db)
    measurement = touch_measurement(db, rid, 'owner')
    submit_feedback(db, 'owner', FeedbackInput(idempotency_key='none-suitable-policy', request_id=rid,
        kind='top5', label='negative', candidate_ids=[]))
    result = measurement_metrics(db, measurement)
    assert result['success_at_5'] is False
    assert result['judged_count'] == 0 and result['unjudged_count'] == 3
    assert result['precision_at_5'] is None and result['ndcg_at_5'] is None
