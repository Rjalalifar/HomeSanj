"""Versioned OTP stop catalogue with an exact spherical nearest-neighbour index."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
from typing import Any

import httpx

CATALOG_VERSION = "otp-stops-1"
EARTH_RADIUS_METERS = 6_371_008.8
STOP_QUERY = """query HomesanjStops {
  quays { id name latitude longitude lines { id transportMode } }
  serverInfo { version buildTime gitCommit internalTransitModelTimeZone }
}"""


def _coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValueError("Coordinates must be numeric")
    lat, lon = float(latitude), float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Coordinates are outside WGS84 bounds")
    return lat, lon


def haversine_meters(latitude: float, longitude: float, other_latitude: float, other_longitude: float) -> float:
    """Return great-circle metres, independent of the pedestrian street network."""
    latitude, longitude = _coordinates(latitude, longitude)
    other_latitude, other_longitude = _coordinates(other_latitude, other_longitude)
    first, second = math.radians(latitude), math.radians(other_latitude)
    dlat, dlon = second - first, math.radians(other_longitude - longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(first) * math.cos(second) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(max(0.0, min(1.0, value))))


def _sphere(latitude: float, longitude: float) -> tuple[float, float, float]:
    lat, lon = math.radians(latitude), math.radians(longitude)
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)


@dataclass
class _Node:
    index: int
    axis: int
    left: _Node | None = None
    right: _Node | None = None


class StopCatalog:
    """Load once per worker; nearest queries never contact OTP or generate stops."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("OTP_STOPS_PATH", "data/otp/stops.json"))
        self.status = "unavailable"
        self.version: str | None = None
        self.metadata: dict[str, Any] = {}
        self.stops: list[dict] = []
        self._points: list[tuple[float, float, float]] = []
        self._root: _Node | None = None
        if not self.path.is_file():
            return
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("schema_version") != CATALOG_VERSION or not isinstance(document.get("stops"), list):
                raise ValueError("Unsupported stop catalogue schema")
            if not isinstance(document.get("dataset_version"), str) or not document["dataset_version"]:
                raise ValueError("Stop dataset version is required")
            seen = set()
            for item in document["stops"]:
                if not isinstance(item.get("stop_id"), str) or not item["stop_id"] or item["stop_id"] in seen:
                    raise ValueError("Stop identifiers must be present and unique")
                if item.get("stop_type") not in ("metro", "bus") or not isinstance(item.get("name"), str):
                    raise ValueError("Stop mode and name must be explicit")
                lat, lon = _coordinates(item["latitude"], item["longitude"])
                seen.add(item["stop_id"])
                self.stops.append({**item, "latitude": lat, "longitude": lon})
            self.stops.sort(key=lambda item: item["stop_id"])
            self.version = document["dataset_version"]
            self.metadata = {key: value for key, value in document.items() if key != "stops"}
            self._points = [_sphere(item["latitude"], item["longitude"]) for item in self.stops]
            self._root = self._build(list(range(len(self.stops))))
            self.status = "ok" if self.stops else "empty"
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.status, self.stops, self.version = "invalid", [], None
            self._points, self._root = [], None

    def _build(self, indices: list[int], depth: int = 0) -> _Node | None:
        if not indices:
            return None
        axis = depth % 3
        indices.sort(key=lambda index: (self._points[index][axis], self.stops[index]["stop_id"]))
        mid = len(indices) // 2
        return _Node(indices[mid], axis, self._build(indices[:mid], depth + 1), self._build(indices[mid + 1:], depth + 1))

    def nearest(self, latitude: float, longitude: float, limit: int = 1) -> list[dict]:
        latitude, longitude = _coordinates(latitude, longitude)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("Nearest stop limit must be between 1 and 20")
        if self.status != "ok":
            return []
        point = _sphere(latitude, longitude)
        heap: list[tuple[float, int]] = []

        def visit(node: _Node | None):
            if node is None:
                return
            target = self._points[node.index]
            squared = sum((left - right) ** 2 for left, right in zip(point, target))
            candidate = (-squared, -node.index)
            if len(heap) < limit:
                heapq.heappush(heap, candidate)
            elif candidate > heap[0]:
                heapq.heapreplace(heap, candidate)
            difference = point[node.axis] - target[node.axis]
            near, far = (node.left, node.right) if difference < 0 else (node.right, node.left)
            visit(near)
            if len(heap) < limit or difference ** 2 <= -heap[0][0]:
                visit(far)

        visit(self._root)
        results = []
        for _, negative_index in heap:
            item = self.stops[-negative_index]
            results.append({**item, "straight_line_meters": haversine_meters(latitude, longitude, item["latitude"], item["longitude"]),
                            "dataset_version": self.version})
        return sorted(results, key=lambda item: (item["straight_line_meters"], item["stop_id"]))


def build_catalogue(response: dict, *, profile: dict, schema_sha256: str, fetched_at: str | None = None) -> dict:
    """Classify quays only from their actual serving lines, never from their names."""
    if response.get("errors") or not isinstance(response.get("data", {}).get("quays"), list):
        raise ValueError("OTP did not return a complete stop response")
    stops, excluded, seen = [], [], set()
    for quay in response["data"]["quays"]:
        stop_id = quay.get("id")
        lines = quay.get("lines") or []
        supported = sorted({line.get("transportMode") for line in lines} & {"bus", "metro"})
        if not supported:
            excluded.append({"stop_id": stop_id, "reason": "no_verified_bus_or_metro_service"})
            continue
        if not isinstance(stop_id, str) or not stop_id or stop_id in seen:
            raise ValueError("OTP stop identifiers must be unique")
        if not isinstance(quay.get("name"), str):
            raise ValueError("OTP stop name is missing")
        latitude, longitude = _coordinates(quay["latitude"], quay["longitude"])
        seen.add(stop_id)
        stops.append({"stop_id": stop_id, "name": quay["name"], "latitude": latitude, "longitude": longitude,
                      "stop_type": "metro" if "metro" in supported else "bus", "served_modes": supported,
                      "line_ids": sorted({line["id"] for line in lines if line.get("transportMode") in supported}),
                      "coordinate_kind": "otp_quay", "entrance_available": False})
    stops.sort(key=lambda item: item["stop_id"])
    stable = {"schema_version": CATALOG_VERSION, "stops": stops, "graph_version": profile.get("graph_version"),
              "source_kind": "recorded_otp", "schedule_basis": profile.get("schedule_basis", "unknown")}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {**stable, "dataset_version": CATALOG_VERSION + "-" + digest[:20],
            "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
            "source": {"base_url": profile.get("base_url"), "api_path": profile.get("api_path"), "query": STOP_QUERY,
                       "schema_sha256": schema_sha256, "otp_server": response["data"].get("serverInfo"),
                       "response_sha256": hashlib.sha256(json.dumps(response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()},
            "counts": {"raw_quays": len(response["data"]["quays"]), "usable_stops": len(stops), "excluded": len(excluded),
                       "bus": sum(item["stop_type"] == "bus" for item in stops), "metro": sum(item["stop_type"] == "metro" for item in stops)},
            "excluded": excluded,
            "limitations": ["Stop coordinates are supplied by the installed OTP graph, not independently surveyed.",
                            "No mapped pedestrian entrance is present in this catalogue; routing targets the quay coordinate.",
                            "Schedule authenticity is independent of observed stop locations and is not assumed.",
                            "No claim of complete citywide bus or metro coverage is made.",
                            "When graph_version is unavailable, content versioning detects stop changes but cannot detect street graph rebuilds; walking cache must expire."]}


def import_live(output: str | Path = "data/otp/stops.json", profile_path: str | Path = "data/otp/api-profile.json") -> dict:
    """Refresh explicitly from the already verified endpoint; searches never call this."""
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    schema_path = Path(profile_path).with_name("introspection.json")
    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes)["data"]["__schema"]
    lookup = {item["name"]: item for item in schema["types"]}
    for name, fields in {"Quay": {"id", "name", "latitude", "longitude", "lines"}, "Line": {"id", "transportMode"}}.items():
        if not fields <= {field["name"] for field in lookup.get(name, {}).get("fields") or []}:
            raise ValueError("The saved OTP schema does not support the stop query")
    if not profile.get("routing_api_verified") or profile.get("api_type") != "transmodel_v3":
        raise ValueError("Stop import requires the verified installed Transmodel API")
    api_path = profile.get("api_path", "")
    if not api_path.startswith("/") or api_path == "/" or "://" in api_path:
        raise ValueError("Invalid verified OTP API path")
    response = httpx.post(profile["base_url"].rstrip("/") + api_path, json={"query": STOP_QUERY}, timeout=30)
    response.raise_for_status()
    if len(response.content) > 20_000_000:
        raise ValueError("OTP stop response exceeds the configured import bound")
    raw = response.json()
    document = build_catalogue(raw, profile=profile, schema_sha256=hashlib.sha256(schema_bytes).hexdigest())
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_name("stops-source.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return {"status": "ok", "dataset_version": document["dataset_version"], **document["counts"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-live", action="store_true", required=True)
    parser.add_argument("--output", default="data/otp/stops.json")
    parser.add_argument("--profile", default="data/otp/api-profile.json")
    arguments = parser.parse_args()
    print(json.dumps(import_live(arguments.output, arguments.profile)))
