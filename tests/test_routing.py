"""Offline routing contracts; these tests never call live services."""
import asyncio
from datetime import datetime
import json

import httpx
import pytest

from backend.app.routing import (
    OTPAdapter, OTPSettings, cache_key, decode_polyline,
    evaluate_itineraries, normalize_itinerary, request_datetime,
)

ORIGIN = {"latitude": 35.72, "longitude": 51.4}
TRAVEL = {
    "destination": {"latitude": 35.7, "longitude": 51.42, "confirmed": True},
    "date": "2026-10-20", "time": "23:50:00", "timezone": "Asia/Tehran",
    "time_mode": "DEPART_AT", "modes": ["BUS"], "include_walk_only": False,
    "max_duration_seconds": 2500, "max_walk_seconds": 1000,
    "max_walk_meters": 1200, "max_transfers": 1,
}


def raw_itinerary(walk=600, duration=1800):
    start = int(request_datetime(TRAVEL).timestamp() * 1000)
    return {
        "duration": duration, "startTime": start, "endTime": start + duration * 1000,
        "numberOfTransfers": 1,
        "legs": [
            {"mode": "WALK", "transitLeg": False, "duration": walk / 3, "distance": 200},
            {"mode": "BUS", "transitLeg": True, "duration": 500, "distance": 3000, "realTime": False},
            {"mode": "WALK", "transitLeg": False, "duration": walk / 3, "distance": 200},
            {"mode": "BUS", "transitLeg": True, "duration": 500, "distance": 3000, "realTime": False},
            {"mode": "WALK", "transitLeg": False, "duration": walk / 3, "distance": 200},
        ],
    }


def norm(raw=None, **kwargs):
    return normalize_itinerary(raw or raw_itinerary(), ORIGIN, TRAVEL, "response_1", OTPSettings(), **kwargs)


def test_sums_all_walk_legs_and_never_double_adds_wait():
    result = norm()
    assert result["walk_duration_seconds"] == 600
    assert result["walk_distance_meters"] == 600
    assert result["total_duration_seconds"] == 1800
    assert result["transfers"] == 1
    assert result["source_kind"] == "live_otp"
    assert result["realtime_status"] == "unavailable"
    assert result["schedule_basis"] == "unknown"


def test_missing_walk_data_and_missing_transfer_count_stay_unknown():
    raw = raw_itinerary()
    raw["legs"][2]["duration"] = None
    del raw["numberOfTransfers"]
    result = norm(raw)
    assert result["walk_duration_seconds"] is None
    assert result["transfers"] is None
    evaluated = evaluate_itineraries([result], TRAVEL)
    assert evaluated["status"] == "no_feasible_returned_itinerary"
    assert any(v["verdict"] == "unknown" for v in evaluated["itinerary_evaluations"][0]["verdicts"])


def test_no_walking_legs_are_unknown_without_explicit_zero_summary():
    raw = raw_itinerary()
    raw["legs"] = [leg for leg in raw["legs"] if leg["mode"] == "BUS"]
    assert norm(raw)["walk_duration_seconds"] is None
    raw.update(walkTime=0, walkDistance=0)
    assert norm(raw)["walk_duration_seconds"] == 0
    assert norm(raw)["walk_distance_meters"] == 0


def test_missing_walk_segment_detected_by_summary():
    raw = raw_itinerary()
    raw["walkTime"] = 900
    assert norm(raw)["walk_duration_seconds"] is None


def test_alternative_itinerary_passes_all_constraints_on_same_route():
    fastest = norm(raw_itinerary(walk=1200, duration=1500))
    alternative = norm(raw_itinerary(walk=600, duration=2000))
    result = evaluate_itineraries([fastest, alternative], TRAVEL)
    assert result["status"] == "ok"
    assert result["selected_itinerary"]["itinerary_id"] == alternative["itinerary_id"]
    assert result["selected_itinerary"]["total_duration_seconds"] == 2000
    assert result["selected_itinerary"]["walk_duration_seconds"] == 600


def test_cannot_borrow_best_metric_from_another_route():
    fastest = norm(raw_itinerary(walk=1200, duration=1500))
    slower = norm(raw_itinerary(walk=300, duration=3000))
    assert evaluate_itineraries([fastest, slower], TRAVEL)["status"] == "no_feasible_returned_itinerary"


def test_time_units_offset_midnight_and_arrive_by():
    result = norm()
    assert datetime.fromisoformat(result["end_datetime"]).astimezone(request_datetime(TRAVEL).tzinfo).day == 21
    assert result["request_datetime"].endswith("+03:30")
    raw = raw_itinerary()
    raw["startTime"] /= 1000
    raw["endTime"] /= 1000
    assert norm(raw, timestamp_unit="seconds")["start_datetime"] == result["start_datetime"]
    arrive = dict(TRAVEL, date="2026-10-21", time="00:20:00", time_mode="ARRIVE_BY")
    assert evaluate_itineraries([result], arrive)["status"] == "ok"
    assert evaluate_itineraries([result], dict(arrive, time="00:19:00"))["status"] == "no_feasible_returned_itinerary"
    assert evaluate_itineraries([result], dict(TRAVEL, time="23:51:00"))["status"] == "no_feasible_returned_itinerary"


def test_explicit_polyline_lon_lat_order():
    assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")[0] == [-120.2, 38.5]
    with pytest.raises(ValueError):
        decode_polyline("_")


def test_duration_inconsistent_with_timestamps_invalid():
    raw = raw_itinerary()
    raw["duration"] += 1000
    with pytest.raises(ValueError):
        norm(raw)


def test_walk_only_requires_opt_in_and_mixed_car_is_rejected():
    raw = raw_itinerary()
    raw["legs"] = [leg for leg in raw["legs"] if leg["mode"] == "WALK"]
    walk = norm(raw)
    assert evaluate_itineraries([walk], TRAVEL)["status"] == "no_feasible_returned_itinerary"
    assert evaluate_itineraries([walk], dict(TRAVEL, include_walk_only=True))["status"] == "ok"
    mixed = norm()
    mixed["legs"][0].update(mode="CAR", is_transit=False)
    assert evaluate_itineraries([mixed], dict(TRAVEL, modes=[]))["status"] == "no_feasible_returned_itinerary"


def test_cache_key_changes_for_every_effective_setting_but_not_preference():
    settings = OTPSettings()
    base = cache_key(ORIGIN, TRAVEL, settings)
    for key, value in [("date", "2026-10-21"), ("time", "22:00:00"), ("time_mode", "ARRIVE_BY"),
                       ("modes", ["RAIL"]), ("include_walk_only", True), ("max_walk_seconds", 700)]:
        assert cache_key(ORIGIN, dict(TRAVEL, **{key: value}), settings) != base
    assert cache_key(dict(ORIGIN, latitude=35.721), TRAVEL, settings) != base
    assert cache_key(ORIGIN, TRAVEL, OTPSettings(graph_version="new")) != base
    assert cache_key(ORIGIN, dict(TRAVEL, preference="less_walking"), settings) == base


def test_profile_verification_cannot_move_to_another_endpoint(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"base_url": "http://127.0.0.1:8821", "api_path": "/verified",
                               "api_type": "legacy_rest_plan", "routing_api_verified": True}))
    monkeypatch.setenv("OTP_PROFILE_PATH", str(path))
    monkeypatch.delenv("OTP_API_PATH", raising=False)
    monkeypatch.setenv("OTP_BASE_URL", "http://different:8821")
    assert not OTPSettings.from_env().api_verified


def test_unconfigured_adapter_does_not_call_root():
    async def run():
        async def fail(request):
            pytest.fail("No HTTP request is permitted before discovery")
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            adapter = OTPAdapter(OTPSettings(), client)
            assert (await adapter.route(ORIGIN, TRAVEL))["status"] == "not_configured"
    asyncio.run(run())


def test_timeout_no_route_and_invalid_response_are_distinct():
    async def run():
        for expected in ("timeout", "no_route_returned", "invalid_response", "api_error"):
            async def handler(request):
                if expected == "timeout":
                    raise httpx.ReadTimeout("offline timeout")
                if expected == "no_route_returned":
                    return httpx.Response(200, json={"plan": {"itineraries": []}})
                if expected == "api_error":
                    return httpx.Response(500, json={})
                return httpx.Response(200, json={"something": []})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                settings = OTPSettings(api_path="/verified", api_type="legacy_rest_plan", api_verified=True,
                                       max_retries=0, supported_modes=["BUS"])
                assert (await OTPAdapter(settings, client).route(ORIGIN, TRAVEL))["status"] == expected
    asyncio.run(run())


def test_concurrency_cancellation_and_bounded_retries():
    async def run():
        active = maximum = calls = 0
        async def handler(request):
            nonlocal active, maximum, calls
            calls += 1
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0.015)
                return httpx.Response(200, json={"plan": {"itineraries": []}})
            finally:
                active -= 1
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            settings = OTPSettings(api_path="/verified", api_type="legacy_rest_plan", api_verified=True,
                                   max_retries=0, max_concurrency=3, supported_modes=["BUS"])
            adapter = OTPAdapter(settings, client)
            tasks = [asyncio.create_task(adapter.route(ORIGIN, TRAVEL)) for _ in range(10)]
            await asyncio.sleep(0)
            tasks[-1].cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            assert maximum == 3
            assert active == 0
            assert calls == 9
        attempts = 0
        async def transient(request):
            nonlocal attempts
            attempts += 1
            return httpx.Response(503)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transient)) as client:
            settings.max_retries = 1
            assert (await OTPAdapter(settings, client).route(ORIGIN, TRAVEL))["status"] == "api_error"
            assert attempts == 2
    asyncio.run(run())


def test_fixture_is_only_explicit_and_labels_synthetic_schedule():
    async def run():
        adapter = OTPAdapter(OTPSettings(fixture_mode=True))
        result = await adapter.route(ORIGIN, TRAVEL)
        assert result["itineraries"][0]["source_kind"] == "synthetic_fixture"
        assert result["itineraries"][0]["schedule_basis"] == "synthetic_schedule"
        assert evaluate_itineraries(result["itineraries"], TRAVEL)["status"] == "ok"
    asyncio.run(run())


def test_transmodel_null_data_and_unknown_error_are_not_no_route():
    adapter = OTPAdapter(OTPSettings(api_type='transmodel_v3'))
    assert adapter._normalize_response({'data': None}, ORIGIN, TRAVEL, 'bad')['status'] == 'invalid_response'
    raw = {'data': {'trip': {'tripPatterns': [], 'routingErrors': [{'code': 'unknownServerFailure'}]}}}
    assert adapter._normalize_response(raw, ORIGIN, TRAVEL, 'bad')['status'] == 'api_error'
    raw['data']['trip']['routingErrors'] = [{'code': 'outsideBounds'}]
    assert adapter._normalize_response(raw, ORIGIN, TRAVEL, 'outside')['status'] == 'out_of_coverage'


def test_recorded_live_contract_fits_canonical_itinerary_schema():
    from pathlib import Path
    from backend.app.contracts import Itinerary
    path = Path('data/otp/contract-result.json')
    if not path.exists():
        pytest.skip('No recorded contract; this test never contacts live OTP')
    result = json.loads(path.read_text(encoding='utf-8'))
    for item in result['itineraries']:
        Itinerary.model_validate(item)
        assert item['transfers'] is None
        assert item['walk_duration_seconds'] == sum(leg['duration_seconds'] for leg in item['legs'] if leg['mode'] == 'WALK')
