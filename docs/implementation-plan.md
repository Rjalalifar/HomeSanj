# Khaneh Sanj — phase 1 implementation plan

**Goal:** Deliver the executable Persian rental-search foundation requested in the phase-1 brief.

**Architecture:** React/TypeScript/Vite and Leaflet frontend; FastAPI/Pydantic backend; SQLAlchemy 2 with SQLite persistence and a durable progressive worker. Frontend spatial selection is checked against authoritative backend geometry. OTP remains the user's existing local service. No external deployment.

**Specification:** The user's complete phase-1 specification, with React replacing Vue and SQLAlchemy 2 required. Decisions here are within the user's authorization to complete and verify the implementation.

## Constraints

- Never install OTP, rebuild its graph, occupy port 8821, expose it, or guess its API.
- Preserve original geometry and provenance; use versioned deterministic transformations.
- Synthetic listings and routes must be explicitly labeled; no fixture fallback unless enabled.
- No paid LLM calls during ordinary tests or seeding; secrets remain backend-only.
- Null means unknown/unset; all active constraints require evidence.
- Filtering precedes routing; routing concurrency defaults to 3, batches are bounded.
- All snapshots retain candidates, source records, versions, and per-condition evidence.

## Implementation and acceptance

- [x] Data: download pinned source if prepared files absent; normalize geometry and IDs; metric sampling, overlap rejection, seeded listings, reports and offline tests.
- [x] Contracts: versioned Pydantic schemas and generated TypeScript/JSON schema; normalization and two listing importers with incomplete/duplicate fixtures.
- [x] Persistence/API: SQLAlchemy migration, immutable search snapshots, validated state patches, spatial/property filtering, lineage and replay.
- [x] Routing: discover existing OTP, validate a real route if accessible; normalize itineraries, alternative selection, cache, concurrency, cancellation and statuses.
- [x] Optional LLM: AvalAI provider roles, bounded retries/budget, capability validation and explicit smoke command; limited offline parser.
- [x] Frontend: Persian RTL manual search, frontend spatial membership, map/legend, cards, progressive results and honest service status.
- [x] Verify: offline tests, frontend build, vertical API flow, full seed and reports; README and phase-2 handoff.

## Review focus

1. Ambiguous memberships and district/neighborhood contradictions must never silently remove a filter.
2. Time-zone offsets, midnight and missing walking legs must not produce false passing routes.
3. Cancellation/restart and partial ranking must preserve evidence and report incomplete scope.
4. Re-seeding must not overwrite existing or real listings, even with a colliding ID.
5. Invalid parser output and unrecognized patches must not mutate search state.
