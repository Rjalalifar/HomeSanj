# Automatic property accessibility handoff

The existing React/FastAPI/SQLAlchemy application now supports automatic property accessibility alongside legacy saved searches. It reuses the canonical listing inventory, property/location filters, durable routing worker, SQLite route cache, verified OTP adapter, and Phase-3 evidence/replay workflow. No OTP installation or graph rebuild is required.

## Run and state contract

From the repository root, with the existing environment and dependencies:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

The UI is `http://127.0.0.1:8000/`. Build the frontend with `npm.cmd run build` from `frontend` when source changes. Existing OTP remains at `http://127.0.0.1:8821`; its discovered Transmodel path is `/otp/transmodel/v3`, recorded in `data/otp/api-profile.json`. A reachable homepage alone does not establish routing availability.

`GET /api/state/default` opts into `accessibility: {enabled: true, semantics_version: "accessibility-1", time_policy: "request_execution"}`. The optional destination remains `state.travel.destination`, with latitude, longitude and `confirmed: true`. Without a destination, the profile is `nearby_stop`; with one, it is `destination`. States without enabled accessibility keep legacy journey semantics. Migration 5 adds `snapshot_candidates.accessibility_snapshot` without replacing existing records.

Automatic execution captures the current `Asia/Tehran` instant in `effective_at`. Destination routing uses that time with `DEPART_AT`; legacy manual journey constraints are cleared for this automatic execution. The frozen effective time and calculation time distinguish a current request from reused evidence.

| Operation | Existing endpoint |
|---|---|
| Submit Normal / Advanced Search | `POST /api/searches`, `POST /api/advanced/searches` |
| Poll or sort a stored result | `GET /api/searches/{request_id}?sort=stop_walk_time_asc` |
| Saved candidate/evaluation evidence | `GET /api/searches/{request_id}/snapshot` |
| Replay saved evidence | `POST /api/searches/{request_id}/replay` |
| Cancel / continue bounded evaluation | `POST /api/searches/{request_id}/cancel`, `/continue` |

These routes retain existing session ownership. Sorting a stored result reads saved evidence and does not create a new routing request. Destination coordinates are not query-string parameters.

## Result and ranking semantics

Property/location conditions determine the visible candidate set. An unavailable access route does not remove an otherwise eligible home. Each result has an independent `accessibility` object containing `mode`, `status`, `nearest_stop`, `walking_stop`, `stop_dataset_version`, `straight_line_meters`, `walk_duration_seconds`, `walk_distance_meters`, `total_duration_seconds`, `effective_at`, `calculated_at`, and `cache_policy_version`.

Without a destination, the nearest geographically located stop is selected from the versioned installed OTP stop catalogue. Haversine distance is independent of pedestrian routing. OTP calculates walking to that stop's quay coordinate using an explicit walk-only profile. `walking_scope=nearest_geographic_stop_only` does not claim the fastest walk among all stops. With a destination, route numbers come from one selected returned itinerary. Failed, missing or uncomputed route values remain null; proximity can remain known when walking fails.

`accessibility-ranker-1` uses separate recommended profiles:

| Profile | Cost weights | Default reference scales |
|---|---|---|
| Destination | rent 0.30, deposit 0.20, total duration 0.35, walking duration 0.15 | 30 million toman, 1 billion toman, 3,600 seconds, 900 seconds |
| Nearby stop | rent 0.30, deposit 0.20, walking duration 0.35, straight-line distance 0.15 | 30 million toman, 1 billion toman, 900 seconds, 1,000 meters |

The reported policy exposes actual weights/scales: component cost is `weight * min(value / scale, 1)`; unknown is 1. Positive explicit caps replace reference scales where supported. The existing controlled `rent_weight_multiplier` is normalized into these weights. These are costs, not probabilities. No transfer count or amenity bonus enters this profile. Known values precede unknowns for metric sorts; ties use property ID. Semantic priority affects exact recommended-cost ties only.

Contextual sorts are `travel_time_asc` / `walk_time_asc` for a destination, and `stop_walk_time_asc` / `stop_distance_asc` without one; `recommended`, `rent_asc` and `deposit_asc` remain available. Legacy `transfers_asc` is rejected for automatic accessibility.

Evaluation remains bounded by `ROUTING_BATCH_LIMIT` (default 30) and `OTP_MAX_CONCURRENCY` (default 3). Read `candidate_count`, `evaluated_count`, `completion_status`, `subset_method` and `ranking_scope` before interpreting a ranking. A partial evaluation is not a citywide best result. `origin_unknown`, `stops_unavailable`, timeout, API failure and no returned route retain distinct evidence.

## Cache and stop data

`accessibility-cache-1` keys include property ID/dataset and coordinates, destination coordinates, mode/profile, stop ID/dataset when relevant, OTP graph/adapter/API identity, supported modes, fixture mode and schedule basis. Successful results alone enter the cache. Sort changes do not change routing inputs.

| Setting | Default and bounds | Meaning |
|---|---|---|
| `OTP_STOPS_PATH` | `data/otp/stops.json` | Versioned imported catalogue loaded locally |
| `ACCESSIBILITY_WALK_CACHE_SECONDS` | 86,400; clamped to 1–604,800 | Pedestrian evidence expiry, independent of current schedule time |
| `ACCESSIBILITY_TRANSIT_CACHE_SECONDS` | 60; clamped to 1–300 | Scheduled route time bucket and expiry |

When the graph version is unavailable, cache expiry is capped at 300 seconds. A cache hit preserves the original routing time and changes `live_otp` evidence to `recorded_otp`. Replay uses stored evidence and hashes; it does not call today's OTP. A destination, coordinate, stop dataset, graph, API or effective transit-time-window change invalidates the relevant key.

The recorded catalogue has 2,460 usable stops. Stop type is derived from actual serving-line modes returned by OTP. Coordinates are quay locations; mapped pedestrian entrances and complete citywide coverage are not established. The current recorded contract has unknown graph version and schedule basis. A successful live API response does not establish official or realtime schedules.

Refresh stops explicitly only when required; search and rendering never import them:

```powershell
.\.venv\Scripts\python.exe -m backend.app.transit_stops --import-live --output data/otp/stops.json --profile data/otp/api-profile.json
```

## Verification commands and evidence

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_accessibility.py tests/test_accessibility_ranking.py tests/test_accessibility_precision.py tests/test_accessibility_otp_replay.py tests/test_accessibility_explanations.py tests/test_transit_stops.py
.\.venv\Scripts\python.exe scripts/accessibility_probe_walk.py
.\.venv\Scripts\python.exe scripts/accessibility_stop_benchmark.py
.\.venv\Scripts\python.exe scripts/verify_accessibility.py
cd frontend
npm.cmd test
npm.cmd run build
npx.cmd playwright test --config playwright.accessibility.config.ts
```

The live checks require the existing local OTP service. `verify_accessibility.py` copies only synthetic listings into an isolated SQLite database and bounds routing batches to three; it does not route all 5,655 listings or invoke a paid model. The Playwright configuration owns an isolated backend on port 8001 and exercises actual local OTP plus the existing Advanced/internal integration scenarios. It requires the existing Qdrant service for Advanced Search.

Use the latest artifacts as execution evidence, rather than treating these commands or this document as a PASS assertion:

- `docs/accessibility-pytest.xml`: backend regression result and timestamp.
- `docs/accessibility-browser-report.json`: actual browser statuses, failures and attachments.
- `docs/accessibility-live-performance-report.json`: created by the bounded live verification; absent until that command completes.
- `data/otp/stops-walk-contract-report.json` and saved request/response: recorded live pedestrian contract.
- `data/otp/stops-performance-report.json`: nearest-stop lookup over existing synthetic listings; this is not end-to-end routing latency.

The recorded pedestrian contract demonstrates separate values for 328.48 meters straight-line proximity, 510.51 meters network walking, and 387 seconds walking. It is evidence for that specific origin/stop/request, not a guaranteed result for other homes or times. Required service/browser reruns and their final status are reported by the latest corresponding artifact; unavailable services must remain explicitly unavailable rather than replaced with fabricated routes.

## Final verification recorded on 2026-10-22

The existing full regression artifact records 160 passing tests. The subsequent targeted precision/cache run passed 9 tests, including one added precision case; together these cover 161 unique backend tests without claiming another full-suite run. See `docs/accessibility-precision-pytest.xml` for the targeted result.

All 8 selected browser scenarios have passing results across the initial run and service-ready rerun: 6 passed in `docs/accessibility-browser-before-service-start.json`, and the remaining 2 passed in `docs/accessibility-browser-report.json` after the existing OTP and Qdrant services were running. The earlier service-dependent failures remain visible in the saved first report.

`docs/accessibility-live-performance-report.json` records PASS for the bounded live check: 5,655 saved synthetic candidates, 2,460 stops, 6 actual OTP requests, peak concurrency 3, 3 pedestrian cache hits on repeat search, and zero OTP calls from sorting or the repeat stop search. Frozen replay returned `ok` with zero network calls. Observed snapshot/proximity work took 3,682 ms, three walking routes 1,519 ms, sorting 1,222 ms, cached routes 1,088 ms, and the destination batch 1,710 ms on this machine. These are one-run measurements, not latency guarantees. Only the bounded subset was routed; `completion_status=partial`, graph version remains null, and schedule basis remains unknown.
The authoritative consolidated current status is [accessibility-final-verification.json](accessibility-final-verification.json).
