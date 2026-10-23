# Phase 3 implementation plan

Goal: deliver independent evaluation, restricted human review and controlled improvement on the existing Phase-2 application.

Architecture: additive SQLAlchemy migration, thin immutable replay manifest, dedicated mathematical metrics, extension metadata on existing review tables, versioned JSONL datasets, bounded offline jobs, and an internal React view. Existing retrieval, hard eligibility, provider, ranking and OTP evidence are reused.

Spec: user-supplied Phase 3 attachment; reuse decisions in phase-3-reuse-audit.md. The user has instructed execution through completion. All code comments are English. No paid calls or production activation occur by default.

- [x] Add focused metric tests: exponential NDCG, fixed-pool recall, unjudged slots, zero denominators, hard-pass relevance, QS S/F/U/pending and first exposure.
- [x] Add migration 4 and replay references with content hashes; missing evidence yields partial replay without external calls.
- [x] Extend review tables with lease/revision and typed annotation metadata; test conflicts, blind views, valid evidence refs and supersession.
- [x] Export/import immutable datasets; keep synthetic provenance, grouped splits, holdout separation and duplicate protection.
- [x] Add offline judge/job runner reusing AvalAI reservations; strict privacy, bounded retry, deferred budgets and recovery.
- [x] Add a versioned case manifest referencing at least 60 existing/new test cases; run deterministic evaluation and a documented single-variable candidate comparison with grouped bootstrap.
- [x] Add promotion gates and test-only rollback demonstration; real human metrics remain unavailable without labels.
- [x] Add restricted internal review/dashboard page to existing React entry point; focused browser checks.
- [x] Run backend/frontend regression checks, actual local service checks where available, and publish handoff with measured results and remaining external dependencies.

Review focus: deleted source evidence; mixed-origin annotations; duplicate task paraphrases; expired/concurrent leases; unknown hard constraints; test release accidentally affecting production; private destination leakage. Tests must cover these explicitly.
