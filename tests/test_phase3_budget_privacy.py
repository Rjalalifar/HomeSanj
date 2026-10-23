"""Offline provider budgets remain independent and sensitive evidence stays restricted."""
import asyncio
from copy import deepcopy
import pytest
from backend.app.db import Database, Evaluation, SearchRequest
from backend.app.llm import AvalAIProvider, ProviderError
from backend.app.evaluation_replay import freeze_manifest, replay_manifest
from backend.app.evaluation_metrics import qualified_success
from tests.test_llm import FakeClient
from tests.test_feedback import request_fixture
from datetime import datetime, timezone


def test_offline_reservations_do_not_spend_parser_quota(monkeypatch):
    monkeypatch.setenv('AI_JUDGE_ENABLED', 'true')
    monkeypatch.setenv('INTENT_LLM_ENABLED', 'true')
    monkeypatch.setenv('JUDGE_MAX_CALLS_PER_MINUTE', '10')
    database = Database('sqlite:///:memory:')
    database.migrate()
    provider = AvalAIProvider(database, client=FakeClient(['{}', '{}']))
    provider._verified = lambda role: True
    provider.daily_limit = 1
    asyncio.run(provider.complete('judge', [{'role': 'user', 'content': 'fixture'}]))
    asyncio.run(provider.complete('parser', [{'role': 'user', 'content': 'fixture'}]))
    assert provider.client.calls == 2


def test_unverified_cost_cap_defers_before_dispatch(monkeypatch):
    monkeypatch.setenv('AI_JUDGE_ENABLED', 'true')
    monkeypatch.setenv('JUDGE_DAILY_MAX_COST_USD', '0.01')
    monkeypatch.delenv('JUDGE_UPPER_COST_PER_MILLION_TOKENS_USD', raising=False)
    database = Database('sqlite:///:memory:')
    database.migrate()
    provider = AvalAIProvider(database, client=FakeClient([]))
    provider._verified = lambda role: True
    with pytest.raises(ProviderError, match='cost_budget_unverifiable'):
        asyncio.run(provider.complete('judge', [{'role': 'user', 'content': 'fixture'}]))
    assert provider.client.calls == 0


def test_public_replay_never_exposes_destination_or_raw_sources(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "privacy.sqlite"}')
    db.migrate()
    rid = request_fixture(db, routing=True)
    with db.session.begin() as session:
        session.add(Evaluation(request_id=rid, property_id='p1', cache_key='test-cache', created_at='2026-01-01',
            result={'status': 'ok', 'selected_itinerary': {'itinerary_id': 'route-one', 'destination': {'latitude': 35.71, 'longitude': 51.42}, 'total_duration_seconds': 120}, 'verdicts': []}))
    manifest = freeze_manifest(db, rid)
    replay = replay_manifest(db, manifest['manifest_id'])
    assert replay['confirmed_state']['travel']['destination'] == {'reference': 'restricted_request_destination', 'confirmed': True}
    assert 'destination' not in replay['rows']['p1']['selected_itinerary']
    assert 'latitude' not in replay['rows']['p1']['property']


def test_explicit_property_confirmation_counts_without_relabeling_card_rejection():
    task = {'created_at': '2026-01-01T00:00:00+00:00', 'frozen_ids': ['a'], 'hard_pass_ids': ['a'],
        'completion_status': 'complete', 'feedback': [{'kind': 'property', 'label': 'positive', 'candidate_ids': ['a']}]}
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert qualified_success([task], now=now)['S'] == 1
    task['feedback'].append({'kind': 'property', 'label': 'negative', 'candidate_ids': ['a']})
    assert qualified_success([task], now=now)['U'] == 1
