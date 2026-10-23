"""Summarize executed acceptance artifacts and preserve browser evidence for handoff."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
docs = root / 'docs'
browser = json.loads((docs / 'phase-2-browser-report.json').read_text(encoding='utf-8'))
suites = ET.parse(docs / 'phase-2-pytest.xml').getroot()
summary = {key: sum(int(suite.attrib.get(key, 0)) for suite in suites.iter('testsuite'))
           for key in ('tests', 'failures', 'errors', 'skipped')}
stats = browser['stats']
assert summary['tests'] >= 97 and summary['failures'] == summary['errors'] == 0
assert stats['expected'] == 6 and stats['unexpected'] == stats['flaky'] == stats['skipped'] == 0
live = json.loads((docs / 'phase-2-live-acceptance-final.json').read_text(encoding='utf-8'))
assert live['status'] == 'PASS' and live['sort_only_cache_misses'] == 0
screens = docs / 'screenshots'
screens.mkdir(exist_ok=True)
for name in ('phase-2-desktop.png', 'phase-2-mobile.png', 'phase-2-live-route.png'):
    shutil.copy2(root / 'frontend/test-results' / name, screens / name)
report = {
    'checked_at': datetime.now(timezone.utc).isoformat(),
    'phase': 2, 'implementation_status': 'complete_with_documented_external_limits',
    'offline_backend': {'status': 'PASS', **summary, 'artifact': 'phase-2-pytest.xml'},
    'frontend_unit': {'status': 'PASS', 'tests': 8, 'command': 'npm test'},
    'production_build': {'status': 'PASS', 'command': 'npm run build'},
    'browser': {'status': 'PASS', 'passed': stats['expected'], 'failed': stats['unexpected'],
                'duration_ms': stats['duration'], 'artifact': 'phase-2-browser-report.json',
                'engine': 'installed Microsoft Edge / Playwright',
                'viewports': ['1440x1000', '390x844']},
    'live_otp': {'status': 'PASS', 'artifact': 'phase-2-live-acceptance-final.json',
                 'candidate_count': live['candidate_count'], 'eligible_count': live['eligible_count'],
                 'sort_only_cache_hits': live['sort_only_cache_hits'],
                 'sort_only_cache_misses': live['sort_only_cache_misses']},
    'real_semantic': {'status': 'PASS', 'collection': 'homesanj_properties_v1',
                      'indexed_count': 5655, 'dimensions': 384,
                      'artifacts': ['embedding-verification.json', 'qdrant-reconcile-report.json',
                                    'advanced-semantic-live-report.json', 'semantic-benchmark.json'],
                      'browser_real_query_passed': True},
    'avalai_account_smoke': {'status': 'NOT_RUN', 'reason': 'No backend account key configured',
                             'requested_model': 'gemini-3.6-flash', 'resolved_model': None,
                             'paid_requests': 0},
    'independent_relevance_model': {'status': 'NOT_RUN', 'reason': 'Zero independent confirmed human labels; deterministic baseline retained'},
    'docker_backend_to_otp': {'status': 'NOT_RUN', 'reason': 'Backend runs directly on Windows host'},
    'external_geocoder': {'status': 'NOT_RUN', 'reason': 'No geocoder configured; destination uses explicit map confirmation'},
    'limits': ['Boundary source is from 2020 and not current official coverage',
               'Observed OTP schedule provenance and graph fingerprint are unknown',
               'Observed OTP API provides no verified aggregate transfer count',
               'Small authored semantic fixture does not establish user relevance lift',
               'No public/cloud deployment or multiuser production authentication claim'],
    'environment_note': 'Sandbox-hosted backend produced OTP HTTP 503; host execution passed the same real service checks. OTP was not reinstalled or altered.',
    'screenshots': [f'screenshots/{name}' for name in ('phase-2-desktop.png', 'phase-2-mobile.png', 'phase-2-live-route.png')],
}
(docs / 'phase-2-verification-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
ledger = '''# Phase 2 implementation ledger

Status: implementation complete; final acceptance executed on 2026-10-21.
Specification: attachment `59776b16-1e59-43d4-92f9-50b4cfa3a5da/pasted-text.txt`.
Architecture: React/TypeScript/Vite, FastAPI/Pydantic, SQLAlchemy 2/SQLite, Leaflet/Turf,
local ONNX multilingual encoder and persistent Qdrant. Code comments/docstrings are English.

- Complete: shared normal/advanced state, Persian confirmed intent, exact filters, public inventory worker,
  actual district assignments, indexed SQLite/FTS5, session ownership and immutable snapshots.
- Complete: persistent Qdrant, pinned 384-dimensional encoder, idempotent indexing/reconcile,
  real Persian queries and comparative authored-fixture benchmark.
- Complete: responsive RTL interface, map/list synchronization, destination/time confirmation,
  travel details and alternatives, three-listing comparison, stale-result protection and provider states.
- Complete: explicit property/Top-5 feedback, evidence-derived explanations, frozen measurements,
  deadline sweeper, bounded review queue and independent-human-label training gate.
- PASS: 97 backend tests, 8 frontend tests, production build and 6 browser scenarios.
- PASS: real OTP contract/search and sort-only cache reuse; real Qdrant advanced search in browser.
- NOT RUN: paid AvalAI account/model smoke (no key), Docker backend-to-OTP network and external geocoder.
- Insufficient data: independent ranking-model training/relevance-lift claims; baseline remains active.

Read `handoff-phase-2.md`, `phase-2-acceptance-matrix.md` and
`phase-2-verification-report.json` before beginning Phase 3. Browser screenshots are under
`docs/screenshots/`. No ordinary task requires the chat history to reproduce this phase.
'''
(docs / 'phase-2-progress.md').write_text(ledger, encoding='utf-8')
path = docs / 'handoff-phase-2.md'
text = path.read_text(encoding='utf-8')
text = text.replace('separately below; the final browser and regression results are added after execution.', 'in `phase-2-verification-report.json`; final browser and regression checks passed on 2026-10-21.')
text = text.replace('Final test counts and screenshots are recorded in the phase-two verification report after\nexecution.', 'Final results: **97 backend tests, 8 frontend tests, 6 browser scenarios and production build PASS**.\nSee `phase-2-verification-report.json` and `phase-2-browser-report.json`.')
text += '''

## Final browser walkthrough and operational notes

The single application entry `/` provides independently selectable Normal and Advanced modes.
The deterministic contextual text parser is also available from the expandable normal-search
panel. Three examples use loaded neighborhood names. Clearing only neighborhoods is separate
from clearing hard filters; confirmed destination/time and unrelated preferences persist.
The browser worker filters and sorts the persisted inventory and displays the same page on the
map. Pending routing does not turn those property previews into verified travel results.

Executed browser coverage includes local filtering without search submission, two-way map/list
selection, explicit destination/time, real OTP routes and readable route legs, three-home comparison,
stale comparisons, explicit feedback, contextual parking/less-walking edits, neighborhood-only
clearing, real Qdrant search with confirmed hard constraints, deterministic explanations, mobile
layout, deliberately unavailable tiles and ignored stale search responses. The map uses Canvas;
walking geometries use dashed styling, transit geometries solid styling. No geocoder is implied.

![Desktop](screenshots/phase-2-desktop.png)
![Mobile](screenshots/phase-2-mobile.png)
![Real route detail](screenshots/phase-2-live-route.png)

The final bounded API acceptance is `phase-2-live-acceptance-final.json`: three eligible real OTP
routes, then three cache hits and zero misses on walking sort. Its OTP P50/P95 were approximately
248/441 ms for three samples. `sqlite-phase-2-benchmark.json` and `semantic-benchmark.json` retain
separate local SQL/API and semantic measurements; these small samples are not a production SLA.

`frontend/.env.example` documents the public OSM-compatible tile URL; retain appropriate provider
attribution if changing providers. The current OSM attribution is always displayed. The UI loads no
API secrets or private user destinations from other sessions. Card provenance and observed
schedule limitations remain visible. Optional feedback reasons are allowlisted category codes.

Client events record actual rendered/impression/click/route/comparison/filter/mode actions.
Indexed event validation avoids reranking every candidate for each card event. Frozen measurements
return immediately after ownership checks; demo properties and fixture routes cannot become
real-user relevance evidence. Backend deadline sweeping continues after the browser closes.

The agent's restricted process environment returned HTTP 503 to local OTP during one check.
Running the backend directly on the host passed the same flow; no OTP service, graph or binding
was changed. Ordinary local startup commands above run in the host environment. Do not interpret
a successful root page as a routing contract test.

Remaining external limits are explicit: no AvalAI account key/model capability was verified; no
paid request was made; no independent human relevance dataset exists. Available deterministic
and offline failure tests cover those unavailable-provider paths. Production label agreement,
model lift and meaningful user-level Precision/NDCG remain unavailable without independent labels.
Phase 3 can start from the current schemas, frozen evidence, restricted review APIs and reports.
'''
path.write_text(text, encoding='utf-8')
path = docs / 'phase-2-acceptance-matrix.md'
text = path.read_text(encoding='utf-8').replace('Frontend fixture and browser test report (recorded after execution)', 'PASS: frontend filter fixtures and six executed browser scenarios').replace('Browser acceptance report (recorded after execution)', 'PASS: `phase-2-browser-report.json` (6/6)')
text += '\nFinal totals: **97 backend tests, 8 frontend tests, 6 browser scenarios, production build: PASS**.\nSee `phase-2-verification-report.json` and `screenshots/`. Final live OTP/cache execution is\n`phase-2-live-acceptance-final.json`. Real AvalAI smoke remains NOT RUN, with zero paid requests.\n'
path.write_text(text, encoding='utf-8')
print(json.dumps({'backend_tests': summary['tests'], 'frontend_tests': 8, 'browser_passed': stats['expected'], 'report': 'docs/phase-2-verification-report.json'}))
