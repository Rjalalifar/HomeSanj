# Phase 2 acceptance evidence

This matrix distinguishes executed offline tests, real local service checks and unavailable
external capabilities. The final browser report supplements it; no provider result is simulated
without an explicit fixture label.

| Requirement | Evidence / status |
| --- | --- |
| Canonical money/null and hard filters | Offline tests in `test_contracts`, `test_search`, `test_phase2_core` |
| OR/AND geography, overlap and same-name ambiguity | Offline geometry/core/intent tests |
| Persisted seed/IDs and no reseeding | Phase-one seed repeat report; immutable inventory/version tests |
| Browser/server filter agreement | PASS: frontend filter fixtures and six executed browser scenarios |
| Sort ties and fixed-scale ranking | `test_phase2_core`, `test_phase2_replay` |
| Same itinerary, least-walking alternative and cache reuse | `test_phase2_worker_selection`; real `phase-2-live-acceptance.json` PASS |
| OTP timeout/no route/concurrency/cancellation | Offline `test_routing`, `test_worker_api` |
| Pending semantic work cannot block normal routing | `test_phase2_worker_queue` |
| Real existing OTP | Live contract returned five valid itineraries; three-property acceptance PASS |
| Qdrant outage/empty/stale/dimension/model mismatch | Offline `test_semantic` and `test_phase2_integration` |
| Real local encoder and persistent Qdrant | `embedding-verification.json`, `qdrant-index-report.json`, `qdrant-reconcile-report.json` PASS |
| Approximate retrieval cannot bypass exact constraints | `test_phase2_integration`; real advanced API hard-match violations = 0 |
| Persian vector/FTS/hybrid comparison | `semantic-benchmark.json` PASS; authored fixture, no user-satisfaction claim |
| No models/OTP during normal filtering | Offline integration tests; browser request instrumentation |
| Unknown route cannot qualify | `test_phase2_integration`, explanation evidence tests |
| Invalid model JSON/IDs, quota and timeout | Offline provider and feedback/explanation tests |
| Real AvalAI account/model smoke | NOT RUN: no credentials, no paid request; `phase-2-avalai-smoke-report.json` |
| Evidence cannot reference outside candidates or false comparisons | Offline typed-claim tests in `test_feedback` |
| Immutable Top-5 and explicit feedback ownership | Offline `test_feedback`; browser flow |
| Deadline records closed/incomplete sessions | `test_measurement_worker` |
| Replayed numeric ranks unaffected by current inventory/page | `test_phase2_replay` |
| Session isolation and cross-origin write rejection | `test_phase2_core` |
| Concurrent SQLite snapshot writes | Three-thread workload in `test_phase2_integration` |
| Independent Active Learning training | Insufficient data, zero independent labels; deterministic baseline retained |
| Mobile, map outage, zero results and stale responses | PASS: `phase-2-browser-report.json` (6/6) |
| Docker backend to host OTP / cloud exposure | NOT RUN; backend runs directly on the Windows host; no tunnel or public binding |

Latency components are separate. SQLite, FTS and immutable API snapshot timings are in
`sqlite-phase-2-benchmark.json`; real semantic retrieval in `semantic-benchmark.json`;
real OTP calls in `phase-2-live-acceptance.json`. Real generative explanation latency and
account cost remain NOT RUN. No precise production throughput or relevance lift is claimed.

Final totals: **97 backend tests, 8 frontend tests, 6 browser scenarios, production build: PASS**.
See `phase-2-verification-report.json` and `screenshots/`. Final live OTP/cache execution is
`phase-2-live-acceptance-final.json`. Real AvalAI smoke remains NOT RUN, with zero paid requests.
