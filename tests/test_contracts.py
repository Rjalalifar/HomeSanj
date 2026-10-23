import pytest
from pydantic import ValidationError

from backend.app.contracts import SearchState, apply_patch
from backend.app.normalize import normalize_text, parse_money, parse_bool


def test_money_digits_units_and_missing():
    assert parse_money('۲٫۵ میلیارد تومان') == 2_500_000_000
    assert parse_money('١٢ میلیون ریال') == 1_200_000
    assert parse_money('5000000', 'rial') == 500_000
    assert parse_money(None) is None
    assert parse_bool(None) is None
    assert parse_bool('ندارد') is False
    with pytest.raises(ValueError):
        parse_money('قیمت توافقی')
    with pytest.raises(ValueError):
        parse_money('11 ریال')


def test_normalized_search_text():
    assert normalize_text('كيان\u200cشهر ۱۲') == 'کیان شهر 12'


def test_patch_semantics_and_strict_allowlist():
    state = SearchState(dataset_version='test')
    modified = apply_patch(state, [{'field': 'property.parking_required', 'value': True}])
    assert modified.property.parking_required is True
    reset = apply_patch(modified, [{'field': 'property.parking_required', 'remove': True}])
    assert reset.property.parking_required is False
    assert reset.state_revision == 2
    assert state.state_revision == 0
    with pytest.raises(ValueError):
        apply_patch(state, [{'field': 'schema_version', 'value': 'hack'}])
    with pytest.raises(ValidationError):
        SearchState(dataset_version='test', property={'max_deposit_toman': -1})


def test_travel_requires_confirmed_destination_and_time():
    with pytest.raises(ValidationError):
        SearchState(dataset_version='test', travel={'destination': {'latitude': 35.7, 'longitude': 51.4, 'confirmed': False}})
    with pytest.raises(ValidationError):
        SearchState(dataset_version='test', travel={'max_duration_seconds': 1800})
