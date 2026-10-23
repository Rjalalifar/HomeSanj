# Phase 3 handoff — evaluation, review and controlled improvement

This phase extends the Phase-2 FastAPI/Pydantic, SQLAlchemy 2/SQLite and React application. The reuse audit was written before feature changes: [phase-3-reuse-audit.md](phase-3-reuse-audit.md). There is no second search engine, vector indexer, canonical listing database or feedback store. All code comments are English. No production ranking release has been activated.

## Run

From the repository root, use the existing virtual environment and installed frontend dependencies:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

The consumer UI remains at `http://127.0.0.1:8000/`. The internal page is `http://127.0.0.1:8000/internal`. Configure `REVIEW_API_TOKEN` in the backend environment before starting, then enter it in the internal login. The token is sent in `x-review-token`, kept in page memory and never put in a URL or browser storage. For multiple independently identified reviewers, configure `REVIEWER_TOKENS_JSON` as a JSON object mapping reviewer names to distinct random secrets of at least 16 characters. Keep this local prototype bound to loopback. The default `.env.example` contains no credentials.

```powershell
cd frontend
npm.cmd run build
npm.cmd test
```

FastAPI startup applies additive migration 4. Existing `review_samples` and `review_annotations` gain JSON metadata columns; their identities and old records remain. New tables hold reference manifests, dataset versions, offline jobs, experiments, release history and guardrail approvals. SQLite remains authoritative. OTP stays on port 8821 and is called only through the existing backend adapter.

## What is reused and what changed

Reused: canonical search state, confirmed intent and hard eligibility; client GIS and server spatial membership; SQLite structured/FTS5 queries; local encoder and existing Qdrant reconciler; OTP normalization, cache and progressive worker; source candidate/route snapshots; once-frozen Top-5 measurements; events, explicit feedback, provider reservations, explanation claim validators and transparent ranking.

Added or extended:

- `evaluation_metrics.py` and `evaluation_diagnostics.py`: exponential-gain NDCG@5, P@5, MRR@5, fixed-pool Recall@20, separate human/AI hit rates, QS S/F/U/pending, grouped bootstrap, state accuracy, same-evidence claim checks, human/judge agreement and observed percentiles.
- `evaluation_replay.py`: content-addressed manifests referencing existing request/candidate/route/retrieval/explanation rows. New final deliveries capture ranking and components. Backfills explicitly say `ranking_at_manifest_capture`; they do not pretend to prove the original historical order. Missing or altered evidence yields `partial_replay`; replay never calls OTP, Qdrant or a model.
- `review_workflow.py`, `review_sampling.py`, `review_issues.py`: one extended acquisition path used by both the old API and new internal jobs. Seeded 10/4/4/2 quotas, critical items outside quota, mode/task stratification, true random shortage refill, stable deduplication, evidence-linked issues, leases, assignment, revisions, typed annotations and immutable supersession.
- `annotation_datasets.py`: real JSONL files and immutable checksum manifests, task/property/intent connected groups, fixed splits, conservative idempotent imports and explicit provenance. Imported labels remain pending; automatic test annotations are `test_fixture`, never independent human labels.
- `offline_evaluation.py`, `judge_pairwise.py`, `judge_grounding.py`: independent offline roles on the existing AvalAI adapter. Blind relevance packets, bounded JSON validation/one repair, original-claim audits, seeded A/B swaps, proposal-only improvement, idempotent job keys, leases, bounded restart attempts and deferred budget/disabled states.
- `evaluation_experiments.py`, `release_control.py`: the existing ranker accepts one explicit evaluation variable, `rent_weight_multiplier`. Experiments freeze label values/IDs, pool hashes, route hashes, controls and versions. Test releases and rollback change a separate test registry; production requires independent evidence, a final holdout milestone and signed human guardrails.
- `InternalReview.tsx`: an internal route within the existing React app, with authentication, queue filters, claims/leases, independent initial grading, evidence selection, patches, pairwise comparison, insufficient/skip/resolve/escalate actions, supersession history and dataset export/download. No consumer redesign.

A proven Phase-2 metric defect was repaired: “none suitable” is a task outcome and no longer creates negative labels for every displayed property. Historical feedback and Top-5 snapshots are untouched. Old measurement fields no longer report a binary-label NDCG as independently graded relevance; their status directs callers to the fixed-pool evaluator. The regression is `test_phase3_feedback_policy.py`.

## Contracts and evidence

Canonical search state remains `shared/contracts.schema.json`. Phase-3 input/output schemas are exported to `shared/evaluation.schema.json`. Internal endpoints are installed by `phase3_api.py`; all protected routes reuse reviewer authentication and same-origin write protection.

| Operation | Endpoint |
|---|---|
| Dashboard / filtered samples | `GET /api/internal/dashboard`, `GET /api/internal/reviews` |
| Claim / annotate | `POST /api/internal/reviews/{sample_id}/claim`, `/annotations` |
| Assign / record issue / compare facts | `POST .../{sample_id}/assign`, `/issues`; `GET .../{sample_id}/pair/{candidate_id}` |
| Reviewers / observed disagreements | `GET /api/internal/reviewers`; `POST /api/internal/reviews/refresh-issues` |
| Acquire batch | `POST /api/internal/acquire` |
| Export / download dataset | `POST /api/internal/datasets/export`; `GET /api/internal/datasets/{dataset_id}/annotations.jsonl` or `/manifest.json` |
| Manifest / replay | `POST /api/internal/manifests/{request_id}`; `GET /api/internal/replay/{manifest_id}` |
| Judge / pairwise / grounding / improvement | `POST .../reviews/{sample_id}/judge`, `/pairwise`, `/explanations/{cache_key}/judge`, `/improvement` |
| Job result | `GET /api/internal/jobs/{job_id}` |
| Compare / approve / release | `POST /api/internal/experiments`, `/approvals`, `/releases` |

Annotation grades are 0 unsuitable, 1 weak, 2 suitable, 3 strong, or null for insufficient evidence. Relevance requires grade >=2 and all active hard conditions pass. Reviewer, explicit user feedback and AI weak labels remain separate origins. Synthetic provenance and approval state are separate dimensions. Grade and utility are not probabilities or user success.

P@5 divides by five, including truly empty slots; displayed unknown labels make it unavailable. NDCG uses `2^grade-1` and the same fully judged fixed pool for IDCG; IDCG=0 is excluded. Recall is relative to that pool, not all Tehran. Human and judge hit rates use their own label origins. Zero denominators are null. Bootstrap resamples linked intent groups, not cards.

QS retains the existing once-frozen first-final Top-5. The default feedback window is 24 hours; S is a valid explicit frozen-candidate confirmation, F an explicit task rejection or terminal failed/empty delivery, U insufficient outcome evidence, and unfinished windows pending. Reports show N/S/F/U/pending, QS=S/(S+F), coverage, S/N and missing-outcome bounds. The bounds are not confidence intervals. First exposed mode and actor cohort are preserved; later conversational success does not rewrite the primary outcome. No real-user QS is claimed for demo/test records.

Exports and review views omit precise destinations, raw sensitive query text, raw source records and provider secrets. Public replay returns a destination reference and sanitized route summaries. Original protected evidence remains in existing SQLite rows; privacy removal results in partial replay rather than replacement data.

## Repeatable workflow

```powershell
# Version existing regression cases; no duplicate fixtures and no provider calls.
.\.venv\Scripts\python.exe -m backend.app.evaluation corpus --output data/evaluation/scenario-manifest.json

# Freeze references for an existing search request.
.\.venv\Scripts\python.exe -m backend.app.evaluation snapshot --request-id REQUEST_ID --output runtime/replay-manifest.json

# Compare the same frozen candidates with the documented single-variable change.
.\.venv\Scripts\python.exe -m backend.app.evaluation evaluate --manifest-id MANIFEST_ID --split validation --output runtime/comparison.json

# Existing data and index; ANN correctness is separate from human relevance.
.\.venv\Scripts\python.exe -m backend.app.semantic reconcile --report docs/phase-3-index-report.json
.\.venv\Scripts\python.exe -m backend.app.evaluation ann --output docs/phase-3-ann-report.json

# Internal UI performs acquisition and typed review; jobs also run in app lifespan.
.\.venv\Scripts\python.exe -m backend.app.evaluation worker-once --output runtime/offline-job-result.json
.\.venv\Scripts\python.exe -m backend.app.evaluation export --output runtime/export-report.json
.\.venv\Scripts\python.exe -m backend.app.evaluation import --directory runtime/datasets/DATASET_ID --output runtime/import-report.json

# Mechanical demonstration on existing demo snapshots, with test-only promotion and rollback.
.\.venv\Scripts\python.exe -m backend.app.evaluation demo --output docs/phase-3-improvement-cycle.json
.\.venv\Scripts\python.exe -m backend.app.evaluation dashboard --output docs/phase-3-dashboard-report.json
```

The candidate increases the rent weight by 25% through `ranking.rank_rows(..., config=...)`; all default production weights remain unchanged. The report records actual differences and whether Top-5 changed. The demo has no invented subjective grades and therefore reports `insufficient_evidence`. It proves the mechanics of configuration publication and restoration in `scope=test`, not user benefit.

Validation and holdout use exported dataset group mappings. Exported holdout tasks are excluded from active acquisition. A final holdout run requires a measured validation result for that same candidate and label dataset, and the same dataset's holdout cannot be reused repeatedly. Production checks require at least 200 reviewed pool members, 30 independent groups, a positive paired lower interval bound, a real fully judged cohort, final holdout and explicit signed guardrails for correctness/privacy/grounding/latency/cost/coverage/index/regressions. These are initial policy gates, not statistical guarantees. There is no current production approval or causal real-user experiment.

## Verification and limits

Authoritative observed results: [phase-3-verification-report.json](phase-3-verification-report.json), [phase-3-acceptance-matrix.md](phase-3-acceptance-matrix.md).

- Full backend regression suite: `python -m pytest -q --junitxml=docs/phase-3-pytest.xml`.
- Frontend unit tests and build: `npm test`, `npm run build` in `frontend`.
- Focused browser suite: `npx playwright test --config playwright.phase3.config.ts`. It launches an isolated local backend on 8001, copies only synthetic listings, reuses the Phase-2 Advanced Search scenario against the existing Qdrant index, and exercises the new internal page. The copied test database is not a production data source. Its ephemeral credential is ignored under `runtime/`, never bundled.
- Existing OTP contract test: `python -m backend.app.otp_probe --contract data/otp/contract-input.json --output runtime/phase3-otp`. The input uses public fixture coordinates and a date inside the previously verified feed. See `phase-3-otp-report.json` for root/routing/fixture distinctions.
- Real Qdrant report: `phase-3-ann-report.json`; fixed synthetic population, exact and approximate top-K use identical vectors, distance and payload filters. `params.exact=true` follows [Qdrant's official search documentation](https://qdrant.tech/documentation/search/). Fully human-judged semantic recall remains unavailable.
- Dataset artifact: `data/evaluation/demo-review/`, with its current identity and idempotent import result in `phase-3-dataset-report.json`. The browser-created annotation is explicitly an automated fixture. Independent human label count is zero.
- AvalAI live judge/improvement and explanation smoke: **NOT RUN** because all four roles are explicitly disabled. A backend key is present; account-visible model access remains unverified. No paid calls were made. Runtime prompts, schemas, error handling, budgets, privacy and invalid-output behavior are covered offline. Enable only the desired role and set its independent request/token/output/rate/concurrency budget before `python -m backend.app.cli avalai-smoke --allow-paid --max-requests 1 --report docs/phase-3-avalai-report.json`. Optional monetary caps require a confirmed conservative account-specific rate; unknown measured cost stays null.
- Real QS, human ranking lift, human semantic recall, human/judge audit-cohort warning and equal-budget active-learning curves remain unavailable without independent human/user evidence. Optional training stays `not_trained_insufficient_human_labels`. The dashboard does not fabricate successful charts for these cases.

All original boundary provenance and limitations remain in the Phase-1/2 handoffs: the 2020 source has 377 neighborhood features/22 districts with documented overlap/assignment uncertainty, not proven current official coverage. Routing schedule/realtime/transfer limitations also remain explicit. Phase 3 does not alter those facts.

## Minimal search KPI patch — 2026-10-22

`GET /api/internal/dashboard` now adds `primary_kpis`: Normal QS@5, human NDCG@5 and finalized-search P95; Advanced QS@5, human NDCG@5 and Gemini groundedness. `/internal` shows exactly these six primary cards with counts, coverage, observation period, policy, source mode and cohort; existing diagnostics remain expandable. The adapter reuses frozen measurements, explicit feedback, versioned human fixed-pool experiment results and stored Gemini-selected typed claims. It never calls a model. Deterministic explanation claims and uncheckable prose are excluded. Accessibility context counts distinguish destination/nearby-stop/legacy where stored state permits; mixed contexts and unmatched traffic are not evidence of mode superiority. NDCG uses the latest stored label-dataset/split cohort, deduplicates manifests and excludes unjudged/test-fixture labels.

All six primary KPIs on the local database are currently `insufficient_data`: no valid resolved real-user outcomes, fully human-graded fixed pools or evaluated Gemini claims; dependable submission-to-final-result timing is missing because the submission event is recorded after initial filtering. An existing empty frozen result mislabeled `real_user` had three synthetic candidates; aggregation now uses existing candidate/route provenance to exclude it without rewriting history. Normal/Advanced/all review filtering and the shared queue were already implemented. Acquisition now preserves ambiguous historical modes as `unknown` when `SearchAnalysis` is absent; no tables, routes, model training or new sampling pipeline were added.

Focused verification: 24 distinct backend tests passed across the following runs (15 initial metric/auth/policy tests, 8 sampler/review tests, then 9 affected metric/auth tests including the new historical-provenance regression). Frontend build passed. Both internal desktop/mobile browser tests passed; only the affected desktop test was rerun after the provenance correction and passed again. Authentication, snapshot identities, shared queue deduplication and unavailable-state rendering were verified. Full regression suites and paid model calls were NOT_RUN for this patch. The isolated browser checks used `http://127.0.0.1:8001/internal`; the normal local application URL remains `http://127.0.0.1:8000/internal`. The current normal backend environment has no reviewer credential configured; use the existing `REVIEW_API_TOKEN`/`REVIEWER_TOKENS_JSON` configuration to log in, never a bundled token.

Commands actually run (repository root for Python, `frontend` for npm/Playwright):

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_search_kpis.py tests/test_phase3_api_diagnostics.py tests/test_phase3_metrics.py tests/test_phase3_feedback_policy.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_search_kpi_sampling.py tests/test_phase3_review.py tests/test_phase3_sampling.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_search_kpis.py tests/test_phase3_api_diagnostics.py
npm.cmd run build
npx.cmd playwright test --config playwright.phase3.config.ts --grep "restricted internal|internal page"
npx.cmd playwright test --config playwright.phase3.config.ts --grep "restricted internal"
```
