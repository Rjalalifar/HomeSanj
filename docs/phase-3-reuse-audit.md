# Phase 3 reuse audit

Audit performed before Phase-3 feature changes, 2026-10-21. The supplied Phase-3 specification is the implementation authority. Existing Python/React applications, SQLAlchemy/SQLite, canonical contracts, client GIS and routing remain in place. No Git repository or AGENTS.md was found. The previous verification report records 97 backend, 8 frontend and 6 browser tests; fresh regression results will be recorded separately.

| Capability | Phase-2 code/route/table/test | Current status | Phase-3 action | Acceptance evidence |
|---|---|---|---|---|
| GIS and exact hard eligibility | geo.py, catalog.py, filter.ts; test_geo, test_phase2_core | working | REUSE | Real 377/22 files, persisted boundary assignments; existing GIS tests |
| SQLite structured/FTS retrieval | catalog.py, search.py; listings, listing_assignments, FTS5 | working | REUSE | test_phase2_core, sqlite-phase-2-benchmark.json |
| Qdrant and encoder reconciliation | semantic.py; semantic CLI | working | REUSE | qdrant-reconcile-report.json; 5655 canonical IDs |
| Intent and explanation | intent.py, explanations.py, llm.py | working | REUSE | typed claim checks and provider tests; live AvalAI NOT RUN without key |
| OTP, cache and itinerary eligibility | routing.py, worker.py; route_evaluations, route_cache | working | REUSE | test_routing, phase-2-live-acceptance-final.json |
| Deterministic ranking | ranking.rank_rows | working | EXTEND | optional explicit evaluation configuration; defaults unchanged |
| Request/candidate/route snapshots | search_requests, snapshot_candidates, route_evaluations | partial | EXTEND | Add immutable content-addressed reference manifest; never recalculate historical rank silently |
| First-final Top-5 freeze | feedback.touch_measurement; measurements | working | REUSE | test_feedback, test_measurement_worker; never re-freeze for Phase 3 |
| Events and explicit feedback | search_events, explicit_feedback | working | REUSE | idempotency/ownership/impression tests |
| QS / ranking metrics | feedback.measurement_metrics | partial | REPAIR | Phase-3 policy must not infer individual relevance from none-suitable; graded fixed-pool metrics and 24-hour QS replace diagnostic interpretation |
| Review sampling and annotation | review_samples, review_annotations | partial | EXTEND | Add leases, revisions, typed metadata and immutable supersession to these tables, not parallel feedback tables |
| Internal review UI | no internal page in existing React app | missing | NEW | Restricted same-app page; blind initial grade and authenticated APIs |
| Versioned annotation datasets | feedback.train_offline consumes labels directly | partial | EXTEND | JSONL export/import, provenance and grouped split manifest |
| Independent evaluator and judge | optional suggest_annotation plus provider judge role | partial | EXTEND | Dedicated strict offline rubric/cache; existing provider and reservations |
| Durable jobs | RoutingWorker leases; measurement_worker sweeps | partial | EXTEND | Separate bounded offline-job queue using same SQLite lease pattern; OTP worker untouched |
| Experiments and release controls | no registry | missing | NEW | Frozen paired comparison, evidence gates, test-scope promotion and rollback |
| Evaluation dashboard | no internal dashboard | missing | NEW | Same internal React page; honest unavailable/zero states |
| Human-reviewed reference pool | no independent human labels | missing | NEW | Collection workflow; no fabricated gold or production lift |

Phase-3 metadata uses references and hashes to existing evidence. Private destinations, raw user text, credentials and session tokens must not enter exports or judge prompts. Existing snapshots remain authoritative; missing/deleted evidence produces partial replay. Production promotion requires independently reviewed evidence and explicit approval. Synthetic mechanics may demonstrate test-scope promotion and rollback only.
