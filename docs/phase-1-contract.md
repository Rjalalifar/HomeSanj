# Phase 1 contracts

The canonical source is `backend/app/contracts.py`. Run `python -m backend.app.export_schema`
to regenerate `shared/contracts.schema.json` and `frontend/src/contracts.generated.ts`.
TypeScript types describe fully serialized models, including defaults. API validation
remains authoritative. The JSON Schema records defaults and optional input fields.

## State

`schema_version=1.0.0`; `dataset_version` must match the loaded geometry. The server
assigns `state_revision` from the parent request. `query` stores the original text;
only the validated `property` and `travel` fields drive filtering. Text parsing
proposes an explicit patch which the user reviews before applying.

Money is integer toman. Durations are seconds, distances meters, GeoJSON is
longitude then latitude. `null` means unset in conditions and unknown in listings.
An active condition with an unknown value cannot pass.

Multiple neighborhood selections are OR, multiple district selections are OR,
and the two groups combine with all property conditions using AND. Empty lists
remove that group's restriction. District membership comes from the point and
district geometry, never the source neighborhood's assigned district number.
Overlapping membership is exposed as ambiguous.

`parking_required=false` and `elevator_required=false` mean no requirement.
Removing an internal patch field restores the canonical default: numeric limits
and destination/date/time are null, selections and modes are empty, required
booleans and walk-only are false, preference is balanced, sort is recommended,
timezone is Asia/Tehran, time mode is DEPART_AT and duration scope is itinerary.
Deleting a destination while retaining travel conditions fails validation; remove
the related conditions together or reset the travel object through the form.

Internal patches are `{field, value}` or `{field, remove:true}`. Only the
`PATCH_FIELDS` allowlist is accepted. This is **not RFC 6902**. Applying a patch
is atomic; validation failures leave the original state unchanged.

## Search lineage and evidence

`POST /api/searches` takes `{state, task_id?, parent_request_id?, new_need?}`.
A change creates a new request and snapshot. Reusing a task without changing the
confirmed destination retains the task. Changing destination or `new_need=true`
creates a new task. The parent remains recorded for audit.

Each snapshot persists all property-qualified candidates with source records,
coordinates, values, ordinal and condition verdicts, before any routing. It also
records the full state, schema/dataset/parser/adapter/ranker/graph versions and
selection method. Route evaluations preserve returned alternatives and their
raw response evidence when available. Snapshot replay uses stored evidence and
does not call OTP or a language model.

## API

| Method and path | Purpose |
| --- | --- |
| GET `/api/health` | Stored dataset and explicit OTP/LLM status |
| GET `/api/neighborhoods` | Validated original neighborhood GeoJSON |
| GET `/api/districts` | Validated original district GeoJSON |
| GET `/api/state/default` | Current dataset's canonical defaults |
| GET `/api/schema` | SearchState JSON Schema |
| POST `/api/state/patch` | Validate and apply an internal patch |
| POST `/api/parse` | Propose supported conditions; never mutate state |
| POST `/api/searches` | Create request and snapshot |
| GET `/api/searches/{id}` | Poll progress and paginated results |
| GET `/api/searches/{id}/snapshot` | Inspect candidate and route evidence |
| POST `/api/searches/{id}/replay` | Read stored snapshot without network calls |
| POST `/api/searches/{id}/cancel` | Cancel pending routing work |
| POST `/api/searches/{id}/continue` | Evaluate the next bounded batch |

Result pagination is `offset` and `limit`, with a maximum of 200 rows. The initial
UI displays 100 rows and labels that limit. Full candidates remain in the snapshot.

## Progressive routing

Candidate selection is deterministic: ascending rent (or deposit for deposit sort),
unknown last, then property ID. A batch defaults to 30 and concurrency to 3.
`evaluated_count`, `candidate_count`, `completion_status` and `subset_method` are
always available. Partial recommendations are only within the evaluated subset.

The durable worker claims SQLite leases and preserves finished evaluations across
restart. Cancellation stops active tasks; unfinished candidates can be continued.
A process crash leaves a lease that another worker can recover after expiration.
Cancellation draining must finish before continuing.

The cache stores returned alternatives, not just the selected route. Changing
preference can reuse these alternatives and reselect. Effective routing inputs
and graph/feed identity participate in the cache key. Cache is time-limited.

## Ranking

Property/route constraints are hard eligibility checks. Recommendation scores are
weighted min/max-normalized metrics over the displayed eligible population, with
unknown values assigned the worst score. Balanced weights are rent 0.35,
duration 0.35, walking 0.15, transfers 0.15. Other preferences adjust these weights;
the implementation and `ranker` version record exact values. Without destination,
only rent contributes. Deposit is not converted into equivalent rent.

The selected itinerary supplies every travel metric on its card. No metric is
borrowed from another alternative.
