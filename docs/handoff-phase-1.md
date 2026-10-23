# Phase 1 handoff — خانه‌سنج

Last verification: 2026-10-20, local Windows host, Python 3.13.5, Node 20.19.4.
The initial workspace was empty and had no AGENTS.md or Git history. User overrides:
React instead of Vue; SQLAlchemy 2 required; all code comments/docstrings English.

## Delivered architecture

- React 19 + TypeScript + Vite, Persian RTL form, Leaflet, frontend Turf point-in-polygon.
- FastAPI/Pydantic canonical state and itinerary models, generated JSON Schema/TypeScript.
- SQLAlchemy 2 / SQLite, additive migration 1, immutable candidate snapshots, route evidence,
  durable leased worker, bounded batches, shared database lease, cancellation and cache.
- Shapely/PyProj authoritative geometry checks, pinned raw data, reproducible transform/seed.
- CSV/JSON importer fixtures, conservative offline Persian parser, optional AvalAI provider.
- No OTP installation, graph build, parallel routing engine, tunnel or port 8821 listener added.
- No accounts, scraping, payments, price prediction or phase-2/3 features implemented.

## Run

The workspace already has `.venv`, frontend dependencies/build, prepared boundaries and a
seeded local database. From `E:\Projects\Golrang\Task`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and http://127.0.0.1:8000/docs. If port 8000 is already serving
this app, use that instance. Do not use port 8821 for the app. Fresh-install commands
are in README.md. `requirements-lock.txt` and `frontend/package-lock.json` pin the
resolved environment. Runtime database and `.env` are intentionally ignored by Git.

## Boundaries and seed: actual results

`data/source-manifest.json` records pinned URLs, source hashes, original CRS metadata,
license uncertainty, conversion version `geometry-v1` and dataset `tehran-2020-v1`.
Original downloads remain in `data/raw/`; repair records retain original geometry.

`data/validation-report.json` reports:

| Measurement | Actual result |
| --- | ---: |
| Neighborhood features | 377 |
| District features | 22 |
| Repaired self-intersections | 2 |
| Neighborhood overlap pairs above 1 m² | 120 |
| Neighborhoods above 1% outside source-assigned district | 108 |
| Neighborhoods above 50% outside source-assigned district | 11 |

These are features in the 2020 source, not a current official count. Boundary validity
date is unknown. District WGS84 is inferred; neighborhood CRS84 is declared. No source
district assignments were corrected. City-wide coverage is unverified. OSM tiles are
independent and attributed. No explicit upstream data license was identified.

The initial vertical seed generated 30 listings in 2 neighborhoods. Full seed generated
**5655 listings**, 1885 each in demo_a/demo_b/demo_c, with **zero shortages**. A repeat run produced the same identity hash, inserted zero rows and skipped all 5655 existing rows (data/seed-repeat-report.json). It inserted
5625 new rows and skipped the prior 30. See `data/seed-small-report.json` and
`data/seed-report.json`. The seed is 2026 and points per series per neighborhood is 5.
Synthetic publication dates are deterministic fixture values, not fresh collection dates.

IDs depend on source type, district, normalized name and canonical geometry hash.
Sampling occurs in EPSG:32639, weighted by component area, outside holes, with ambiguous
neighborhood points rejected. Candidate attempts are bounded to 1000 per point and
bounding-box draws to 100 per candidate. Existing IDs are never overwritten by seed/import.

## Actual OTP discovery and connection

- Base: `http://127.0.0.1:8821`.
- Version observed from `serverInfo`: **2.10.0**.
- API: **Transmodel GraphQL v3**, exact path **`/otp/transmodel/v3`**.
- Discovery evidence: root debug UI -> its linked JavaScript -> exact path -> live introspection.
- `root_reachable=true`, `routing_api_verified=true`, `fixture_mode=false`.
- A real coordinate request on an observed line and an active service date returned **5 valid itineraries**.
- `data/otp/connection-report.json`, `introspection.json`, `server.json`,
  `contract-http-request.json`, `contract-input.json`, `contract-result.json` and
  `api-profile.json` retain the evidence. Settings bind verification to base/path/API type.
- `.env` records `OTP_API_PATH=/otp/transmodel/v3`, separately from the base URL.
  The portable `.env.example` leaves discovery fields empty.

Only **BUS** has been observed and enabled. No claim of metro/BRT/all-city coverage is made.
The global `lines` query returned an upstream GraphQL DataFetchingException; narrower quay,
journey-pattern, service-date and trip queries succeeded. This does not prevent routing.

The chosen service's active dates were read from the API; the contract date was 2026-10-20.
The data contains OSM-derived IDs, but those IDs alone do not establish schedule provenance.
`schedule_basis=unknown`, `realtime_status=unavailable` for observed transit, and graph/feed
version is unknown. Do not label these schedules official. If independent evidence confirms
synthetic scheduling, set `OTP_SCHEDULE_BASIS=synthetic_schedule`; the UI then labels it
«برآورد مبتنی بر برنامهٔ فرضی».

**Transfer-count limitation:** this installed TripPattern schema has no aggregate transfer
count. `transfers=null` is preserved; interchange evidence is retained. An active maximum
transfers constraint gets `unknown`, so it cannot pass. No ride-legs-minus-one guess is made.
Walking access, intermediate transfers and egress are summed from all walking legs, with
summary reconciliation. The total itinerary duration already includes waiting. Time from
requested departure to actual start is separate (`request_to_start_seconds`).

Rerun the real contract, without paid APIs:

```powershell
.\.venv\Scripts\python.exe -m backend.app.otp_probe --contract data/otp/contract-input.json
```

The recorded date must remain within the installed feed's active dates. For a newly installed
OTP API, run discovery first with `python -m backend.app.otp_probe`, inspect the saved schema
and validate a coordinate request before writing a new verified profile. Discovery alone is
not routing verification. The implementation never routes against `/`.

A second vertical check evaluated **3 of 15** stored demo candidates, all three receiving
eligible live routes. It correctly reports `partial` and `evaluated_subset` in
`docs/live-search-report.json`. Ordinary filtering returned all 5655 property candidates,
with the first 100 displayed, as recorded in `docs/api-smoke-report.json`.

Docker/cloud were **not tested**. For Docker Desktop verify host.docker.internal:8821 from
inside the backend container; Linux may also need host-gateway mapping. Loopback binding and
firewall can still block it. A different host cannot reach the user's loopback. No exposure
or tunnel was created.

## State, API, evidence, and phase-2 integration

See `docs/phase-1-contract.md` and generated `shared/contracts.schema.json`.
Canonical code: `backend/app/contracts.py`; regenerate with `python -m backend.app.export_schema`.
Do not maintain independent frontend/parser/snapshot interpretations.

- Null condition means unset; null listing attribute means unknown. False required flags mean
  no requirement. Deletion restores documented defaults. Patch is allowlisted and atomic,
  not RFC 6902. User strings are never interpolated into SQL or GraphQL.
- Within neighborhood IDs: OR; within district IDs: OR; between groups and conditions: AND.
  District filters use point-in-district geometry. Contradictions and ambiguous memberships
  remain visible and are never silently cleared.
- Confirm one destination on the map. Date/time/time mode are explicit, in Asia/Tehran.
  Only itinerary duration is supported as the duration-cap scope. Natural-language requests
  for elapsed time from an earlier clock time remain unsupported rather than misinterpreted.
- Every search creates a request and snapshot. Same need retains task ID; destination change
  or explicit new_need creates a new task. Parent ID and state revision are recorded.
- All property candidates and provenance are snapshotted before routing. Evaluations retain
  alternatives, selected route, per-condition verdicts, response ID and raw response.
  Dataset/schema/parser/ranker/adapter/graph and LLM role settings are recorded.
- Replay reads persisted evidence with no external calls. It is not a fresh routing evaluation.
- Defaults: 30 candidates per batch, concurrency 3. A database-wide lease prevents two workers
  from independently exceeding the intended concurrency. Crash recovery waits for lease expiry;
  completed evaluations are retained. Cancellation drains active calls; continuing resumes
  remaining candidates in deterministic order.
- Cache keys include origin, destination, datetime, time mode, effective modes/options,
  adapter/API/graph identity and fixture state. Cache TTL defaults to one hour when graph version
  is unavailable. Cached live responses become `recorded_otp`, not new live calls.
- Preference reranks the same candidate snapshots and can reuse cached alternatives. All card
  metrics come from one eligible itinerary. Partial rankings are not global recommendations.
- UI currently displays the first 100 results; API supports offset/limit (maximum 200).
  Snapshot contains all candidates. Richer browsing/comparison belongs to phase 2.

## AvalAI

`LLM_ENABLED=false`, no backend key configured; real smoke test **not_run**. No paid request
was made. See `docs/avalai-smoke-report.json`. Offline parser examples and manual form work.
Provider uses the compatible SDK, `/v1/models` account check and `/v1/chat/completions`.
Public catalog membership is not used as account-access proof. No json_schema capability is
claimed. Each role has its own model/version; default model is gemini-3.6-flash with no silent
fallback. Judge is off; no automatic experiment proposer runs in phase 1.

To test after adding a backend-only key and explicitly enabling LLM:

```powershell
.\.venv\Scripts\python.exe -m backend.app.cli avalai-smoke --allow-paid --max-requests 1
```

This is an explicit paid-capable operation: at most one attempt, 64 output tokens per model,
no retry, plus the configured daily request/token reservation ceilings. If roles use different
models the one-request budget may be insufficient; each model must be verified deliberately.
Invalid JSON cannot change state; one repair maximum. 401/403 are not retried; 429/5xx/timeouts
have bounded retries, and every attempt reserves budget before sending. Timeouts do not refund
potentially spent quota. No credentials appear in frontend, URLs or logs.

## Verification

Machine-readable summary: `docs/verification-report.json`.

- Backend offline suite: **49 passed** (money/null, geometry/holes/multipart, seed/IDs,
  ambiguity, real counts, alternate itinerary selection, walking sums, time/coordinates,
  midnight/arrive/depart, cache invalidation, timeout/no-route, concurrency, cancellation,
  lease recovery, importer duplicates, parser/budget and snapshot/API contracts).
- Frontend unit tests: **3 passed**.
- TypeScript + Vite production build: **passed**.
- Headless Edge browser flow: **passed**; manual search, synthetic labels, parser preview,
  destination confirmation, mobile width, and no JavaScript page errors.
- npm audit after pin updates: **0 vulnerabilities**.
- Live OTP contract: **passed**, five itineraries; vertical live search: three candidates.
- AvalAI smoke and Docker-host networking: **not_run**, for reasons stated above.

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
npx playwright test
```

The browser test expects the server at port 8000 and installed Edge. Screenshots are under
`frontend/test-results/`. The backend suite emits an upstream Starlette/AnyIO deprecation
warning; all assertions pass. Tests do not call live OTP or paid LLM endpoints.

The remaining external limitations are known transfer-count absence in this API, unverified
schedule/feed provenance, BUS-only observed coverage, and lack of AvalAI account credentials.
They are surfaced rather than replaced with estimates. No required independent foundation
work is left waiting on these external limitations.
