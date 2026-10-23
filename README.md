# Homesanj - Tehran Rental Search

Homesanj helps users find and compare rental apartments in Tehran. It combines budget, property features, neighborhood filters and access to public transport. The application interface is in Persian; this guide is in English.

The demo includes synthetic listings and prices. They demonstrate the product and do not represent current market offers.

## What the application does

- **Normal Search:** filters homes by deposit, monthly rent, size, bedrooms, parking, elevator and location. Browser filtering provides a preview; the backend checks submitted conditions against stored data.
- **Advanced Search:** adds semantic matching through a local multilingual embedding model and Qdrant. It keeps the same property and location constraints. Gemini can optionally select evidence-backed explanation claims through AvalAI.
- **Accessibility:** evaluates each home's route to an optional saved destination. Without a destination, it evaluates walking access to the nearest geographically located stop in the imported stop catalog.
- **Internal evaluation:** provides a protected dashboard and one shared review queue for Normal and Advanced searches. Feedback, annotations and frozen search evidence support offline evaluation and replay.

The stack is React, TypeScript, Vite and Leaflet on the frontend; FastAPI, Pydantic, SQLAlchemy 2 and SQLite on the backend. SQLite stores listings, search snapshots, routing jobs, cached results and review records. The backend calls the existing OpenTripPlanner (OTP) service for routes.

## Local services and addresses

| Service | Address | Purpose |
|---|---|---|
| Application | http://127.0.0.1:8000/ | Built frontend and backend API |
| API documentation | http://127.0.0.1:8000/docs | Interactive API reference |
| Internal dashboard | http://127.0.0.1:8000/internal | Reviewer login, metrics and review queue |
| Vite development server | http://127.0.0.1:5173/ | Frontend development; proxies `/api` to port 8000 |
| Existing OTP service | http://127.0.0.1:8821/ | Route calculation; this port is reserved for OTP |
| Qdrant | http://127.0.0.1:6333/ | Optional semantic search index |

The commands below use Windows PowerShell and run from the repository root unless stated otherwise. The recorded development environment used Python 3.13.5 and Node.js 20.19.4. Docker is needed for the supplied Qdrant container configuration.

## Start an already configured project

If the virtual environment, database and frontend build already exist, start the backend:

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
~~~

Open http://127.0.0.1:8000/. Keep this terminal running. Start the existing OTP service when routing is needed. If Advanced Search is configured, start its existing Qdrant container with:

~~~powershell
docker compose -f compose.qdrant.yml up -d
~~~

Regular startup does not regenerate listings, download the embedding model or rebuild the vector index. The routing worker starts with the backend and stores progress in SQLite. One backend process is sufficient for this local MVP.

### After changing frontend files

Port 8000 serves `frontend/dist`, not the TypeScript source files. Build the frontend after UI changes:

~~~powershell
cd frontend
npm.cmd run build
cd ..
~~~

Reload the browser page after the build finishes. A tab that was already open can continue showing its previously loaded JavaScript; use Ctrl+F5 or reopen the page if necessary.

For frontend development, keep the backend running and use a second terminal:

~~~powershell
cd frontend
npm.cmd run dev
~~~

Then open http://127.0.0.1:5173/ to see source changes through Vite.

## First-time setup

Use this section for a new local installation. Keep an existing `.env` and database when continuing an established project.

### 1. Install dependencies and create local configuration

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
cd frontend
npm.cmd ci
cd ..
~~~

### 2. Prepare boundaries, database and demo listings

~~~powershell
.\.venv\Scripts\python.exe -m backend.app.geo
.\.venv\Scripts\python.exe -m backend.app.cli migrate
.\.venv\Scripts\python.exe -m backend.app.cli seed --seed 2026 --dataset-version tehran-2020-v1 --points-per-series-per-neighborhood 5
~~~

The geometry command prepares and validates the versioned boundary files. The seed command generates reproducible synthetic listings and inserts them without overwriting existing records. The saved report, `data/seed-report.json`, records 5,655 generated listings: five per group in each of 377 neighborhoods, with no shortages in that recorded run.

### 3. Build and run

~~~powershell
cd frontend
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
~~~

Basic property and price searches work without Qdrant or an enabled language model. Route values remain unavailable when OTP cannot provide a valid result.

## Configure accessibility and OTP

Homes are always route origins. A user can save one optional destination in the current browser, change it or remove it.

| Search context | Measurement | Available accessibility sorts in the UI |
|---|---|---|
| Saved destination | OTP itinerary duration and total walking time from the home to that destination | Travel time to destination; walking time to destination |
| No saved destination | Straight-line proximity and OTP walking route to the nearest geographically located stop | Walking time to public transport |

Recommended, rent and deposit sorting are available in both contexts. Straight-line distance can appear as a separate measurement; it is not a walking route or travel-time estimate. Unknown or uncomputed values remain unknown and sort after known values.

Destination routing captures the current `Asia/Tehran` time when a search is submitted. Sorting an existing result reuses stored itineraries and does not request new routes. New routing inputs can require new calculations. Evaluation runs in bounded batches, with three concurrent OTP calls by default; a partial result ranks only the evaluated subset. The UI shows evaluated and candidate counts and supports continuing or cancelling evaluation.

The existing installation was verified as OTP 2.10.0 with the Transmodel API at `/otp/transmodel/v3`. Its recorded profile is `data/otp/api-profile.json`. Relevant `.env` settings are:

~~~dotenv
OTP_BASE_URL=http://127.0.0.1:8821
OTP_API_PATH=/otp/transmodel/v3
OTP_API_TYPE=transmodel_v3
OTP_PROFILE_PATH=data/otp/api-profile.json
OTP_TIMEOUT_SECONDS=20
OTP_MAX_CONCURRENCY=3
OTP_FIXTURE_MODE=false
ROUTING_BATCH_LIMIT=30
~~~

These API settings describe the verified local installation. A reachable OTP homepage alone does not confirm that routing works. For a different installation, verify its version and API before changing the profile. This project does not install OTP, rebuild its graph or replace it with another routing engine.

The imported catalog in `data/otp/stops.json` contains 2,460 usable stops. Coordinates identify quays; mapped entrances and complete city coverage have not been established. The recorded destination-routing profile verifies BUS mode. A metro stop in the catalog does not prove that metro routing is enabled in that profile. The graph version and schedule basis are unknown, and transfer counts are unavailable in the recorded contract.

`live_otp` means a current API call; it does not guarantee realtime or official schedule data. `recorded_otp` identifies reused routing evidence. Synthetic routes require explicit fixture mode. Timeouts, API errors and missing routes remain distinct outcomes.

### If the backend runs in Docker

`127.0.0.1` inside a container refers to that container. On Docker Desktop, use `http://host.docker.internal:8821` only after verifying access from the backend container. Linux Docker Engine may need `extra_hosts: ["host.docker.internal:host-gateway"]`; the host service's bind address and firewall must also allow access. A backend on another machine cannot reach this computer's OTP through its own loopback address.

## Enable Advanced Search with Qdrant

Advanced semantic matching needs the local embedding model and a populated Qdrant index. Run this setup once, after preparing listings:

~~~powershell
docker compose -f compose.qdrant.yml up -d
.\.venv\Scripts\python.exe -m backend.app.semantic download-model --report docs/embedding-verification.json
.\.venv\Scripts\python.exe -m backend.app.semantic index --report docs/qdrant-index-report.json
.\.venv\Scripts\python.exe -m backend.app.semantic reconcile --report docs/qdrant-reconcile-report.json
~~~

The pinned model is `Xenova/multilingual-e5-small`. Model files remain under `runtime/models/`; Qdrant data persists in its Docker volume. `reconcile` checks the index against the canonical SQLite inventory; use `index` after changing listings to apply required index updates. Normal application startup does not repeat the model download.

Qdrant binds to loopback port 6333. If it is unavailable, Normal Search still works and Advanced Search reports degraded semantic matching while retaining the structured candidate set. Property and location constraints remain enforced in both modes.

## Optional Gemini features through AvalAI

Language-model features are disabled by default. Normal Search, manual filters, the limited rule-based parser and deterministic evidence-based explanations work without paid calls. Advanced semantic matching uses the local embedding model independently of Gemini.

AvalAI uses an OpenAI-compatible endpoint at `https://api.avalai.ir/v1`. Parser, explainer, judge and improvement roles have separate settings and versions; their configured model is `gemini-3.6-flash`. Check account access before enabling a role. The application does not silently replace an unavailable model.

Configure credentials only in the backend environment. `LLM_ENABLED` controls parser/explainer availability; `INTENT_LLM_ENABLED` and `ADVANCED_AI_ENABLED` control their respective application paths. Judge and improvement jobs have separate opt-in settings. Responses are validated before use, and each role has request, token and retry budgets.

An explicitly enabled smoke test can incur provider charges:

~~~powershell
.\.venv\Scripts\python.exe -m backend.app.cli avalai-smoke --allow-paid --max-requests 1
~~~

This command also needs the backend key and relevant role enabled. Ordinary seeding and offline unit tests make no paid calls. Keep keys out of source control, browser code, URLs and logs. See `.env.example` and the Phase 3 handoff for role settings and budgets.

## Internal dashboard and shared review

Open http://127.0.0.1:8000/internal. Set `REVIEW_API_TOKEN` in the backend environment before startup, then enter that credential at the reviewer login. For multiple reviewer identities, use `REVIEWER_TOKENS_JSON`. The page keeps the credential in memory; internal APIs require reviewer authentication.

The dashboard has three primary KPIs per search mode:

| KPI | Normal Search | Advanced Search | Meaning |
|---|---|---|---|
| QS@5 | Yes | Yes | Explicit real-user confirmation of a valid home in the first frozen final Top 5; resolved success divided by resolved success plus failure |
| Human-labeled NDCG@5 | Yes | Yes | Ranking quality using human grades 0-3 and exponential gain over fixed, versioned candidate pools |
| P95 finalized-search latency | Yes | No | End-to-end submission-to-valid-final-result latency, including required routing |
| Gemini Evidence Reliance | No | Yes | Supported verifiable Gemini-selected claims divided by evaluated verifiable claims |

Each card includes source mode, sample count, coverage, observation period and policy information when available. Missing valid evidence is shown as `insufficient_data`. The current event model does not provide dependable end-to-end timing, so the P95 card reports missing instrumentation. Missing labels are not zero grades; deterministic explanations do not count as Gemini evidence. Scores from unmatched traffic do not establish that one mode is better.

Both search modes use the same sampler, review queue, annotations and dataset/experiment workflow. The existing list filters by Normal, Advanced or all records; ambiguous historical modes remain unknown. Review samples retain request and snapshot identities. Rejecting all suggestions is a task outcome, not a negative relevance label for every listing. AI suggestions require human review. Automated test annotations remain separate from independent human labels.

## Data provenance and imports

The boundary source is the [Tehran districts and neighborhoods repository](https://github.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson). Pinned sources, checksums and transformation reports are stored under `data/`.

- The files contain 377 neighborhood features and 22 districts. The raw neighborhood filename contains `376`; neither number establishes today's official neighborhood count.
- The source-file commits date to November 2020. Boundary validity dates are unknown. This is not a current official boundary source or a fresh OSM extraction; the OSM basemap is independent.
- The prepared-data specification records two repaired self-intersections, 120 neighborhood pairs overlapping by more than one square meter, 108 neighborhoods with more than 1% outside their assigned district, and 11 with more than 50% outside. Local validation results and repair details are in `data/validation-report.json`.
- A neighborhood's `district_no` is a source assignment, not a verified hierarchy. District filters use the property's point and district geometry. Overlapping memberships remain ambiguous; assignments are not silently corrected.
- Neighborhood source coordinates use CRS84. WGS84 for districts is inferred from coordinates and alignment because source CRS metadata is empty. Output GeoJSON uses `[longitude, latitude]`.
- No explicit data license was identified in the reviewed source repository. Original geometry, provenance and repair methods are retained. OpenStreetMap tile attribution remains visible.
- Polygon holes and MultiPolygons are supported. Filtering and seeding use original validated geometry. Complete city coverage is not claimed.

The three demo groups, `demo_a`, `demo_b` and `demo_c`, are visual data categories. They do not indicate price, quality or accessibility tiers. Seeding is reproducible for the same identity and seed; refresh, filters and sorting never randomize stored locations or prices. Sampling rejects ambiguous neighborhood overlaps and records shortages rather than placing points outside boundaries.

Two import formats demonstrate data-ingestion contracts; they are not live website integrations:

~~~powershell
.\.venv\Scripts\python.exe -m backend.app.cli import tests/fixtures/listings-a.csv --kind csv_a
.\.venv\Scripts\python.exe -m backend.app.cli import tests/fixtures/listings-b.json --kind json_b
~~~

Fixtures are synthetic by default; use `--real` only for genuine source records. Strong source identity is required for merging, and raw prices and dates remain preserved. Missing values are `null`. Money is stored as integer toman, durations as seconds and distances as meters. Deposit and monthly rent remain separate.

## Tests and technical references

Run offline unit tests from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd test
~~~

Run live browser/integration checks only with their required local services available. From `frontend`:

~~~powershell
npm.cmd run build
npx.cmd playwright test --config playwright.accessibility.config.ts
~~~

This browser configuration starts an isolated backend on port 8001 and uses the existing OTP and Qdrant services for the relevant scenarios. Existing reports record their own execution dates and results; this README is not a claim that every check has just run. Paid provider checks require separate explicit activation.

Detailed contracts and recorded evidence:

- [Accessibility handoff](docs/handoff-accessibility.md): automatic destination/stop routing, cache policy, API and measured limitations. Its original sort list also documents the backend `stop_distance_asc` option, which is now hidden in the UI.
- [Accessibility verification report](docs/accessibility-final-verification.json): recorded bounded live routing, cache and browser results.
- [Phase 1 handoff](docs/handoff-phase-1.md) and [state/API contract](docs/phase-1-contract.md): data, importers, seed, schemas and OTP adapter.
- [Phase 2 handoff](docs/handoff-phase-2.md): structured/semantic search, frontend filtering and evidence-backed explanations.
- [Phase 3 handoff](docs/handoff-phase-3.md): evaluation, reviewer workflow, KPI patch and controlled experiments.
- [Phase 3 acceptance matrix](docs/phase-3-acceptance-matrix.md) and [verification report](docs/phase-3-verification-report.json): recorded checks and remaining evidence gaps.

To regenerate shared JSON schemas and TypeScript types after changing contracts, run `.\.venv\Scripts\python.exe -m backend.app.export_schema` from the repository root.
