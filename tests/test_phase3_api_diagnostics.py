"""Internal authentication and diagnostic evidence requirements."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.app.main import create_app
from backend.app.config import Settings
from backend.app.routing import OTPAdapter, OTPSettings
from backend.app.evaluation_store import ReplayManifest
from backend.app.evaluation_diagnostics import groundedness, state_accuracy, human_judge_agreement, percentiles
from tests.test_phase2_core import setup


def test_internal_api_is_restricted_and_delivery_captures_evidence(setup, monkeypatch):
    db, geo, _ = setup
    monkeypatch.setenv('REVIEW_API_TOKEN', 'internal-test-token-only')
    app = create_app(Settings(), database=db, geo=geo, adapter=OTPAdapter(OTPSettings()), start_worker=False)
    with TestClient(app) as client:
        assert client.get('/api/internal/dashboard').status_code == 403
        headers = {'x-review-token': 'internal-test-token-only'}
        report = client.get('/api/internal/dashboard', headers=headers)
        assert report.status_code == 200 and report.json()['real_qs_status'] == 'unavailable'
        state = client.get('/api/state/default').json()
        state['accessibility'] = None
        response = client.post('/api/searches', json={'state': state})
        assert response.status_code == 201
        with db.session() as session:
            manifests = list(session.scalars(select(ReplayManifest)))
            assert len(manifests) == 1 and manifests[0].payload['historical_original_ranking_verified']
        assert client.post('/api/internal/releases', json={'scope': 'production', 'experiment_id': 'missing'}, headers=headers).status_code == 409


def test_diagnostics_use_null_and_exact_evidence():
    assert groundedness({'evidence': {}})['groundedness']['value'] is None
    assert human_judge_agreement([(None, 3)])['binary_mismatch']['value'] is None
    assert human_judge_agreement([(0, 3), (2, 3)])['binary_mismatch']['value'] == .5
    result = state_accuracy({'property': {'parking_required': False}}, {'property': {'parking_required': None}})
    assert result['exact_state'] == 0 and result['field_accuracy']['value'] == 0
    assert percentiles([])['p95'] is None


def test_same_snapshot_claim_is_checked_against_its_fact():
    from backend.app.explanations import TypedClaim, render_claim
    facts = {'property:a:monthly_rent_toman': {'value': 100, 'unit': 'toman', 'itinerary_id': None}}
    claim = render_claim(TypedClaim(property_id='a', field='monthly_rent_toman', operator='known'), facts, {'a'})
    answer = {'evidence': facts, 'ai_selected_claims': [claim], 'recommended_property_id': 'a'}
    assert groundedness(answer)['groundedness']['value'] == 1
    claim['text'] = 'A false price'
    assert groundedness(answer)['contradicted'] == 1
