# Phase 3 acceptance matrix

Read with `phase-3-verification-report.json`, which contains actual test counts, commands and service observations. PASS refers to an executed check; no human/LLM outcome is inferred from code tests.

| Requirement | Implementation / reused evidence | Verification / status |
|---|---|---|
| Reuse audit before implementation | phase-3-reuse-audit.md; same canonical tables and application | PASS: audit precedes new feature files |
| Replay lineage, privacy and partial evidence | evaluation_replay.py; original candidate/evaluation/cache rows | PASS: test_phase3_review, test_phase3_budget_privacy, test_phase3_api_diagnostics |
| 0..3/null, hard-pass relevance, exact metric denominators | evaluation_metrics.py | PASS: test_phase3_metrics |
| First-final freeze and QS policy | existing measurements/feedback; 24-hour evaluator | PASS: test_feedback, test_measurement_worker, test_phase3_metrics, test_phase3_feedback_policy |
| Versioned >=60 cases without cloned fixtures | data/evaluation/scenario-manifest.json | PASS: references and hashes existing/new tests; synthetic/programmatic provenance |
| Normal search isolation and GIS agreement | existing Phase-2 tests and focused consumer browser test | PASS: backend GIS/contract tests; zero advanced/internal/provider requests in browser |
| Real Qdrant integrity and ANN/exact | existing SemanticService.reconcile and encoder/Qdrant client | PASS: phase-3-ann-report.json; human relevance remains unavailable |
| OTP actual contract | existing verified Transmodel adapter | PASS: phase-3-otp-report.json; fixture_mode=false |
| Judge budget/invalid JSON/privacy/no implicit paid call | existing AvalAI provider, offline_evaluation.py | PASS offline: test_llm, test_phase3_jobs_experiments, test_phase3_budget_privacy; live NOT RUN |
| Independent claim grounding / agreement | original ExplanationCache plus typed validator | PASS deterministic: test_phase3_api_diagnostics; live AI/human agreement NOT RUN |
| Leases, assignments, supersession, evidence-scoped review | extended review_samples/review_annotations | PASS: test_phase3_review, test_phase3_issue_holdout; internal browser checks |
| Seeded stratified/random acquisition | legacy API and new jobs share acquire_batch/select_batch | PASS: test_phase3_sampling; conditional probabilities only |
| Typed annotations and provenance-preserving dataset files | annotation_datasets.py; real JSONL export/import | PASS: test_phase3_review; phase-3-dataset-report.json; fixture origin explicit |
| Worker restart/idempotency/deferred budgets | offline_jobs using the existing SQLite lease pattern | PASS: test_phase3_jobs_experiments; OTP worker remains independent |
| Changed candidate with frozen controls/labels | existing rank_rows optional multiplier; experiment report | PASS mechanics: phase-3-improvement-cycle.json; ranking lift insufficient_evidence |
| Holdout isolation | dataset task-group manifest; acquisition exclusion; final milestone gate | PASS: test_phase3_issue_holdout and experiment tests |
| Publication and rollback | append-only scoped releases and human guardrail approvals | PASS test-only promote/rollback; production blocked without evidence/approval |
| Internal dashboard and access control | same React/FastAPI app; credential-protected APIs | PASS: test_phase3_api_diagnostics and desktop/mobile browser tests |
| Full regression/build and English comments | final verification report and JUnit/browser artifacts | PASS as recorded in phase-3-verification-report.json |
| Independent human evaluation / real QS / causal lift | requires actual independent reviewers and real users | NOT RUN: no fabricated human labels or lift |
| Optional training / equal-budget learning curve | reuse existing offline training baseline | NOT RUN: insufficient independent human labels |

The remaining dependencies are external evidence and optional account activation. They are not silently substituted with generated labels, guessed costs or demo outcomes.
