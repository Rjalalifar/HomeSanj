"""OTP transport, explicit normalization, and evidence-based itinerary selection."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

ADAPTER_VERSION = "otp-explicit-1.0.0"


def _dict(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)


@dataclass
class OTPSettings:
    base_url: str = "http://127.0.0.1:8821"
    api_path: str = ""
    api_type: str = ""
    timeout_seconds: float = 20
    max_concurrency: int = 3
    max_retries: int = 1
    fixture_mode: bool = False
    supported_modes: list[str] = field(default_factory=list)
    graph_version: str | None = None
    schedule_basis: str = "unknown"
    api_verified: bool = False
    profile_path: str = "data/otp/api-profile.json"

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        profile_path = os.getenv("OTP_PROFILE_PATH", cls.profile_path)
        profile = json.loads(Path(profile_path).read_text(encoding="utf-8")) if Path(profile_path).is_file() else {}
        settings = cls(
            base_url=os.getenv("OTP_BASE_URL", profile.get("base_url", cls.base_url)).rstrip("/"),
            api_path=os.getenv("OTP_API_PATH") or profile.get("api_path", ""),
            api_type=os.getenv("OTP_API_TYPE") or profile.get("api_type", ""),
            timeout_seconds=max(0.1, min(120, float(os.getenv("OTP_TIMEOUT_SECONDS", "20")))),
            max_concurrency=max(1, min(10, int(os.getenv("OTP_MAX_CONCURRENCY", "3")))),
            max_retries=max(0, min(2, int(os.getenv("OTP_MAX_RETRIES", "1")))),
            fixture_mode=os.getenv("OTP_FIXTURE_MODE", "false").lower() == "true",
            supported_modes=[x for x in os.getenv("OTP_SUPPORTED_MODES", ",".join(profile.get("supported_modes", []))).split(",") if x],
            graph_version=os.getenv("OTP_GRAPH_VERSION") or profile.get("graph_version"),
            schedule_basis=os.getenv("OTP_SCHEDULE_BASIS", profile.get("schedule_basis", "unknown")),
            api_verified=bool(profile.get("routing_api_verified")),
            profile_path=profile_path,
        )
        if settings.schedule_basis not in ("unknown", "official_schedule", "synthetic_schedule"):
            raise ValueError("Invalid OTP_SCHEDULE_BASIS")
        settings.api_verified = settings.api_verified and all(getattr(settings, name) == profile.get(name) for name in ("base_url", "api_path", "api_type"))
        return settings


def request_datetime(travel: dict) -> datetime:
    travel = _dict(travel)
    if travel.get("timezone", "Asia/Tehran") != "Asia/Tehran":
        raise ValueError("Only Asia/Tehran is supported")
    value = datetime.fromisoformat(f"{travel['date']}T{travel['time']}")
    if value.tzinfo is not None:
        raise ValueError("Request time must be a local time without offset")
    return value.replace(tzinfo=ZoneInfo("Asia/Tehran"))


def cache_key(origin, travel, settings: OTPSettings | dict | None = None, **extra) -> str:
    """Cache the complete effective routing request; preference is deliberately absent."""
    travel, origin = _dict(travel), _dict(origin)
    settings = settings or OTPSettings()
    get = settings.get if isinstance(settings, dict) else lambda k, d=None: getattr(settings, k, d)
    destination = travel.get("destination") or {}
    effective = {
        "origin": {k: origin.get(k) for k in ("latitude", "longitude")},
        "destination": {k: destination.get(k) for k in ("latitude", "longitude")},
        "datetime": request_datetime(travel).isoformat(),
        "time_mode": travel.get("time_mode", "DEPART_AT"),
        "modes": sorted(travel.get("modes") or get("supported_modes", [])),
        "include_walk_only": travel.get("include_walk_only", False),
        "constraints": {k: travel.get(k) for k in ("max_duration_seconds", "max_walk_seconds", "max_walk_meters", "max_transfers", "duration_scope")},
        "base_url": get("base_url"), "api_path": get("api_path"), "api_type": get("api_type"),
        "graph_version": get("graph_version"), "fixture_mode": get("fixture_mode"),
        "schedule_basis": get("schedule_basis"), "adapter_version": ADAPTER_VERSION,
        "extra": extra,
    }
    return hashlib.sha256(json.dumps(effective, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _timestamp(value, unit: str = "milliseconds") -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Response datetime has no UTC offset")
        return parsed.isoformat()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid timestamp")
    return datetime.fromtimestamp(value / (1000 if unit == "milliseconds" else 1), timezone.utc).isoformat()


def _number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not float("-inf") < value < float("inf") or value < 0:
        raise ValueError("Invalid nonnegative metric")
    return value


def decode_polyline(encoded: str, precision: int = 5) -> list[list[float]]:
    """Decode the documented Google polyline encoding to GeoJSON lon/lat."""
    values, pos, lat, lon = [], 0, 0, 0
    while pos < len(encoded):
        pair = []
        for _ in range(2):
            shift = result = 0
            while True:
                if pos >= len(encoded) or shift > 30:
                    raise ValueError("Invalid encoded polyline")
                byte = ord(encoded[pos]) - 63
                pos += 1
                if byte < 0 or byte > 63:
                    raise ValueError("Invalid encoded polyline character")
                result |= (byte & 31) << shift
                shift += 5
                if byte < 32:
                    break
            pair.append(~(result >> 1) if result & 1 else result >> 1)
        lat, lon = lat + pair[0], lon + pair[1]
        values.append([lon / 10 ** precision, lat / 10 ** precision])
    return values


def normalize_itinerary(raw, origin, travel, response_id, settings, *, source_kind="live_otp", timestamp_unit="milliseconds"):
    """Normalize the verified legacy itinerary field contract used by OTP GraphQL."""
    travel = _dict(travel)
    missing, legs, geometry = [], [], []
    raw_legs = raw.get("legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        raise ValueError("Itinerary must contain legs")
    for item in raw_legs:
        mode = item.get("mode")
        transit = item.get("transitLeg")
        if transit is None and mode == "WALK":
            transit = False
        leg = {
            "mode": mode, "is_transit": transit, "duration_seconds": _number(item.get("duration")),
            "distance_meters": _number(item.get("distance")),
            "start_datetime": _timestamp(item.get("startTime"), timestamp_unit),
            "end_datetime": _timestamp(item.get("endTime"), timestamp_unit),
            "route": item.get("route"), "from": item.get("from"), "to": item.get("to"),
            "realtime": item.get("realTime"), "geometry": None,
        }
        encoded = item.get("legGeometry")
        if isinstance(encoded, dict) and encoded.get("points"):
            points = decode_polyline(encoded["points"])
            leg["geometry"] = {"type": "LineString", "coordinates": points}
            geometry.extend(points)
        legs.append(leg)
    walks = [leg for leg in legs if leg["mode"] == "WALK"]
    mode_known = all(leg["mode"] is not None for leg in legs)
    walk_seconds = sum(leg["duration_seconds"] for leg in walks) if walks and mode_known and all(leg["duration_seconds"] is not None for leg in walks) else None
    walk_meters = sum(leg["distance_meters"] for leg in walks) if walks and mode_known and all(leg["distance_meters"] is not None for leg in walks) else None
    for summary_key, total in [("walkTime", walk_seconds), ("walkDistance", walk_meters)]:
        summary = _number(raw.get(summary_key))
        if not walks and mode_known and summary == 0:
            if summary_key == "walkTime":
                walk_seconds = 0
            else:
                walk_meters = 0
        elif summary is not None and total is not None and abs(summary - total) > 2:
            missing.append(f"{summary_key}.leg_summary_mismatch")
            if summary_key == "walkTime":
                walk_seconds = None
            else:
                walk_meters = None
    start = _timestamp(raw.get("startTime"), timestamp_unit)
    end = _timestamp(raw.get("endTime"), timestamp_unit)
    duration = _number(raw.get("duration"))
    if start and end:
        elapsed = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        if elapsed < 0 or (duration is not None and abs(elapsed - duration) > 2):
            raise ValueError("Itinerary duration contradicts timestamps")
        if duration is None:
            duration = elapsed
    transfers = _number(raw.get("numberOfTransfers", raw.get("transfers")))
    if transfers is not None and int(transfers) != transfers:
        raise ValueError("Transfers must be an integer")
    requested = request_datetime(travel)
    wait_before = max(0, (datetime.fromisoformat(start) - requested).total_seconds()) if start and travel.get("time_mode", "DEPART_AT") == "DEPART_AT" else None
    transit_legs = [leg for leg in legs if leg["is_transit"] is True]
    realtime = "available" if any(leg["realtime"] is True for leg in transit_legs) else "unavailable" if transit_legs and all(leg["realtime"] is False for leg in transit_legs) else "unknown"
    values = {"start_datetime": start, "end_datetime": end, "total_duration_seconds": duration,
              "walk_duration_seconds": walk_seconds, "walk_distance_meters": walk_meters, "transfers": transfers}
    missing.extend(key for key, value in values.items() if value is None)
    if not mode_known:
        missing.append("leg.mode")
    if any(leg["is_transit"] is None for leg in legs):
        missing.append("leg.is_transit")
    return {
        "itinerary_id": "it_" + hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:24],
        "otp_response_id": response_id, "origin": _dict(origin), "destination": travel["destination"],
        "request_datetime": requested.isoformat(), "time_mode": travel.get("time_mode", "DEPART_AT"),
        **values, "legs": legs, "geometry": {"type": "LineString", "coordinates": geometry} if geometry else None,
        "status": "ok", "source_kind": source_kind, "schedule_basis": settings.schedule_basis,
        "realtime_status": realtime, "location_accuracy": origin.get("location_accuracy", "unknown"),
        "graph_version": settings.graph_version, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "missing_fields": missing, "request_to_start_seconds": wait_before,
    }


def evaluate_itineraries(itineraries, travel, preference="balanced"):
    """Require every active constraint to pass on one returned itinerary."""
    travel = _dict(travel)
    evaluations, feasible = [], []
    requested = request_datetime(travel)
    for item in itineraries:
        verdicts = []
        for condition, metric in [("max_duration_seconds", "total_duration_seconds"), ("max_walk_seconds", "walk_duration_seconds"),
                                  ("max_walk_meters", "walk_distance_meters"), ("max_transfers", "transfers")]:
            expected, actual = travel.get(condition), item.get(metric)
            if expected is not None:
                verdicts.append({"condition": condition, "actual": actual, "expected": expected,
                                 "verdict": "unknown" if actual is None else "pass" if actual <= expected else "fail"})
        legs = item.get("legs") or []
        modes = [leg.get("mode") for leg in legs]
        walk_only = bool(legs) and all(mode == "WALK" for mode in modes)
        transit_known = bool(legs) and all(leg.get("is_transit") is not None for leg in legs)
        has_transit = any(leg.get("is_transit") is True for leg in legs)
        if not travel.get("include_walk_only", False):
            verdicts.append({"condition": "transit_required", "actual": has_transit if transit_known else None,
                             "expected": True, "verdict": "pass" if has_transit else "fail" if transit_known else "unknown"})
        illegal = [leg.get("mode") for leg in legs if leg.get("mode") != "WALK" and
                   (leg.get("is_transit") is False or leg.get("mode") in ("CAR", "BICYCLE", "SCOOTER"))]
        if illegal:
            verdicts.append({"condition": "transit_and_walking_only", "actual": illegal, "verdict": "fail"})
        allowed = travel.get("modes") or []
        if allowed:
            compatible = bool(legs) and all(mode == "WALK" or mode in allowed for mode in modes)
            verdicts.append({"condition": "modes", "actual": modes, "expected": allowed,
                             "verdict": "unknown" if not legs or None in modes else "pass" if compatible else "fail"})
        elif not legs or None in modes:
            verdicts.append({"condition": "modes", "actual": modes, "verdict": "unknown"})
        if travel.get("include_walk_only") and not (has_transit or walk_only):
            verdicts.append({"condition": "supported_trip_kind", "actual": modes, "verdict": "unknown" if not transit_known else "fail"})
        time_mode = travel.get("time_mode", "DEPART_AT")
        metric = "end_datetime" if time_mode == "ARRIVE_BY" else "start_datetime"
        actual = item.get(metric)
        try:
            instant = datetime.fromisoformat(actual.replace("Z", "+00:00")) if actual else None
            if instant is not None and instant.tzinfo is None:
                instant = None
            passes = instant <= requested if time_mode == "ARRIVE_BY" and instant else instant >= requested if instant else False
        except (TypeError, ValueError):
            instant, passes = None, False
        verdicts.append({"condition": time_mode, "actual": actual, "expected": requested.isoformat(),
                         "verdict": "unknown" if instant is None else "pass" if passes else "fail"})
        evaluations.append({"itinerary_id": item.get("itinerary_id"), "verdicts": verdicts})
        if all(v["verdict"] == "pass" for v in verdicts):
            feasible.append((item, verdicts))
    if not feasible:
        return {"status": "no_feasible_returned_itinerary" if itineraries else "no_route_returned",
                "selected_itinerary": None, "verdicts": [], "itinerary_evaluations": evaluations,
                "message_fa": "در مسیرهای بازگشتی برای این تنظیمات گزینهٔ منطبق پیدا نشد"}
    order = {"less_walking": ["walk_duration_seconds", "total_duration_seconds", "transfers"],
             "fewer_transfers": ["transfers", "total_duration_seconds", "walk_duration_seconds"]}.get(
                 preference, ["total_duration_seconds", "walk_duration_seconds", "transfers"])
    selected, verdicts = min(feasible, key=lambda pair: tuple((pair[0].get(k) is None, pair[0].get(k) or 0) for k in order))
    return {"status": "ok", "selected_itinerary": selected, "verdicts": verdicts, "itinerary_evaluations": evaluations}


class OTPAdapter:
    def __init__(self, settings: OTPSettings | dict | None = None, client: httpx.AsyncClient | None = None):
        self.settings = OTPSettings(**settings) if isinstance(settings, dict) else settings or OTPSettings.from_env()
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self):
        return self.settings.fixture_mode or bool(self.settings.api_path and self.settings.api_type and self.settings.api_verified)

    async def close(self):
        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None

    async def route(self, origin, travel):
        origin, travel = _dict(origin), _dict(travel)
        if not self.configured:
            return {"status": "not_configured", "itineraries": [], "otp_response_id": None, "raw_response": None}
        if self.settings.fixture_mode:
            return self._fixture(origin, travel)
        if not self.settings.api_path.startswith("/") or self.settings.api_path == "/" or "://" in self.settings.api_path:
            return {"status": "not_configured", "itineraries": [], "error": "Invalid explicit routing API path"}
        pedestrian = travel.get("routing_profile") == "walk_only"
        if pedestrian and self.settings.api_type != "transmodel_v3":
            return {"status": "not_configured", "itineraries": [], "error": "Pedestrian capability not verified for this API type"}
        requested_modes = [] if pedestrian else travel.get("modes") or self.settings.supported_modes
        if not pedestrian and (not requested_modes or set(requested_modes) - set(self.settings.supported_modes)):
            return {"status": "invalid_request", "itineraries": [], "error": "Modes must be verified against the installed OTP data"}
        async with self._semaphore:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=self.settings.timeout_seconds)
            response_id = "otp_" + uuid4().hex
            for attempt in range(self.settings.max_retries + 1):
                try:
                    response = await self._request(origin, travel, requested_modes)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < self.settings.max_retries:
                            await asyncio.sleep(0.1 * 2 ** attempt)
                            continue
                    if response.status_code >= 400:
                        return {"status": "api_error", "itineraries": [], "otp_response_id": response_id, "http_status": response.status_code}
                    raw = response.json()
                    return self._normalize_response(raw, origin, travel, response_id)
                except httpx.TimeoutException:
                    if attempt == self.settings.max_retries:
                        return {"status": "timeout", "itineraries": [], "otp_response_id": response_id}
                except (httpx.RequestError, OSError):
                    if attempt == self.settings.max_retries:
                        return {"status": "api_error", "itineraries": [], "otp_response_id": response_id}
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                    return {"status": "invalid_response", "itineraries": [], "otp_response_id": response_id}
                if attempt < self.settings.max_retries:
                    await asyncio.sleep(0.1 * 2 ** attempt)

    async def _request(self, origin, travel, modes):
        profile = json.loads(Path(self.settings.profile_path).read_text(encoding="utf-8")) if Path(self.settings.profile_path).is_file() else {}
        destination = travel["destination"]
        url = self.settings.base_url.rstrip("/") + self.settings.api_path
        if self.settings.api_type == "transmodel_v3":
            variables = {
                "from": {"coordinates": {k: origin[k] for k in ("latitude", "longitude")}},
                "to": {"coordinates": {k: destination[k] for k in ("latitude", "longitude")}},
                "dateTime": request_datetime(travel).isoformat(),
                "arriveBy": travel.get("time_mode") == "ARRIVE_BY",
                "modes": {"accessMode": "foot", "egressMode": "foot",
                          "directMode": "foot" if travel.get("include_walk_only") else None,
                          "transportModes": [{"transportMode": mode.lower()} for mode in modes]},
            }
            if travel.get("routing_profile") == "walk_only":
                # Installed schema and a recorded live contract verify empty transit modes.
                variables["modes"] = {"directMode": "foot", "transportModes": []}
            return await self._client.post(url, json={"query": TRANSMODEL_QUERY, "variables": variables}, timeout=self.settings.timeout_seconds)
        if self.settings.api_type == "gtfs_graphql_plan":
            query = profile.get("routing_query")
            if not query:
                raise ValueError("Verified GraphQL query missing from API profile")
            variables = {
                "from": {"lat": origin["latitude"], "lon": origin["longitude"]},
                "to": {"lat": destination["latitude"], "lon": destination["longitude"]},
                "date": travel["date"], "time": travel["time"],
                "arriveBy": travel.get("time_mode") == "ARRIVE_BY",
                "modes": [{"mode": value} for value in sorted(set(modes) | {"WALK"})],
            }
            return await self._client.post(url, json={"query": query, "variables": variables}, timeout=self.settings.timeout_seconds)
        if self.settings.api_type == "legacy_rest_plan":
            return await self._client.get(url, params={
                "fromPlace": f"{origin['latitude']},{origin['longitude']}",
                "toPlace": f"{destination['latitude']},{destination['longitude']}",
                "date": travel["date"], "time": travel["time"],
                "arriveBy": str(travel.get("time_mode") == "ARRIVE_BY").lower(),
                "mode": ",".join(sorted(set(modes) | {"WALK"})),
                "numItineraries": 5,
            }, timeout=self.settings.timeout_seconds)
        raise ValueError("Unsupported or unverified API type")

    def _normalize_response(self, raw, origin, travel, response_id):
        if not isinstance(raw, dict):
            raise ValueError("Response must be an object")
        base = {"itineraries": [], "otp_response_id": response_id, "raw_response": raw}
        if raw.get("errors") or raw.get("error"):
            return {"status": "api_error", **base}
        if self.settings.api_type == "transmodel_v3":
            trip = (raw.get("data") or {}).get("trip")
            if not isinstance(trip, dict) or not isinstance(trip.get("tripPatterns"), list):
                return {"status": "invalid_response", **base}
            errors = trip.get("routingErrors") or []
            if not trip["tripPatterns"] and errors:
                codes = {error.get("code") for error in errors}
                status = "out_of_coverage" if codes & {"outsideBounds", "outsideServicePeriod"} else "no_route_returned" if codes <= {"locationNotFound", "noStopsInRange", "noTransitConnection", "noTransitConnectionInSearchWindow", "walkingBetterThanTransit", "noDirectModeConnection"} else "api_error"
                return {"status": status, **base, "routing_errors": errors}
            itineraries, invalid = [], []
            for index, item in enumerate(trip["tripPatterns"]):
                try:
                    itineraries.append(normalize_transmodel(item, origin, travel, response_id, self.settings))
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
                    invalid.append({"index": index, "reason": str(error)})
            return {**base, "itineraries": itineraries, "invalid_itineraries": invalid, "routing_errors": errors,
                    "status": "ok" if itineraries else "invalid_response" if invalid else "no_route_returned"}
        plan = (raw.get("data") or {}).get("plan") if self.settings.api_type == "gtfs_graphql_plan" else raw.get("plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("itineraries"), list):
            return {"status": "invalid_response", **base}
        itineraries, invalid = [], []
        for index, item in enumerate(plan["itineraries"]):
            try:
                itineraries.append(normalize_itinerary(item, origin, travel, response_id, self.settings))
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
                invalid.append({"index": index, "reason": str(error)})
        return {**base, "itineraries": itineraries, "invalid_itineraries": invalid,
                "status": "ok" if itineraries else "invalid_response" if invalid else "no_route_returned"}

    def _fixture(self, origin, travel):
        requested = request_datetime(travel)
        duration = 1800
        start = requested - timedelta(seconds=duration) if travel.get("time_mode") == "ARRIVE_BY" else requested
        stamp = lambda dt: int(dt.timestamp() * 1000)
        raw = {"duration": duration, "startTime": stamp(start), "endTime": stamp(start + timedelta(seconds=duration)),
               "numberOfTransfers": 0, "legs": [
                   {"mode": "WALK", "transitLeg": False, "duration": 300, "distance": 350},
                   {"mode": "BUS", "transitLeg": True, "duration": 1200, "distance": 5000, "realTime": False},
                   {"mode": "WALK", "transitLeg": False, "duration": 300, "distance": 350}]}
        if travel.get("routing_profile") == "walk_only":
            raw["legs"] = [{"mode": "WALK", "transitLeg": False, "duration": duration, "distance": 1500}]
        response_id = "synthetic_" + cache_key(origin, travel, self.settings)[:24]
        itinerary = normalize_itinerary(raw, origin, travel, response_id, self.settings, source_kind="synthetic_fixture")
        itinerary["schedule_basis"] = "synthetic_schedule"
        return {"status": "ok", "itineraries": [itinerary], "otp_response_id": response_id, "raw_response": raw, "fixture_mode": True}


TRANSMODEL_QUERY = """query KhanehSanjTrip($from: Location!, $to: Location!, $dateTime: DateTime!, $arriveBy: Boolean!, $modes: Modes!) {
  trip(from: $from, to: $to, dateTime: $dateTime, arriveBy: $arriveBy, modes: $modes, numTripPatterns: 5) {
    routingErrors { code description inputField }
    tripPatterns {
      expectedStartTime expectedEndTime duration walkTime walkDistance
      legs {
        mode ride duration distance expectedStartTime expectedEndTime realtime
        pointsOnLink { points }
        line { id publicCode name transportMode }
        fromPlace { name latitude longitude }
        toPlace { name latitude longitude }
        interchangeFrom { staySeated }
        interchangeTo { staySeated }
      }
    }
  }
}"""


def normalize_transmodel(raw, origin, travel, response_id, settings):
    """Map fields from the discovered Transmodel v3 schema; transfer count is absent."""
    mapped = {
        "startTime": raw.get("expectedStartTime"), "endTime": raw.get("expectedEndTime"),
        "duration": raw.get("duration"), "walkTime": raw.get("walkTime"), "walkDistance": raw.get("walkDistance"),
        "numberOfTransfers": None, "legs": [],
    }
    if not isinstance(raw.get("legs"), list):
        raise ValueError("Missing Transmodel legs")
    for leg in raw["legs"]:
        mode = leg.get("mode")
        mapped["legs"].append({
            "mode": "WALK" if mode == "foot" else mode.upper() if isinstance(mode, str) else None,
            "transitLeg": leg.get("ride"), "duration": leg.get("duration"), "distance": leg.get("distance"),
            "startTime": leg.get("expectedStartTime"), "endTime": leg.get("expectedEndTime"),
            "realTime": leg.get("realtime"), "legGeometry": leg.get("pointsOnLink"),
            "route": leg.get("line"), "from": leg.get("fromPlace"), "to": leg.get("toPlace"),
        })
    result = normalize_itinerary(mapped, origin, travel, response_id, settings, timestamp_unit="iso8601")
    for original, normalized in zip(raw["legs"], result["legs"]):
        normalized["interchange_from"] = original.get("interchangeFrom")
        normalized["interchange_to"] = original.get("interchangeTo")
    return result