import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from backend.app.contracts import SearchState, apply_patch
from backend.app.db import Database, ProviderCall
from backend.app.llm import AvalAIProvider, ProviderError, limited_parse
from sqlalchemy import select


def test_limited_parser_does_not_infer_unsupported_destination():
    result = limited_parse('اجاره تا ۱۵ میلیون تومان و حداقل ۲ اتاق و نزدیک مترو')
    state = apply_patch(SearchState(dataset_version='test'), result.operations)
    assert state.property.max_monthly_rent_toman == 15_000_000
    assert state.property.min_bedrooms == 2
    assert state.travel.destination is None
    assert result.unsupported == ['نزدیک مترو']


class FakeClient:
    def __init__(self, results):
        self.results, self.calls = list(results), 0
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=result))])


def provider(monkeypatch, client):
    monkeypatch.setenv('LLM_ENABLED', 'true')
    db = Database('sqlite:///:memory:')
    db.migrate()
    p = AvalAIProvider(db, client=client)
    p._verified = lambda role: True
    return p, db


def test_invalid_json_cannot_create_patch_and_repairs_once(monkeypatch):
    client = FakeClient(['not JSON', '{"operations":[{"field":"schema_version","value":"bad"}]}'])
    p, db = provider(monkeypatch, client)
    with pytest.raises(ProviderError, match='validation_error'):
        asyncio.run(p.parse('hello'))
    assert client.calls == 2
    with db.session() as session:
        assert all(row.status == 'validation_error' for row in session.scalars(select(ProviderCall)))


def test_unauthorized_is_never_retried(monkeypatch):
    response = httpx.Response(401, request=httpx.Request('POST', 'https://invalid.example'))
    client = FakeClient([openai.AuthenticationError('invalid credentials', response=response, body=None)])
    p, db = provider(monkeypatch, client)
    with pytest.raises(ProviderError, match='authentication_error'):
        asyncio.run(p.complete('parser', [{'role': 'user', 'content': 'x'}]))
    assert client.calls == 1


def test_timeout_reserves_budget_and_prevents_unbudgeted_retry(monkeypatch):
    client = FakeClient([openai.APITimeoutError(request=httpx.Request('POST', 'https://invalid.example'))])
    p, db = provider(monkeypatch, client)
    p.daily_limit = 1
    with pytest.raises(ProviderError, match='budget_stopped'):
        asyncio.run(p.complete('parser', [{'role': 'user', 'content': 'x'}]))
    with db.session() as session:
        calls = list(session.scalars(select(ProviderCall)))
        assert len(calls) == 1 and calls[0].status == 'timeout' and calls[0].reserved_tokens > 0
    assert client.calls == 1


def test_disabled_provider_uses_offline_parser(monkeypatch):
    monkeypatch.setenv('LLM_ENABLED', 'false')
    client = FakeClient([])
    db = Database('sqlite:///:memory:')
    db.migrate()
    p = AvalAIProvider(db, client=client)
    result = asyncio.run(p.parse('پارکینگ لازم نیست'))
    assert result.operations[0].value is False
    assert client.calls == 0
