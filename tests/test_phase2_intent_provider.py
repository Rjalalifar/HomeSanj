import asyncio
import json

import pytest

from backend.app.contracts import SearchState
from backend.app.intent import IntentInput, interpret
from backend.app.llm import ProviderError
from tests.test_search import TinyGeo


def test_provider_clarification_cannot_silently_commit(monkeypatch):
    monkeypatch.setenv('INTENT_LLM_ENABLED', 'true')
    class Provider:
        async def complete(self, *args):
            return json.dumps({'operations': [{'field': 'property.parking_required', 'value': True}],
                               'clarifications': ['آیا پارکینگ الزامی است؟'], 'soft_preferences': []})
    result = asyncio.run(interpret(IntentInput(state=SearchState(dataset_version='test'), text='شرایط خاص', use_ai=True), TinyGeo(), Provider(), []))
    assert result['search_pending'] is True


def test_provider_extra_server_fields_rejected_with_one_repair(monkeypatch):
    monkeypatch.setenv('INTENT_LLM_ENABLED', 'true')
    class Provider:
        calls = 0
        async def complete(self, *args):
            self.calls += 1
            return '{"operations":[],"clarifications":[],"soft_preferences":[],"provider":"attacker"}'
    provider = Provider()
    with pytest.raises(ProviderError, match='validation_error'):
        asyncio.run(interpret(IntentInput(state=SearchState(dataset_version='test'), text='شرایط خاص', use_ai=True), TinyGeo(), provider, []))
    assert provider.calls == 2
