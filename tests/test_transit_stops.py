"""Stop proximity tests are offline and never infer routes from straight lines."""
import json
import random

import pytest

from backend.app.transit_stops import CATALOG_VERSION, StopCatalog, build_catalogue, haversine_meters


def write_catalogue(tmp_path, stops):
    path = tmp_path / "stops.json"
    path.write_text(json.dumps({"schema_version": CATALOG_VERSION, "dataset_version": "test-v1", "stops": stops}), encoding="utf-8")
    return StopCatalog(path)


def stop(identifier, latitude, longitude, mode="bus"):
    return {"stop_id": identifier, "name": identifier, "latitude": latitude, "longitude": longitude, "stop_type": mode}


def test_haversine_known_distances_and_coordinates():
    assert haversine_meters(0, 0, 0, 1) == pytest.approx(111_195.08, abs=0.02)
    assert haversine_meters(35.7, 51.4, 35.7, 51.4) == 0
    assert haversine_meters(0, 179.999, 0, -179.999) == pytest.approx(222.39016, abs=0.02)
    with pytest.raises(ValueError):
        haversine_meters(float("nan"), 51.4, 35, 51)


def test_catalogue_nearest_and_stable_ties(tmp_path):
    catalogue = write_catalogue(tmp_path, [stop("b", 35.7, 51.4), stop("a", 35.7, 51.4, "metro"), stop("c", 35.8, 51.4)])
    result = catalogue.nearest(35.7, 51.4, 2)
    assert [item["stop_id"] for item in result] == ["a", "b"]
    assert result[0]["stop_type"] == "metro"
    assert result[0]["dataset_version"] == "test-v1"
    assert "walk_distance_meters" not in result[0]


def test_spherical_index_matches_exhaustive_haversine(tmp_path):
    rng = random.Random(42)
    rows = [stop(f"stop-{index:04}", rng.uniform(-89, 89), rng.uniform(-180, 180)) for index in range(900)]
    catalogue = write_catalogue(tmp_path, rows)
    for _ in range(25):
        lat, lon = rng.uniform(-90, 90), rng.uniform(-180, 180)
        expected = sorted(rows, key=lambda item: (haversine_meters(lat, lon, item["latitude"], item["longitude"]), item["stop_id"]))[:5]
        assert [item["stop_id"] for item in catalogue.nearest(lat, lon, 5)] == [item["stop_id"] for item in expected]


def test_catalogue_unavailable_empty_or_invalid_never_invents_stops(tmp_path):
    missing = StopCatalog(tmp_path / "absent.json")
    assert missing.status == "unavailable" and missing.nearest(35.7, 51.4) == []
    assert write_catalogue(tmp_path, []).status == "empty"
    invalid = write_catalogue(tmp_path, [stop("x", 35.7, 51.4, "unknown")])
    assert invalid.status == "invalid" and invalid.version is None
    with pytest.raises(ValueError):
        missing.nearest(35.7, 51.4, 0)


def test_import_uses_actual_serving_modes_and_content_versions():
    response = {"data": {"quays": [
        {"id": "bus", "name": "Metro street", "latitude": 35.7, "longitude": 51.4, "lines": [{"id": "line-1", "transportMode": "bus"}]},
        {"id": "unknown", "name": "Metro station", "latitude": 35.8, "longitude": 51.5, "lines": []},
        {"id": "metro", "name": "Station", "latitude": 35.9, "longitude": 51.6, "lines": [{"id": "line-2", "transportMode": "metro"}]},
    ]}}
    first = build_catalogue(response, profile={}, schema_sha256="test", fetched_at="first")
    second = build_catalogue(response, profile={}, schema_sha256="test", fetched_at="second")
    assert first["dataset_version"] == second["dataset_version"]
    assert first["counts"] == {"raw_quays": 3, "usable_stops": 2, "excluded": 1, "bus": 1, "metro": 1}
    assert first["stops"][0]["stop_type"] == "bus"
    response["data"]["quays"][0]["longitude"] = 51.41
    changed = build_catalogue(response, profile={}, schema_sha256="test")
    assert changed["dataset_version"] != first["dataset_version"]
    with pytest.raises(ValueError):
        build_catalogue({"errors": [{"message": "broken"}], "data": response["data"]}, profile={}, schema_sha256="test")
