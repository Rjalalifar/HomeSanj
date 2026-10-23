"""Observed metrics from existing event, freeze, route and annotation evidence."""
from collections import Counter, defaultdict
import os
from sqlalchemy import select
from .db import Evaluation, ProviderCall, SearchRequest
from .catalog import SearchAnalysis
from .feedback import Measurement, Feedback, SearchEvent, ReviewSample, ReviewAnnotation
from .evaluation_store import DatasetVersion, Experiment, OfflineJob, Release, ReplayManifest
from .evaluation_metrics import qualified_success, ratio, METRIC_VERSION, RUBRIC_VERSION
from .event_evidence import request_actor


def dashboard(db):
    with db.session() as session:
        measurements = list(session.scalars(select(Measurement)))
        cohort_actors = {m.measurement_id: request_actor(session, m.evaluation_request_id)
            if m.actor_kind == 'real_user' else m.actor_kind for m in measurements}
        feedback = list(session.scalars(select(Feedback).order_by(Feedback.created_at, Feedback.feedback_id)))
        events = list(session.scalars(select(SearchEvent).order_by(SearchEvent.timestamp, SearchEvent.event_id)))
        requests = {r.request_id: r for r in session.scalars(select(SearchRequest))}
        analyses = {a.request_id: a for a in session.scalars(select(SearchAnalysis))}
        routes = list(session.scalars(select(Evaluation)))
        calls = list(session.scalars(select(ProviderCall)))
        samples = list(session.scalars(select(ReviewSample)))
        annotations = list(session.scalars(select(ReviewAnnotation)))
        datasets = [{'dataset_id': d.dataset_id, **d.manifest} for d in session.scalars(select(DatasetVersion))]
        experiment_rows = list(session.scalars(select(Experiment)))
        manifests = {m.manifest_id: m for m in session.scalars(select(ReplayManifest))}
        experiments = [{'experiment_id': e.experiment_id, 'status': e.report['status'],
            'split': e.report['split'], 'independent_tasks': e.report['independent_tasks']} for e in experiment_rows]
        jobs = Counter(j.status for j in session.scalars(select(OfflineJob)))
        releases = [{'release_id': r.release_id, 'scope': r.scope, 'action': r.action, 'config': r.config,
                     'previous_id': r.previous_id} for r in session.scalars(select(Release).order_by(Release.created_at))]
    from .explanations import ExplanationCache
    from .evaluation_diagnostics import groundedness, human_judge_agreement, percentiles
    with db.session() as session:
        explanations = list(session.scalars(select(ExplanationCache)))
    grounding = [groundedness(e.payload) for e in explanations]
    stages = defaultdict(list)
    for event in events:
        mode = analyses[event.request_id].search_mode if event.request_id in analyses else 'normal'
        if isinstance(event.payload.get('duration_ms'), (int, float)):
            stages[(mode, event.event_type)].append(event.payload['duration_ms'])
    for analysis in analyses.values():
        if analysis.latency_ms is not None:
            stages[(analysis.search_mode, 'retrieval_pipeline')].append(analysis.latency_ms)
    by_sample = defaultdict(list)
    for annotation in annotations:
        by_sample[annotation.sample_id].append(annotation)
    common = []
    for values in by_sample.values():
        human = [a for a in values if a.annotation_kind == 'human_confirmed' and a.annotation_data.get('blind_initial') and a.annotation_data.get('action') == 'annotate']
        judge = [a for a in values if a.annotation_kind == 'ai_suggested' and a.annotation_data.get('origin') == 'ai_weak']
        if human and judge:
            common.append((human[0].annotation_data.get('grade'), judge[-1].annotation_data.get('grade')))
    groups = defaultdict(list)
    first_exposed = {}
    for e in events:
        if e.event_type == 'result_rendered':
            first_exposed.setdefault(e.task_id, e.request_id)
    conversation_success = 0
    for m in measurements:
        rid = first_exposed.get(m.task_id)
        analysis = analyses.get(rid)
        mode = analysis.search_mode if analysis else ('normal' if rid else 'unexposed')
        records = [f for f in feedback if f.measurement_id == m.measurement_id and f.owner_session == m.owner_session and f.actor_kind == m.actor_kind]
        ids = [r['property_id'] for r in m.top_k_snapshot]
        passed = [r['property_id'] for r in m.top_k_snapshot if all(v['verdict'] == 'pass' for v in r.get('property_verdicts', []) + r.get('travel_verdicts', []))]
        groups[(mode, cohort_actors[m.measurement_id], 'unassigned', 'explicit_top5_v1')].append({
            'created_at': m.freeze_at or m.created_at, 'frozen_ids': ids, 'hard_pass_ids': passed,
            'completion_status': m.completion_status, 'feedback': [{'kind': f.kind, 'label': f.label,
                'candidate_ids': f.candidate_ids, 'created_at': f.created_at} for f in records]})
        conversation_success += any(f.task_id == m.task_id and f.request_id != m.evaluation_request_id and f.label == 'positive' for f in feedback)
    qs = [{'mode': key[0], 'actor_cohort': key[1], 'experiment_arm': key[2], 'solicitation_policy': key[3],
           **qualified_success(values, window_hours=float(os.getenv('QS_FEEDBACK_WINDOW_HOURS', '24')))} for key, values in groups.items()]
    impressions = {(e.request_id, e.candidate_id) for e in events if e.event_type == 'result_impression'}
    clicks = {(e.request_id, e.candidate_id) for e in events if e.event_type == 'result_clicked'}
    route_status = Counter(r.result.get('status', 'unknown') for r in routes)
    role_usage = {}
    for role in ('parser', 'explainer', 'judge', 'improvement'):
        subset = [c for c in calls if c.role == role]
        known_tokens = [(c.usage or {}).get('total_tokens') for c in subset]
        known_tokens = [value for value in known_tokens if type(value) is int and value >= 0]
        role_usage[role] = {'calls': len(subset), 'statuses': dict(Counter(c.status for c in subset)),
            'reserved_tokens': sum(c.reserved_tokens for c in subset),
            'observed_total_tokens': sum(known_tokens) if subset and len(known_tokens) == len(subset) else None,
            'known_token_total': sum(known_tokens) if known_tokens else None,
            'token_usage_available_calls': len(known_tokens), 'token_usage_missing_calls': len(subset) - len(known_tokens),
            'measured_cost': None, 'cost_status': 'unavailable_without_provider_billing'}
    from .search_kpis import primary_kpis
    return {'metric_version': METRIC_VERSION, 'rubric_version': RUBRIC_VERSION,
        'primary_kpis': primary_kpis(measurements=measurements, feedback=feedback, events=events,
            requests=requests, analyses=analyses, explanations=explanations, experiments=experiment_rows,
            annotations=annotations, manifests=manifests, cohort_actors=cohort_actors),
        'qs': qs, 'real_qs_status': 'available' if any(q['actor_cohort'] == 'real_user' and q['S']+q['F'] for q in qs) else 'unavailable',
        'conversational_success': {'count': conversation_success, 'primary_qs_rewritten': False},
        'search': {'request_count': len(requests), 'completion': dict(Counter(r.completion_status for r in requests.values())),
                   'modes': dict(Counter(a.search_mode for a in analyses.values()))},
        'behavioral_diagnostics': {'ctr': ratio(len(clicks & impressions), len(impressions)),
            'clicks_without_valid_impressions': len(clicks-impressions), 'is_relevance_metric': False,
            'rank_stratification': 'unavailable_without_rank_at_impression_evidence'},
        'otp': {'statuses': dict(route_status), 'evaluated': len(routes),
            'cache_hits': sum(bool(r.result.get('cache_hit')) for r in routes)},
        'retrieval': {'statuses': dict(Counter(a.status for a in analyses.values())),
            'human_fixed_pool_recall': None, 'ann_report': 'docs/phase-3-ann-report.json'},
        'providers': role_usage,
        'grounding': {'claim_count': sum(g['groundedness']['denominator'] for g in grounding), 'correct': sum(g['correct'] for g in grounding), 'unsupported': sum(g['unsupported'] for g in grounding), 'contradicted': sum(g['contradicted'] for g in grounding), 'unknown': sum(g['unknown'] for g in grounding), 'no_claim_cases': sum(g['no_claim'] for g in grounding), 'rate': ratio(sum(g['correct'] for g in grounding), sum(g['groundedness']['denominator'] for g in grounding))},
        'human_judge_agreement': human_judge_agreement(common),
        'stage_latency': [{'mode': k[0], 'stage': k[1], **percentiles(v)} for k, v in sorted(stages.items())],
        'review': {'samples': len(samples), 'statuses': dict(Counter(s.status for s in samples)),
            'annotations': len(annotations), 'origins': dict(Counter(a.annotation_kind for a in annotations)),
            'independent_real_graded': sum(a.annotation_kind == 'human_confirmed' and a.annotation_data.get('grade') is not None and a.annotation_data.get('synthetic') is False for a in annotations)},
        'datasets': datasets, 'experiments': experiments, 'jobs': dict(jobs), 'releases': releases,
        'unavailable_metrics': {'human_ranking_quality': 'A fully independently judged fixed pool is required',
            'human_judge_agreement': 'Independent common graded annotations are required',
            'live_judge_quality': 'Opt-in judge and account-visible model verification required'},
        'training_status': 'not_trained_insufficient_human_labels'}
