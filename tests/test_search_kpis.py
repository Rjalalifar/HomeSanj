"""Primary cards reuse frozen evidence without inventing missing observations."""
from copy import deepcopy
from types import SimpleNamespace as Row

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.routing import OTPAdapter, OTPSettings
from tests.test_phase2_core import setup


def test_internal_dashboard_has_exactly_six_unavailable_primary_metrics(setup, monkeypatch):
    db, geo, _ = setup
    monkeypatch.setenv('REVIEW_API_TOKEN', 'internal-kpi-test-token')
    app = create_app(Settings(), database=db, geo=geo, adapter=OTPAdapter(OTPSettings()), start_worker=False)
    with TestClient(app) as client:
        assert client.get('/api/internal/dashboard').status_code == 403
        report = client.get('/api/internal/dashboard', headers={'x-review-token': 'internal-kpi-test-token'}).json()
    assert 'primary_kpis' in report
    assert set(report['primary_kpis']['normal']) == {'qs_at_5', 'human_ndcg_at_5', 'finalized_search_p95_ms'}
    assert set(report['primary_kpis']['advanced']) == {'qs_at_5', 'human_ndcg_at_5', 'gemini_groundedness'}
    for mode, metrics in report['primary_kpis'].items():
        for metric in metrics.values():
            assert metric['status'] == 'insufficient_data' and metric['value'] is None
            assert metric['source_mode'] == mode and metric['reason']
            assert metric['sample_size'] == 0 and metric['coverage']['value'] is None
            assert {'period', 'policy_version', 'cohort'} <= metric.keys()
    assert {'otp', 'retrieval', 'providers', 'stage_latency', 'grounding', 'qs', 'review'} <= report.keys()


def aggregate(**kwargs):
    from backend.app.search_kpis import primary_kpis
    defaults = dict(measurements=[], feedback=[], events=[], requests={}, analyses={}, explanations=[],
                    experiments=[], annotations=[], manifests={})
    return primary_kpis(**(defaults | kwargs))


def test_empty_historical_demo_freeze_is_not_a_real_user_failure(setup, monkeypatch):
    from sqlalchemy import select
    from backend.app.feedback import Measurement
    db, geo, _ = setup
    monkeypatch.setenv('REVIEW_API_TOKEN', 'internal-kpi-test-token')
    app = create_app(Settings(), database=db, geo=geo, adapter=OTPAdapter(OTPSettings()), start_worker=False)
    with TestClient(app) as client:
        state = client.get('/api/state/default').json()
        state['accessibility'] = None
        assert client.post('/api/searches', json={'state': state}).status_code == 201
        with db.session.begin() as session:
            m = session.scalar(select(Measurement))
            m.actor_kind = 'real_user'
            m.top_k_snapshot = []
            m.freeze_at = '2026-01-01T00:00:00+00:00'
        report = client.get('/api/internal/dashboard', headers={'x-review-token': 'internal-kpi-test-token'}).json()
        assert report['primary_kpis']['normal']['qs_at_5']['value'] is None
        assert report['real_qs_status'] == 'unavailable'
        with db.session() as session:
            assert session.scalar(select(Measurement)).actor_kind == 'real_user'


def request(rid='normal', mode='normal'):
    return Row(request_id=rid, snapshot_id='snapshot-' + rid, state={'accessibility': {'enabled': True},
               'travel': {'destination': None}}, created_at='2026-01-01T00:00:00+00:00', completion_status='complete')


def measurement(rid='normal', actor='real_user'):
    return Row(measurement_id='measure-' + rid, task_id='task-' + rid, owner_session='owner',
        evaluation_request_id=rid, snapshot_id='snapshot-' + rid, search_mode=rid, actor_kind=actor,
        freeze_at='2026-01-01T00:00:01+00:00', created_at='2026-01-01T00:00:00+00:00',
        completion_status='final', top_k_snapshot=[{'property_id': 'p', 'property': {'is_synthetic': False},
            'property_verdicts': [{'verdict': 'pass'}], 'travel_verdicts': []}])


def feedback(m, **changes):
    return Row(**(dict(measurement_id=m.measurement_id, task_id=m.task_id, request_id=m.evaluation_request_id,
        snapshot_id=m.snapshot_id, owner_session=m.owner_session, actor_kind=m.actor_kind,
        created_at='2026-01-01T00:01:00+00:00', kind='top5', label='positive', candidate_ids=['p']) | changes))


def test_qs_separates_modes_real_feedback_unknown_pending_and_snapshot_identity():
    normal, advanced = measurement(), measurement('advanced')
    unknown, pending, demo = measurement('unknown'), measurement('pending'), measurement('demo', 'demo')
    unknown.top_k_snapshot[0]['property_verdicts'] = [{'verdict': 'unknown'}]
    pending.freeze_at = pending.created_at = '2999-01-01T00:00:00+00:00'
    ms = [normal, advanced, unknown, pending, demo]
    result = aggregate(measurements=ms, feedback=[feedback(normal), feedback(advanced, label='negative', candidate_ids=[]),
        feedback(unknown), feedback(pending), feedback(demo)],
        requests={m.evaluation_request_id: request(m.evaluation_request_id) for m in ms},
        analyses={m.evaluation_request_id: Row(search_mode='advanced' if m is advanced else 'normal') for m in ms})
    normal_kpi, advanced_kpi = result['normal']['qs_at_5'], result['advanced']['qs_at_5']
    assert normal_kpi['value'] == 1 and normal_kpi['sample_size'] == 1
    assert normal_kpi['counts'] == {'N': 2, 'S': 1, 'F': 0, 'U': 1, 'pending': 1}
    assert normal_kpi['coverage']['value'] == .5
    assert advanced_kpi['value'] == 0 and advanced_kpi['sample_size'] == 1
    invalid = aggregate(measurements=[normal], requests={'normal': request()},
        analyses={'normal': Row(search_mode='normal')}, feedback=[feedback(normal, snapshot_id='different'),
        feedback(normal, actor_kind='reviewer'), feedback(normal, request_id='different')])
    assert invalid['normal']['qs_at_5']['value'] is None
    ambiguous = aggregate(measurements=[normal], requests={'normal': request()}, feedback=[feedback(normal)])
    assert ambiguous['normal']['qs_at_5']['sample_size'] == 0
    normal.completion_status = 'deadline_partial'
    partial = aggregate(measurements=[normal], requests={'normal': request()},
        analyses={'normal': Row(search_mode='normal')}, feedback=[feedback(normal)])
    assert partial['normal']['qs_at_5']['value'] is None


def test_latency_does_not_substitute_first_paint_or_post_filter_submission():
    events = [Row(request_id='normal', event_type=kind, timestamp='2026-01-01T00:00:01+00:00',
                  payload={'duration_ms': 5}) for kind in ('search_submitted', 'result_rendered', 'search_completed')]
    result = aggregate(requests={'normal': request()}, analyses={'normal': Row(search_mode='normal')}, events=events)
    metric = result['normal']['finalized_search_p95_ms']
    assert metric['value'] is None and 'instrumentation' in metric['reason']


def test_grounding_counts_only_verifiable_gemini_selected_claims():
    from backend.app.explanations import TypedClaim, render_claim
    facts = {'property:p:monthly_rent_toman': {'value': 100, 'unit': 'toman', 'itinerary_id': None}}
    claim = render_claim(TypedClaim(property_id='p', field='monthly_rent_toman', operator='known'), facts, {'p'})
    bad = deepcopy(claim)
    bad['text'] = 'Wrong amount'
    payload = {'mode': 'ai_selected_verified_templates', 'ai_status': 'ok', 'model_version': 'gemini-3.6-flash',
        'schema_version': 'typed-comparisons-1', 'evidence': facts, 'ai_selected_claims': [claim, bad, {'text': 'Nice home'}],
        'recommendations': [{'strengths': [claim] * 20}]}
    explanations = [Row(request_id='advanced', payload=payload, created_at='2026-01-01T00:00:00+00:00'),
        Row(request_id='advanced', payload=payload | {'mode': 'deterministic_fallback'}, created_at='2026-01-01T00:00:00+00:00'),
        Row(request_id='normal', payload=payload, created_at='2026-01-01T00:00:00+00:00')]
    result = aggregate(explanations=explanations, requests={'advanced': request('advanced')},
        analyses={'advanced': Row(search_mode='advanced'), 'normal': Row(search_mode='normal')})
    metric = result['advanced']['gemini_groundedness']
    assert metric['value'] == .5 and metric['sample_size'] == 2
    assert metric['coverage']['numerator'] == 2 and metric['coverage']['denominator'] == 3


def test_ndcg_reuses_versioned_human_pools_excludes_missing_and_deduplicates():
    from backend.app.evaluation_metrics import ranking_metrics, METRIC_VERSION
    from backend.app.evaluation_replay import digest
    labels = {'p': {'grade': 3, 'hard': 'pass', 'origin': 'human', 'annotation_ids': ['a']},
              'q': {'grade': 1, 'hard': 'pass', 'origin': 'human', 'annotation_ids': ['b']}}
    case = {'manifest_id': 'manifest', 'mode': 'normal', 'status': 'ok', 'label_origin': 'human',
        'frozen_labels': labels, 'labels_hash': digest(labels), 'inventory_hash': 'inventory',
        'baseline_ids': ['q', 'p'], 'metrics': {'baseline': ranking_metrics(['q', 'p'], labels)}}
    record = Row(created_at='2026-01-01T00:00:00+00:00', report={'metric_version': METRIC_VERSION,
        'label_dataset_id': 'labels-v1', 'label_dataset_sha256': 'hash', 'split': 'validation', 'cases': [case]})
    annotations = [Row(annotation_id=aid, annotation_kind='human_confirmed', needs_human_review=False,
        annotation_data={'origin': 'human', 'type': 'relevance_grade', 'action': 'annotate', 'grade': grade})
        for aid, grade in [('a', 3), ('b', 1)]]
    kwargs = dict(experiments=[record, record], annotations=annotations,
        manifests={'manifest': Row(request_id='normal')}, requests={'normal': request()},
        analyses={'normal': Row(search_mode='normal')})
    metric = aggregate(**kwargs)['normal']['human_ndcg_at_5']
    assert metric['value'] == case['metrics']['baseline']['ndcg_at_5']['value']
    assert metric['sample_size'] == 1 and metric['policy_version'] == METRIC_VERSION
    labels['q']['grade'] = None
    assert aggregate(**kwargs)['normal']['human_ndcg_at_5']['value'] is None
    labels['q']['grade'] = 1
    annotations[0].annotation_data['origin'] = 'test_fixture'
    assert aggregate(**kwargs)['normal']['human_ndcg_at_5']['value'] is None
