"""Read-only primary KPI projection over existing Phase 3 evidence."""
from collections import Counter
import math
import os

from .evaluation_metrics import METRIC_VERSION, QS_VERSION, qualified_success, ratio
from .evaluation_replay import digest
from .evaluation_diagnostics import groundedness


def primary_kpis(*, measurements, feedback, events, requests, analyses, explanations,
                 experiments, annotations, manifests, cohort_actors=None):
    def mode_of(request_id):
        analysis = analyses.get(request_id)
        mode = analysis.search_mode if analysis else None
        return mode if mode in ('normal', 'advanced') else 'unknown'

    def context(req):
        if not req:
            return 'unknown'
        if (req.state.get('accessibility') or {}).get('enabled'):
            return 'destination' if req.state.get('travel', {}).get('destination') else 'nearby_stop'
        return 'legacy'

    def card(mode, value, size, total, reason, policy, cohort, dates, **extra):
        dates = sorted(date for date in dates if date)
        return {'source_mode': mode, 'status': 'ok' if value is not None else 'insufficient_data',
            'value': value, 'reason': None if value is not None else reason, 'sample_size': size,
            'coverage': ratio(size, total), 'policy_version': policy, 'cohort': cohort,
            'period': {'start': dates[0] if dates else None, 'end': dates[-1] if dates else None,
                       'basis': 'all_stored_observations_in_named_cohort'}, **extra}

    first_exposed = {}
    for event in events:
        if event.event_type == 'result_rendered' and getattr(event, 'task_id', None):
            first_exposed.setdefault((event.task_id, event.owner_session), event.request_id)
    result = {}
    for mode in ('normal', 'advanced'):
        current = [m for m in measurements if m.actor_kind == 'real_user' and
                   (cohort_actors or {}).get(m.measurement_id, m.actor_kind) == 'real_user' and
                   mode_of(first_exposed.get((m.task_id, m.owner_session), m.evaluation_request_id)) == mode]
        tasks = []
        for m in current:
            req = requests.get(m.evaluation_request_id)
            final = bool(m.freeze_at and m.completion_status == 'final' and req and
                         req.snapshot_id == m.snapshot_id and req.completion_status == 'complete')
            rows = m.top_k_snapshot[:5] if final else []
            passed = [r['property_id'] for r in rows if r.get('property', {}).get('is_synthetic') is False
                and (r.get('selected_itinerary') or {}).get('source_kind') != 'synthetic_fixture'
                and all(v['verdict'] == 'pass' for v in r.get('property_verdicts', []) + r.get('travel_verdicts', []))]
            records = [f for f in feedback if final and f.actor_kind == 'real_user' and
                f.measurement_id == m.measurement_id and f.owner_session == m.owner_session and
                f.request_id == m.evaluation_request_id and f.snapshot_id == m.snapshot_id and
                f.task_id == m.task_id and f.created_at >= m.freeze_at]
            tasks.append({'created_at': m.freeze_at or m.created_at,
                'frozen_ids': [r['property_id'] for r in rows], 'hard_pass_ids': passed,
                'completion_status': 'complete' if final else m.completion_status,
                'feedback': [{'kind': f.kind, 'label': f.label, 'candidate_ids': f.candidate_ids,
                              'created_at': f.created_at} for f in records]})
        qs = qualified_success(tasks, window_hours=float(os.getenv('QS_FEEDBACK_WINDOW_HOURS', '24')))
        result[mode] = {'qs_at_5': card(mode, qs['qs_at_5']['value'], qs['S'] + qs['F'], qs['N'],
            'No resolved valid real-user outcome in the first frozen final Top-5.', QS_VERSION,
            'real_user; first_exposed_mode; explicit_top5_v1; unassigned_experiment',
            [m.freeze_at or m.created_at for m in current],
            counts={key: qs[key] for key in ('N', 'S', 'F', 'U', 'pending')},
            context_counts=dict(Counter(context(requests.get(m.evaluation_request_id)) for m in current)),
            window_hours=qs['window_hours'])}

    # Use one existing label-dataset/split cohort; repeated experiments are not new samples.
    available = sorted((e for e in experiments if e.report.get('metric_version') == METRIC_VERSION
        and e.report.get('label_dataset_id') and e.report.get('label_dataset_sha256')),
        key=lambda e: e.created_at, reverse=True)
    cohort = None
    if available:
        report = available[0].report
        cohort = (report['label_dataset_id'], report['label_dataset_sha256'], report.get('split'))
    human = {a.annotation_id: a for a in annotations if a.annotation_kind == 'human_confirmed'
        and not a.needs_human_review and a.annotation_data.get('origin') == 'human'
        and a.annotation_data.get('type') == 'relevance_grade' and a.annotation_data.get('action') == 'annotate'}
    pools = {'normal': {}, 'advanced': {}}
    for record in available:
        report = record.report
        if (report['label_dataset_id'], report['label_dataset_sha256'], report.get('split')) != cohort:
            continue
        for case in report.get('cases', []):
            manifest = manifests.get(case.get('manifest_id'))
            mode = mode_of(manifest.request_id) if manifest else 'unknown'
            if mode not in pools or case.get('mode') != mode:
                continue
            labels = case.get('frozen_labels', {})
            metric = case.get('metrics', {}).get('baseline', {})
            value = metric.get('ndcg_at_5', {}).get('value')
            valid = (case.get('status') == 'ok' and case.get('inventory_hash') and bool(labels)
                and case.get('labels_hash') == digest(labels) and metric.get('metric_version') == METRIC_VERSION
                and metric.get('fully_judged_pool') is True and isinstance(value, (int, float))
                and math.isfinite(value) and 0 <= value <= 1
                and all(label.get('origin') == 'human' and label.get('grade') in (0, 1, 2, 3)
                    and label.get('annotation_ids') and all(aid in human and
                        human[aid].annotation_data.get('grade') == label['grade'] for aid in label['annotation_ids'])
                    for label in labels.values()))
            pools[mode].setdefault(case['manifest_id'], (value if valid else None, record.created_at, manifest.request_id))
    for mode, cases in pools.items():
        values = [value for value, _, _ in cases.values() if value is not None]
        result[mode]['human_ndcg_at_5'] = card(mode, sum(values) / len(values) if values else None,
            len(values), len(cases), 'No fully human-graded fixed versioned pool with nonzero IDCG.',
            METRIC_VERSION, 'human_fixed_pool:' + ':'.join(str(v) for v in cohort) if cohort else 'human_fixed_pool_unavailable',
            [date for _, date, _ in cases.values()],
            context_counts=dict(Counter(context(requests.get(rid)) for _, _, rid in cases.values())))

    normal = [r for rid, r in requests.items() if mode_of(rid) == 'normal']
    result['normal']['finalized_search_p95_ms'] = card('normal', None, 0, len(normal),
        'missing_instrumentation: search_submitted is recorded after candidate filtering; '
        'no dependable submission-to-valid-final-result interval including required OTP completion is stored.',
        None, 'normal_requests; end_to_end_timing_unavailable', [r.created_at for r in normal], unit='ms',
        context_counts=dict(Counter(context(r) for r in normal)))

    from .explanations import TypedClaim
    ai = [e for e in explanations if mode_of(e.request_id) == 'advanced'
        and e.payload.get('mode') == 'ai_selected_verified_templates' and e.payload.get('ai_status') == 'ok'
        and str(e.payload.get('model_version', '')).lower().startswith('gemini-')]
    supported = evaluated = total = 0
    for row in ai:
        claims = row.payload.get('ai_selected_claims', [])
        total += len(claims)
        for item in claims:
            try:
                claim = TypedClaim.model_validate(item.get('claim'))
            except ValueError:
                continue
            if claim.operator == 'unknown':
                continue
            check = groundedness({'evidence': row.payload.get('evidence', {}), 'ai_selected_claims': [item]})
            supported += check['correct']
            evaluated += 1
    result['advanced']['gemini_groundedness'] = card('advanced', supported / evaluated if evaluated else None,
        evaluated, total, 'No evaluated verifiable Gemini-selected claims; deterministic explanations are excluded.',
        ','.join(sorted({e.payload['schema_version'] for e in ai if e.payload.get('schema_version')})) or None,
        'stored_gemini_selected_claims; existing_deterministic_claim_to_evidence_checks', [e.created_at for e in ai],
        counts={'supported': supported, 'evaluated': evaluated, 'uncheckable': total - evaluated},
        context_counts=dict(Counter(context(requests.get(e.request_id)) for e in ai)))
    return result
