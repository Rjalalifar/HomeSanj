import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.contracts import SearchState
from backend.app.db import Candidate, Database, Evaluation, SearchRequest, Task, utcnow
from backend.app.explanations import explain, render_claim, TypedClaim
from backend.app.feedback import (
    AnnotationInput, EventInput, FeedbackInput, Measurement, ReviewAnnotation, ReviewSample,
    SamplingInput, SearchEvent, confirm_annotation, measurement_payload, migrate_feedback,
    record_event, select_review_samples, submit_feedback, suggest_annotation,
    touch_measurement, train_offline,
)


@pytest.fixture
def db(tmp_path):
    database = Database(f'sqlite:///{tmp_path / "feedback.sqlite3"}')
    database.migrate()
    migrate_feedback(database)
    return database


def request_fixture(db, request_id='req_first', task_id='task_first', *, synthetic=True, routing=False, status='complete', created_at=None):
    created_at = created_at or utcnow()
    state = SearchState(dataset_version='test').model_dump(mode='json')
    if routing:
        state['travel'].update(destination={'latitude': 35.7, 'longitude': 51.4, 'confirmed': True, 'label': 'Private work'},
            date='2026-10-20', time='08:00:00')
    with db.session.begin() as session:
        if not session.get(Task, task_id):
            session.add(Task(task_id=task_id, destination=state['travel']['destination'], created_at=created_at))
        session.add(SearchRequest(request_id=request_id, task_id=task_id, parent_request_id=None,
            snapshot_id='snap_' + request_id, state=state, versions={'dataset': 'test'},
            candidate_count=3, evaluated_count=0, completion_status=status,
            subset_method='test_order', batch_limit=3, warnings=[], created_at=created_at))
        for index in range(3):
            pid = f'p{index + 1}'
            session.add(Candidate(request_id=request_id, property_id=pid, ordinal=index,
                property_snapshot={'property_id': pid, 'monthly_rent_toman': (index + 1) * 10000000,
                    'deposit_toman': 100000000, 'area_m2': 60 + index, 'bedrooms': 2,
                    'parking': index == 0, 'elevator': None, 'is_synthetic': synthetic,
                    'neighborhood_id': f'n{index}', 'title_fa': 'A listing'},
                property_verdicts=[]))
    return request_id


def feedback(request_id='req_first', **kwargs):
    values = {'idempotency_key': 'key-feedback-1', 'request_id': request_id, 'kind': 'property',
              'label': 'positive', 'candidate_ids': ['p1']}
    return FeedbackInput(**(values | kwargs))


def test_first_final_top_five_is_immutable_after_filter_change(db):
    first = request_fixture(db)
    frozen = touch_measurement(db, first, 'owner')
    before = frozen.top_k_snapshot
    request_fixture(db, 'req_second')
    with db.session.begin() as session:
        candidate = session.get(Candidate, ('req_second', 'p1'))
        candidate.property_snapshot = candidate.property_snapshot | {'monthly_rent_toman': 99999999}
    second = touch_measurement(db, 'req_second', 'owner')
    assert second.measurement_id == frozen.measurement_id
    assert second.evaluation_request_id == first
    assert second.top_k_snapshot == before
    assert second.top_k_snapshot[0]['property_id'] == 'p1'
    with pytest.raises(HTTPException) as error:
        submit_feedback(db, 'owner', feedback('req_second', kind='top5'))
    assert error.value.status_code == 409


def test_deadline_freezes_only_actually_exposed_eligible_rows(db, monkeypatch):
    monkeypatch.setenv('MEASUREMENT_DEADLINE_SECONDS', '120')
    rid = request_fixture(db, status='partial')
    pending = touch_measurement(db, rid, 'owner')
    assert pending.freeze_at is None and not pending.top_k_snapshot
    record_event(db, 'owner', EventInput(event_id='event-render-1', event_type='result_rendered',
                                      request_id=rid, candidate_id='p2'))
    after = datetime.fromisoformat(pending.deadline) + timedelta(seconds=1)
    frozen = touch_measurement(db, rid, 'owner', now=after)
    assert frozen.completion_status == 'deadline_partial'
    assert [row['property_id'] for row in frozen.top_k_snapshot] == ['p2']
    assert frozen.exposed_candidate_ids == ['p2']


def test_no_route_cannot_become_a_qualifying_feedback_target(db):
    rid = request_fixture(db, routing=True, status='routing_unavailable')
    with pytest.raises(HTTPException) as error:
        submit_feedback(db, 'owner', feedback(rid))
    assert error.value.status_code == 422
    result = asyncio.run(explain(db, rid))
    assert result['recommended_property_id'] is None
    assert not result['recommendations']


def test_events_are_idempotent_owned_and_not_relevance(db):
    rid = request_fixture(db)
    data = EventInput(event_id='click-event-1', event_type='result_clicked', request_id=rid, candidate_id='p1')
    assert record_event(db, 'owner', data)['status'] == 'recorded'
    assert record_event(db, 'owner', data)['status'] == 'duplicate'
    with pytest.raises(HTTPException) as error:
        record_event(db, 'other', data)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        record_event(db, 'owner', data.model_copy(update={'candidate_id': 'p2'}))
    assert error.value.status_code == 409
    metrics = measurement_payload(db, touch_measurement(db, rid, 'owner'))['metrics']
    assert metrics['success_at_5'] is None and metrics['judged_count'] == 0
    with db.session() as session:
        event = session.get(SearchEvent, data.event_id)
        assert 'destination' not in json.dumps(event.payload)
        assert event.actor_kind == 'demo'


def test_impressions_have_visibility_policy_and_semantic_deduplication(db):
    rid = request_fixture(db)
    event = EventInput(event_id='impression-1', event_type='result_impression', request_id=rid, candidate_id='p1',
                      visible_fraction=.49, visible_ms=1000)
    with pytest.raises(HTTPException):
        record_event(db, 'owner', event)
    good = event.model_copy(update={'visible_fraction': .5})
    assert record_event(db, 'owner', good)['status'] == 'recorded'
    assert record_event(db, 'owner', good.model_copy(update={'event_id': 'impression-2'}))['status'] == 'duplicate'
    with pytest.raises(HTTPException):
        record_event(db, 'owner', EventInput(event_id='server-forge-1', request_id=rid, event_type='search_completed'))
    with pytest.raises(HTTPException):
        record_event(db, 'owner', EventInput(event_id='source-missing-1', request_id=rid, event_type='sort_changed'))


def test_explicit_positive_top_five_identifies_a_frozen_candidate(db):
    rid = request_fixture(db, synthetic=False)
    frozen = touch_measurement(db, rid, 'owner')
    with pytest.raises(HTTPException):
        submit_feedback(db, 'owner', feedback(kind='top5', candidate_ids=[]))
    with pytest.raises(HTTPException):
        submit_feedback(db, 'owner', feedback(kind='top5', candidate_ids=['missing']))
    result = submit_feedback(db, 'owner', feedback(kind='top5', candidate_ids=['p2']))
    assert result['is_ground_truth']
    metrics = measurement_payload(db, frozen)['metrics']
    assert metrics['success_at_5'] is True
    assert metrics['unjudged_count'] == 2
    assert metrics['precision_at_5'] is None and metrics['ndcg_at_5'] is None


def test_rejecting_one_home_does_not_label_other_homes(db):
    rid = request_fixture(db, synthetic=False)
    submit_feedback(db, 'owner', feedback(label='negative'))
    metrics = measurement_payload(db, touch_measurement(db, rid, 'owner'))['metrics']
    assert metrics['judged_count'] == 1 and metrics['unjudged_count'] == 2
    assert metrics['success_at_5'] is None
    submit_feedback(db, 'owner', feedback(idempotency_key='none-suitable-1', kind='top5', label='negative', candidate_ids=[]))
    metrics = measurement_payload(db, touch_measurement(db, rid, 'owner'))['metrics']
    assert metrics['success_at_5'] is False and metrics['precision_at_5'] is None
    assert metrics['unjudged_count'] == 2


def test_feedback_idempotency_and_demo_separation(db):
    rid = request_fixture(db)
    first = submit_feedback(db, 'owner', feedback())
    assert first['actor_kind'] == 'demo' and not first['is_ground_truth']
    assert submit_feedback(db, 'owner', feedback())['status'] == 'duplicate'
    with pytest.raises(HTTPException) as error:
        submit_feedback(db, 'owner', feedback(label='negative'))
    assert error.value.status_code == 409
    metrics = measurement_payload(db, touch_measurement(db, rid, 'owner'))['metrics']
    assert not metrics['eligible_for_real_user_metrics']


class FakeProvider:
    models = {'explainer': 'test-model', 'judge': 'test-model'}

    def __init__(self, value):
        self.value = value
        self.calls = []

    async def complete(self, role, messages):
        self.calls.append((role, messages))
        return self.value


def test_optional_explanation_rejects_foreign_property_and_false_comparison(db, monkeypatch):
    monkeypatch.setenv('ADVANCED_AI_ENABLED', 'true')
    rid = request_fixture(db)
    provider = FakeProvider(json.dumps({'recommended_property_id': 'p1', 'claims': [
        {'property_id': 'p1', 'field': 'monthly_rent_toman', 'operator': 'less_than', 'other_property_id': 'missing'}]}))
    response = asyncio.run(explain(db, rid, provider, True))
    assert response['mode'] == 'deterministic_fallback' and response['ai_status'] == 'validation_error'
    provider.value = json.dumps({'recommended_property_id': 'p1', 'claims': [
        {'property_id': 'p1', 'field': 'monthly_rent_toman', 'operator': 'greater_than', 'other_property_id': 'p2'}]})
    response = asyncio.run(explain(db, rid, provider, True))
    assert response['mode'] == 'deterministic_fallback'
    provider.value = json.dumps({'recommended_property_id': 'p1', 'claims': [
        {'property_id': 'p1', 'field': 'monthly_rent_toman', 'operator': 'less_than', 'other_property_id': 'p2'}]})
    response = asyncio.run(explain(db, rid, provider, True))
    assert response['mode'] == 'ai_selected_verified_templates'
    assert len(response['ai_selected_claims'][0]['evidence_refs']) == 2


def test_default_explanation_never_calls_model_and_model_cannot_override_rank(db, monkeypatch):
    monkeypatch.setenv('ADVANCED_AI_ENABLED', 'true')
    rid = request_fixture(db)
    provider = FakeProvider('{"recommended_property_id":"p3","claims":[]}')
    response = asyncio.run(explain(db, rid, provider, False))
    assert response['recommended_property_id'] == 'p1' and not provider.calls
    response = asyncio.run(explain(db, rid, provider, True))
    assert response['mode'] == 'deterministic_fallback'
    assert response['recommended_property_id'] == 'p1'
    assert 'Private work' not in json.dumps(provider.calls)


def test_existing_reference_does_not_authorize_unchecked_factual_prose():
    facts = {'property:p1:parking': {'value': None}}
    with pytest.raises(ValueError):
        render_claim(TypedClaim(property_id='p1', field='parking', operator='known'), facts, {'p1'})
    with pytest.raises(ValueError):
        TypedClaim.model_validate({'property_id': 'p1', 'field': 'parking', 'operator': 'unknown',
                                  'text': 'This is a safe quiet neighborhood'})


def test_review_sampling_is_bounded_and_ai_label_never_becomes_gold(db, tmp_path):
    rid = request_fixture(db)
    selected = select_review_samples(db, 'owner', SamplingInput(request_id=rid, limit=2))
    assert len(selected['samples']) == 2
    sample_id = selected['samples'][0]['sample_id']
    with db.session() as session:
        sample = session.get(ReviewSample, sample_id)
        assert sample.propensity is None
        assert sample.evidence['uncertainty'] == 'unavailable_without_a_calibrated_model'
        pid = sample.candidate_id
    provider = FakeProvider(json.dumps({'candidate_id': pid, 'suggested_label': 'positive',
        'reason': 'budget', 'evidence_refs': [f'property:{pid}:monthly_rent_toman'],
        'uncertainty': 'unknown', 'needs_human_review': True}))
    suggestion = asyncio.run(suggest_annotation(db, sample_id, 'reviewer_test', provider))
    assert suggestion['status'] == 'suggested_only'
    with db.session() as session:
        assert session.get(ReviewSample, sample_id).status == 'pending'
        annotation = session.get(ReviewAnnotation, suggestion['annotation_id'])
        assert annotation.needs_human_review and annotation.annotation_kind == 'ai_suggested'
    human = confirm_annotation(db, sample_id, 'reviewer_test',
        AnnotationInput(idempotency_key='confirm-human-1', label='positive'))
    assert human['demo_excluded_from_training']
    report = train_offline(db, tmp_path / 'report.json')
    assert report['status'] == 'insufficient_data'
    assert report['confirmed_independent_labels'] == 0
    assert report['activation'] == 'deterministic_baseline_retained'


def test_review_invalid_evidence_is_rejected(db):
    rid = request_fixture(db)
    sample_id = select_review_samples(db, 'owner', SamplingInput(request_id=rid, limit=1))['samples'][0]['sample_id']
    with pytest.raises(HTTPException) as error:
        confirm_annotation(db, sample_id, 'reviewer_test', AnnotationInput(
            idempotency_key='bad-reference-1', label='positive', evidence_refs=['property:foreign:parking']))
    assert error.value.status_code == 422


def test_training_requires_independent_real_human_labels(db, tmp_path):
    rid = request_fixture(db, synthetic=False)
    sample_id = select_review_samples(db, 'owner', SamplingInput(request_id=rid, limit=1))['samples'][0]['sample_id']
    confirm_annotation(db, sample_id, 'reviewer_test', AnnotationInput(idempotency_key='real-human-1', label='negative'))
    report = train_offline(db, tmp_path / 'report.json')
    assert report['confirmed_independent_labels'] == 1
    assert report['independent_groups'] == 1
    assert report['status'] == 'insufficient_data'
