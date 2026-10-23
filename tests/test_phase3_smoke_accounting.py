"""Smoke limits cover every role, and missing provider usage remains unknown."""
import asyncio
from types import SimpleNamespace

import httpx
import openai
from sqlalchemy import select

from backend.app.db import Database, ProviderCall
from backend.app.evaluation_dashboard import dashboard
from backend.app.llm import AvalAIProvider
from tests.test_llm import FakeClient


def smoke_provider(monkeypatch, tmp_path, results):
    monkeypatch.setenv('LLM_ENABLED', 'false')
    monkeypatch.setenv('AI_JUDGE_ENABLED', 'true')
    monkeypatch.setenv('AI_IMPROVEMENT_ENABLED', 'true')
    monkeypatch.setenv('JUDGE_MODEL', 'judge-fixture-1')
    monkeypatch.setenv('IMPROVEMENT_MODEL', 'improvement-fixture-1')
    for role in ('JUDGE', 'IMPROVEMENT'):
        monkeypatch.delenv(role + '_DAILY_MAX_COST_USD', raising=False)
        monkeypatch.delenv(role + '_UPPER_COST_PER_MILLION_TOKENS_USD', raising=False)
    db = Database('sqlite:///:memory:')
    db.migrate()
    client = FakeClient(results)

    async def catalog():
        return SimpleNamespace(data=[SimpleNamespace(id=name, model_dump=lambda: {})
            for name in ('judge-fixture-1', 'improvement-fixture-1')])

    client.models = SimpleNamespace(list=catalog)
    return AvalAIProvider(db, client=client, capability_path=tmp_path / 'capabilities.json'), db


def test_smoke_command_budget_covers_independent_offline_roles(monkeypatch, tmp_path):
    provider, db = smoke_provider(monkeypatch, tmp_path, ['{"ok":true}', '{"ok":true}'])
    stopped = asyncio.run(provider.smoke(max_requests=1))
    assert stopped['status'] == 'budget_stopped'
    assert provider.client.calls == 0
    assert not provider.capability_path.exists()
    passed = asyncio.run(provider.smoke(max_requests=2))
    assert passed['status'] == 'ok'
    assert len(passed['verified_models']) == 2
    assert provider.client.calls == 2
    with db.session() as session:
        assert len(list(session.scalars(select(ProviderCall)))) == 2


def test_smoke_never_retries_a_billable_timeout(monkeypatch, tmp_path):
    error = openai.APITimeoutError(request=httpx.Request('POST', 'https://invalid.example'))
    provider, db = smoke_provider(monkeypatch, tmp_path, [error, '{"ok":true}'])
    monkeypatch.setenv('AI_IMPROVEMENT_ENABLED', 'false')
    provider.retries = 2
    report = asyncio.run(provider.smoke(max_requests=1))
    assert report['status'] == 'timeout'
    assert provider.client.calls == 1
    with db.session() as session:
        calls = list(session.scalars(select(ProviderCall)))
        assert len(calls) == 1 and calls[0].status == 'timeout'


def test_dashboard_does_not_turn_missing_usage_into_zero(monkeypatch, tmp_path):
    provider, db = smoke_provider(monkeypatch, tmp_path, [])
    first = provider._reserve('judge', 80)
    provider._finish(first, 'timeout')
    usage = dashboard(db)['providers']['judge']
    assert usage['observed_total_tokens'] is None
    assert usage['token_usage_missing_calls'] == 1
    provider._finish(first, 'ok', {'total_tokens': 10})
    assert dashboard(db)['providers']['judge']['observed_total_tokens'] == 10
    second = provider._reserve('judge', 80)
    provider._finish(second, 'timeout')
    mixed = dashboard(db)['providers']['judge']
    assert mixed['observed_total_tokens'] is None
    assert mixed['known_token_total'] == 10
    assert mixed['token_usage_available_calls'] == 1
    assert mixed['token_usage_missing_calls'] == 1
