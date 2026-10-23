"""Canonical contracts. JSON Schema and TypeScript are generated from these models."""
from __future__ import annotations

from datetime import date as Date, time as Time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = '1.0.0'
PARSER_VERSION = 'confirmed-fa-2'
RANKER_VERSION = 'fixed-reference-utility-2'


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class PropertyConditions(Contract):
    max_deposit_toman: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    max_monthly_rent_toman: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    min_area_m2: float | None = Field(None, ge=0)
    min_bedrooms: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    parking_required: bool | None = False
    elevator_required: bool | None = False


class Destination(Contract):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str = Field('مقصد روی نقشه', max_length=200)
    confirmed: Literal[True]


class Travel(Contract):
    destination: Destination | None = None
    date: Date | None = None
    time: Time | None = None
    time_mode: Literal['ARRIVE_BY', 'DEPART_AT'] = 'DEPART_AT'
    timezone: Literal['Asia/Tehran'] = 'Asia/Tehran'
    max_duration_seconds: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    max_walk_seconds: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    max_walk_meters: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    max_transfers: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    modes: list[str] = Field(default_factory=list, max_length=10)
    include_walk_only: bool = False
    duration_scope: Literal['itinerary'] = 'itinerary'

    @model_validator(mode='after')
    def coherent(self):
        active = any(getattr(self, key) is not None for key in (
            'max_duration_seconds', 'max_walk_seconds', 'max_walk_meters', 'max_transfers'))
        if (active or self.modes or self.include_walk_only) and self.destination is None:
            raise ValueError('Travel constraints require a confirmed destination')
        if self.time and self.time.tzinfo is not None:
            raise ValueError('Use a local time without offset; timezone is Asia/Tehran')
        if len(set(self.modes)) != len(self.modes):
            raise ValueError('Duplicate modes')
        return self


class Accessibility(Contract):
    semantics_version: Literal['accessibility-1'] = 'accessibility-1'
    enabled: bool = True
    time_policy: Literal['request_execution'] = 'request_execution'
    effective_at: str | None = None


class SearchState(Contract):
    schema_version: Literal['1.0.0'] = SCHEMA_VERSION
    dataset_version: str = Field(min_length=1, max_length=100)
    state_revision: int = Field(0, ge=0, strict=True)
    query: str = Field('', max_length=1000)
    property: PropertyConditions = Field(default_factory=PropertyConditions)
    selected_neighborhood_ids: list[str] = Field(default_factory=list, max_length=400)
    selected_district_ids: list[str] = Field(default_factory=list, max_length=30)
    travel: Travel = Field(default_factory=Travel)
    accessibility: Accessibility | None = None
    preference: Literal['balanced', 'lower_rent', 'faster_commute', 'less_walking', 'fewer_transfers'] = 'balanced'
    soft_preferences: list[Literal['parking', 'elevator', 'lower_rent', 'faster_commute', 'less_walking', 'fewer_transfers']] = Field(default_factory=list, max_length=6)
    sort: Literal['recommended', 'rent_asc', 'deposit_asc', 'travel_time_asc', 'walk_time_asc', 'transfers_asc', 'stop_walk_time_asc', 'stop_distance_asc'] = 'recommended'


    @model_validator(mode='after')
    def accessibility_coherence(self):
        automatic = bool(self.accessibility and self.accessibility.enabled)
        if not automatic and self.travel.destination and (self.travel.date is None or self.travel.time is None):
            raise ValueError('A destination requires an explicit date and local time')
        if self.sort in ('stop_walk_time_asc', 'stop_distance_asc') and (not automatic or self.travel.destination):
            raise ValueError('Stop sorting requires automatic accessibility without a destination')
        if automatic and self.sort == 'transfers_asc':
            raise ValueError('Transfers sort belongs to legacy journey semantics')
        return self


class SourceRecord(Contract):
    source: str
    source_id: str
    url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    published_at: str | None = None
    collected_at: str | None = None


class PropertyListing(Contract):
    property_id: str
    series_id: str | None = None
    neighborhood_id: str | None = None
    neighborhood_ids: list[str] = Field(default_factory=list)
    neighborhood_membership_status: Literal['unique', 'ambiguous', 'outside', 'unknown'] = 'unknown'
    district_ids: list[str] = Field(default_factory=list)
    district_membership_status: Literal['unique', 'ambiguous', 'outside', 'unknown']
    title_fa: str
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    deposit_toman: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    monthly_rent_toman: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    area_m2: float | None = Field(None, ge=0)
    bedrooms: int | None = Field(None, ge=0, le=9000000000000000, strict=True)
    parking: bool | None = None
    elevator: bool | None = None
    location_accuracy: str = 'unknown'
    source_records: list[SourceRecord]
    published_at: str | None = None
    collected_at: str | None = None
    is_synthetic: bool
    dataset_version: str
    seed: int | None = None
    quality_flags: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Both coordinates must be present or missing')
        return self


class PatchOperation(Contract):
    field: str
    value: Any = None
    remove: bool = False


PATCH_FIELDS = {'query', 'selected_neighborhood_ids', 'selected_district_ids', 'preference', 'soft_preferences', 'sort'} | {
    f'property.{name}' for name in PropertyConditions.model_fields
} | {f'travel.{name}' for name in Travel.model_fields}


def apply_patch(state: SearchState, operations: list[dict | PatchOperation]) -> SearchState:
    """Apply an allowlisted internal patch, not RFC 6902. Validation is atomic."""
    data = state.model_dump(mode='json')
    defaults = SearchState(dataset_version=state.dataset_version).model_dump(mode='json')
    for raw in operations:
        op = raw if isinstance(raw, PatchOperation) else PatchOperation.model_validate(raw)
        if op.field not in PATCH_FIELDS:
            raise ValueError(f'Unsupported patch field: {op.field}')
        parts = op.field.split('.')
        target, default = data, defaults
        for part in parts[:-1]:
            target, default = target[part], default[part]
        target[parts[-1]] = default[parts[-1]] if op.remove else op.value
    data['state_revision'] = state.state_revision + 1
    return SearchState.model_validate(data)


class SearchInput(Contract):
    state: SearchState
    task_id: str | None = None
    parent_request_id: str | None = None
    new_need: bool = False


class ParseInput(Contract):
    text: str = Field(max_length=1000)


class ParseOutput(Contract):
    operations: list[PatchOperation] = Field(default_factory=list, max_length=20)
    unsupported: list[str] = Field(default_factory=list)
    mode: str = 'حالت نمونه بدون LLM'
    parser_version: str = PARSER_VERSION

class Itinerary(Contract):
    itinerary_id: str
    otp_response_id: str
    origin: dict[str, Any]
    destination: dict[str, Any]
    request_datetime: str
    time_mode: Literal['ARRIVE_BY', 'DEPART_AT']
    start_datetime: str | None
    end_datetime: str | None
    total_duration_seconds: float | None = Field(ge=0)
    walk_duration_seconds: float | None = Field(ge=0)
    walk_distance_meters: float | None = Field(ge=0)
    transfers: int | None = Field(ge=0)
    legs: list[dict[str, Any]]
    geometry: dict[str, Any] | None
    status: str
    source_kind: Literal['live_otp', 'recorded_otp', 'synthetic_fixture']
    schedule_basis: Literal['official_schedule', 'synthetic_schedule', 'unknown']
    realtime_status: Literal['available', 'unavailable', 'unknown']
    location_accuracy: str
    graph_version: str | None
    fetched_at: str
    missing_fields: list[str]
    request_to_start_seconds: float | None = Field(None, ge=0)
