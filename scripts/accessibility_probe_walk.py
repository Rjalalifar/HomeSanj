"""Verify pedestrian routing against the installed OTP using public sample points."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.routing import OTPAdapter, OTPSettings, TRANSMODEL_QUERY
from backend.app.transit_stops import StopCatalog
from backend.app.db import Database, Listing
from backend.app.config import Settings


def main():
    settings = OTPSettings.from_env()
    if settings.fixture_mode or not settings.api_verified or settings.api_type != "transmodel_v3":
        raise ValueError("This contract requires the verified live Transmodel instance")
    source = Path("data/otp/introspection.json")
    schema = json.loads(source.read_text(encoding="utf-8"))["data"]["__schema"]
    types = {item["name"]: item for item in schema["types"]}
    mode_fields = {field["name"]: field for field in types["Modes"]["inputFields"]}
    proof = {name: mode_fields[name]["description"] for name in ("directMode", "transportModes")}
    database = Database(Settings.from_env().database_url)
    with database.session() as session:
        listing = session.scalar(select(Listing).where(Listing.is_synthetic.is_(True)).order_by(Listing.property_id).limit(1))
        if listing is None:
            raise ValueError("The existing synthetic property dataset is required")
        origin = {key: listing.payload[key] for key in ("latitude", "longitude")}
        property_id = listing.property_id
    stop = StopCatalog().nearest(**origin)[0]
    destination = {key: stop[key] for key in ("latitude", "longitude")}
    now = datetime.now(ZoneInfo("Asia/Tehran")).replace(microsecond=0)
    travel = {"date": now.date().isoformat(), "time": now.time().isoformat(), "time_mode": "DEPART_AT",
              "timezone": "Asia/Tehran", "destination": destination, "include_walk_only": True, "modes": []}
    variables = {"from": {"coordinates": origin}, "to": {"coordinates": destination}, "dateTime": now.isoformat(),
                 "arriveBy": False, "modes": {"directMode": "foot", "transportModes": []}}
    request = {"query": TRANSMODEL_QUERY, "variables": variables}
    target = Path("data/otp")
    (target / "stops-walk-request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"checked_at": now.isoformat(), "fixture_mode": False, "status": "not_run", "api_path": settings.api_path,
              "otp_version": "2.10.0", "graph_version": settings.graph_version, "schedule_basis": settings.schedule_basis,
              "schema_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "schema_evidence": proof,
              "point_source": "Existing synthetic property origin; nearest imported OTP quay coordinate.", "property_id": property_id,
              "stop_id": stop["stop_id"], "stop_dataset_version": stop["dataset_version"], "straight_line_meters": stop["straight_line_meters"]}
    try:
        response = httpx.post(settings.base_url + settings.api_path, json=request, timeout=settings.timeout_seconds)
        response.raise_for_status()
        raw = response.json()
        result = OTPAdapter(settings)._normalize_response(raw, origin, travel, "walking_contract_public_sample")
        (target / "stops-walk-response.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        walking = [item for item in result["itineraries"] if item["legs"] and all(leg["mode"] == "WALK" and leg["is_transit"] is False for leg in item["legs"])]
        verified = bool(walking) and len(walking) == len(result["itineraries"]) and all(item["walk_duration_seconds"] is not None and item["walk_distance_meters"] is not None for item in walking)
        report.update({"status": "pass" if verified else "fail", "http_status": response.status_code,
                       "routing_status": result["status"], "walking_api_verified": verified, "itinerary_count": len(walking),
                       "measurements": [{key: item[key] for key in ("total_duration_seconds", "walk_duration_seconds", "walk_distance_meters", "start_datetime", "end_datetime", "source_kind")} for item in walking]})
    except (httpx.HTTPError, ValueError, KeyError) as error:
        report.update({"status": "fail", "walking_api_verified": False, "error_type": type(error).__name__})
    (target / "stops-walk-contract-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("status", "walking_api_verified", "itinerary_count", "straight_line_meters", "measurements")}))


if __name__ == "__main__":
    main()
