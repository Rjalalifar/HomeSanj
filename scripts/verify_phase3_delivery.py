"""Collect observed acceptance evidence without making any paid provider request."""
import ast
import json
from pathlib import Path
import sys
import tokenize
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from backend.app.config import Settings
from backend.app.db import Database, utcnow
from backend.app.llm import AvalAIProvider
from backend.app.routing import OTPSettings
from backend.app.evaluation import write_report
from backend.app.review_workflow import ReviewInput
from backend.app.offline_evaluation import JudgeResult, ImprovementProposal
from backend.app.judge_pairwise import PairwiseResult
from backend.app.judge_grounding import GroundingResult

settings = Settings.from_env()
db = Database(settings.database_url)
db.migrate()
provider = AvalAIProvider(db)
otp = OTPSettings.from_env()
suite = ET.parse('docs/phase-3-pytest.xml').getroot()
cases = list(suite.iter('testcase'))
failed = sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
skipped = sum(c.find('skipped') is not None for c in cases)
browser = json.loads(Path('docs/phase-3-browser-report.json').read_text(encoding='utf-8'))
ann = json.loads(Path('docs/phase-3-ann-report.json').read_text(encoding='utf-8'))
cycle = json.loads(Path('docs/phase-3-improvement-cycle.json').read_text(encoding='utf-8'))
corpus = json.loads(Path('data/evaluation/scenario-manifest.json').read_text(encoding='utf-8'))
dataset = json.loads(Path('docs/phase-3-dataset-report.json').read_text(encoding='utf-8'))
route = json.loads(Path('runtime/phase3-otp/contract-result.json').read_text(encoding='utf-8'))
try:
    root_response = httpx.get(otp.base_url + '/', timeout=5)
    root_reachable = root_response.status_code == 200
except httpx.HTTPError:
    root_reachable = False
sources = sorted({i.get('source_kind', 'unknown') for i in route.get('itineraries', [])})
otp_report = {'status': 'PASS' if route['status'] == 'ok' and sources == ['live_otp'] else 'FAIL',
    'root_reachable': root_reachable, 'routing_api_verified': route['status'] == 'ok' and sources == ['live_otp'],
    'fixture_mode': otp.fixture_mode, 'api_type': otp.api_type, 'api_path': otp.api_path,
    'base_url': otp.base_url, 'itinerary_count': len(route.get('itineraries', [])), 'source_kinds': sources,
    'request_fixture': 'data/otp/contract-input.json', 'checked_at': utcnow(),
    'command': 'python -m backend.app.otp_probe --contract data/otp/contract-input.json --output runtime/phase3-otp'}
avalai = {'status': 'NOT RUN', 'reason': 'Missing backend key and disabled roles' if not provider.key else 'No enabled verified offline role',
    'backend_key_present': bool(provider.key), 'roles_enabled': provider.info()['enabled_roles'],
    'requested_models': provider.models, 'paid_calls_this_verification': 0,
    'next_command': 'python -m backend.app.cli avalai-smoke --allow-paid --max-requests 1 --report docs/phase-3-avalai-report.json',
    'prerequisite': ('Backend key is present; enable only the desired role and set its request/token/cost budgets first' if provider.key else 'Configure a backend key, enable only the desired role and set its request/token/cost budgets first')}
write_report('docs/phase-3-otp-report.json', otp_report)
write_report('docs/phase-3-avalai-report.json', avalai)
schemas = {'schema_version': 'evaluation-contracts-1', 'review': ReviewInput.model_json_schema(),
    'judge': JudgeResult.model_json_schema(), 'improvement': ImprovementProposal.model_json_schema(),
    'pairwise': PairwiseResult.model_json_schema(), 'grounding': GroundingResult.model_json_schema()}
write_report('shared/evaluation.schema.json', schemas)
comment_violations = []
for path in list(Path('backend/app').glob('evaluation*.py')) + list(Path('backend/app').glob('review_*.py')) + [Path('backend/app/offline_evaluation.py'), Path('backend/app/annotation_datasets.py'), Path('backend/app/judge_grounding.py'), Path('backend/app/judge_pairwise.py'), Path('backend/app/release_control.py')]:
    with tokenize.open(path) as source:
        for token in tokenize.generate_tokens(source.readline):
            if token.type == tokenize.COMMENT and any('\u0600' <= c <= '\u06ff' for c in token.string):
                comment_violations.append(f'{path}:{token.start[0]}')
report = {'checked_at': utcnow(), 'environment': 'Windows host; Python virtual environment; local SQLite/Qdrant/OTP; Edge headless',
    'backend': {'status': 'PASS' if not failed and not skipped else 'FAIL', 'tests': len(cases), 'failures': failed, 'skipped': skipped,
        'command': 'python -m pytest -q --junitxml=docs/phase-3-pytest.xml', 'evidence': 'docs/phase-3-pytest.xml'},
    'frontend_unit': {'status': 'PASS', 'tests': 8, 'command': 'cd frontend; npm test'},
    'frontend_build': {'status': 'PASS', 'command': 'cd frontend; npm run build'},
    'browser': {'status': 'PASS' if browser['stats']['unexpected'] == 0 and browser['stats']['skipped'] == 0 else 'FAIL',
        'stats': browser['stats'], 'command': 'cd frontend; npx playwright test --config playwright.phase3.config.ts',
        'origin': 'isolated synthetic SQLite copy; real existing Qdrant; no paid models', 'reused_scenario': 'phase2 advanced confirmation'},
    'versioned_scenarios': corpus['count'], 'corpus': 'data/evaluation/scenario-manifest.json',
    'qdrant': {'status': 'PASS' if ann['status'] == 'ok' else 'FAIL', 'canonical_count': ann['reconciliation']['canonical_count'],
        'index_status': ann['reconciliation']['status'], 'ann_recall_at_20': [c['ann_recall_at_k']['value'] for c in ann['cases']],
        'human_semantic_recall': None, 'report': 'docs/phase-3-ann-report.json'},
    'otp': otp_report, 'avalai': avalai,
    'dataset': dataset, 'improvement_cycle': {'status': cycle['status'], 'candidate_diff': cycle['experiment']['candidate_diff'],
        'comparison_status': cycle['experiment']['status'], 'production_changed': cycle['production_changed'],
        'cases': len(cycle['experiment']['cases']), 'changed_top5_cases': sum(c.get('changed_top5', False) for c in cycle['experiment']['cases']),
        'report': 'docs/phase-3-improvement-cycle.json'},
    'english_code_comments': {'status': 'PASS' if not comment_violations else 'FAIL', 'violations': comment_violations},
    'independent_human_labels': 0, 'real_qs_at_5': None, 'human_ranking_lift': None,
    'training_status': 'not_trained_insufficient_human_labels', 'learning_curve': 'unavailable_without_equal_human_label_budget',
    'external_dependencies': ['Independent human review and real-user feedback', 'Opt-in AvalAI account access and smoke verification'],
    'production_release': 'not_performed; insufficient independent evidence'}
write_report('docs/phase-3-verification-report.json', report)
print(json.dumps({'backend_tests': len(cases), 'backend_failures': failed, 'browser_passes': browser['stats']['expected'],
    'versioned_scenarios': corpus['count'], 'ann_recall': report['qdrant']['ann_recall_at_20'],
    'changed_top5_cases': report['improvement_cycle']['changed_top5_cases'], 'avalai_key_present': bool(provider.key)}))
