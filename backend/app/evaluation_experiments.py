"""Paired frozen-input experiments and append-only release controls."""
from copy import deepcopy
from sqlalchemy import select, text
from .contracts import SearchState
from .db import utcnow, new_id
from .feedback import ReviewSample, ReviewAnnotation
from .evaluation_store import Experiment, Release
from .evaluation_replay import replay_manifest, digest
from .evaluation_metrics import ranking_metrics, grouped_bootstrap, METRIC_VERSION, RUBRIC_VERSION
from .annotation_datasets import group_split
from .ranking import rank_rows


def labels_for(db, request_id, rows):
    labels = {pid: {'grade': None, 'hard': 'unknown', 'origin': 'unjudged'} for pid in rows}
    with db.session() as session:
        samples = {s.sample_id: s for s in session.scalars(select(ReviewSample).where(ReviewSample.request_id == request_id))}
        annotations = list(session.scalars(select(ReviewAnnotation).where(ReviewAnnotation.sample_id.in_(samples))))
    superseded = {a.annotation_data.get('supersedes') for a in annotations}
    grouped = {}
    for a in annotations:
        meta = a.annotation_data
        if a.annotation_id in superseded or a.annotation_kind != 'human_confirmed' or meta.get('type') != 'relevance_grade' or meta.get('action') != 'annotate':
            continue
        sample = samples[a.sample_id]
        grouped.setdefault(sample.candidate_id, []).append(meta | {'annotation_id': a.annotation_id})
    for pid, row in rows.items():
        verdicts = row.get('property_verdicts', []) + row.get('travel_verdicts', [])
        hard = 'fail' if any(v['verdict'] == 'fail' for v in verdicts) else 'unknown' if any(v['verdict'] == 'unknown' for v in verdicts) else 'pass'
        grades = {m.get('grade') for m in grouped.get(pid, [])}
        labels[pid] = {'grade': next(iter(grades)) if len(grades) == 1 else None, 'hard': hard,
            'origin': 'human' if grades else 'unjudged', 'synthetic': row['property'].get('is_synthetic', True), 'annotation_ids': [m['annotation_id'] for m in grouped.get(pid, [])]}
    return labels


def compare(db, manifest_ids, candidate=None, *, split='validation', seed=17):
    candidate = candidate or {'rent_weight_multiplier': 1.25}
    from .annotation_datasets import export_dataset
    label_dataset = export_dataset(db, seed=seed)
    cases, pairs = [], []
    if split == 'holdout':
        with db.session() as session:
            previous = list(session.scalars(select(Experiment)))
        validation = [e for e in previous if e.report['split'] == 'validation' and e.report['candidate_config'] == candidate and e.report['status'] == 'offline_measured' and e.report.get('label_dataset_id') == label_dataset['dataset_id']]
        if not validation:
            raise ValueError('Final holdout requires a measured validation experiment for this candidate first')
        used = [e for e in previous if e.report['split'] == 'holdout' and e.report.get('label_dataset_id') == label_dataset['dataset_id']]
        if used:
            raise ValueError('This holdout milestone has already been consumed; create a new versioned dataset before another milestone')
    from types import SimpleNamespace
    from .annotation_datasets import linked_groups
    replays = {mid: replay_manifest(db, mid, include_private=True) for mid in sorted(set(manifest_ids))}
    group_rows = []
    for r in replays.values():
        intent = dict(r['confirmed_state'])
        intent.pop('state_revision', None)
        for pid in r['rows']:
            group_rows.append(SimpleNamespace(task_id=r['task_id'], candidate_id=pid, evidence={'confirmed_state': intent}))
    groups = linked_groups(group_rows)
    for manifest_id, replay in replays.items():
        if replay['status'] != 'ok':
            cases.append({'manifest_id': manifest_id, 'status': 'partial_replay', 'missing': replay['missing_evidence']})
            continue
        task = replay['task_id']
        group = label_dataset['task_groups'].get(task, {}).get('group_id', groups.get(task, task))
        # Group assignment is fixed before any candidate metric is observed.
        if split != 'mechanical_demo' and group_split(group, seed) != split:
            continue
        state = SearchState.model_validate(replay['state'])
        eligible = [replay['rows'][r['property_id']] for r in replay['original_ranking'] if r['property_id'] in replay['rows']]
        baseline_rows = rank_rows(deepcopy(eligible), state, replay.get('retrieval_priority_ids', []), config={})
        candidate_rows = rank_rows(deepcopy(eligible), state, replay.get('retrieval_priority_ids', []), config=candidate)
        orders = {'baseline': [r['property']['property_id'] for r in baseline_rows],
                  'candidate': [r['property']['property_id'] for r in candidate_rows]}
        labels = labels_for(db, replay['request_id'], replay['rows'])
        if state.travel.destination and not (state.accessibility and state.accessibility.enabled):
            for pid, row in replay['rows'].items():
                if row.get('route_status') != 'ok' or not row.get('selected_itinerary'):
                    labels[pid]['hard'] = 'unknown'
        results = {name: ranking_metrics(order, labels) for name, order in orders.items()}
        left, right = (results[name]['ndcg_at_5']['value'] for name in ('baseline', 'candidate'))
        difference = right - left if left is not None and right is not None else None
        pairs.append((group, difference))
        cases.append({'manifest_id': manifest_id, 'task_id': task, 'intent_group': group, 'mode': replay['mode'],
            'actor_cohort': replay['actor_cohort'], 'split': split, 'dataset': replay['versions'].get('dataset'),
            'versions': replay['versions'], 'scope': replay['ranking_scope'], 'status': 'ok',
            'baseline_ids': orders['baseline'][:20], 'candidate_ids': orders['candidate'][:20],
            'changed_top5': orders['baseline'][:5] != orders['candidate'][:5], 'metrics': results,
            'judged_coverage': results['baseline']['judged_coverage'], 'label_origin': 'human' if any(x['origin'] == 'human' for x in labels.values()) else 'unjudged',
            'frozen_labels': labels, 'labels_hash': digest(labels), 'inventory_hash': digest(replay['candidate_refs']), 'route_hash': digest(replay['route_refs'])})
    uncertainty = grouped_bootstrap(pairs, seed)
    report = {'experiment_version': 'paired-frozen-ranker-1', 'declared_variable': 'rent_weight_multiplier',
        'baseline_config': {}, 'candidate_config': candidate, 'label_dataset_id': label_dataset['dataset_id'], 'label_dataset_sha256': label_dataset['sha256'], 'fixed_inputs': 'same canonical candidate facts, hard eligibility, route evidence, labels and semantic priority',
        'metric_version': METRIC_VERSION, 'rubric_version': RUBRIC_VERSION, 'split': split, 'seed': seed,
        'hypothesis': 'Increasing the rent weight by 25 percent may better match independently reviewed preference for lower rent',
        'primary_metric': 'ndcg_at_5', 'target_cohort': 'independent_human_judged_fixed_pool',
        'error_evidence_annotation_ids': sorted({aid for c in cases for label in c.get('frozen_labels', {}).values() for aid in label.get('annotation_ids', [])}),
        'reviewer_time_seconds': None, 'candidate_diff': {'rent_weight_multiplier': {'before': 1.0, 'after': candidate['rent_weight_multiplier']}},
        'guardrail_policy': {'hard_fail': 0, 'unknown_as_pass': 0, 'privacy_leaks': 0, 'minimum_human_labels': 200, 'minimum_independent_groups': 30, 'latency_cost_coverage': 'explicit human sign-off on measured evidence'},
        'cases': cases, 'uncertainty': uncertainty, 'independent_tasks': len({c.get('intent_group') for c in cases if c.get('intent_group')}),
        'status': 'insufficient_evidence' if uncertainty['status'] != 'ok' else 'offline_measured',
        'real_user_causal_lift': None, 'production_promotion': 'blocked_pending_independent_human_evidence_and_approval',
        'not_run': {'live_llm': 'offline replay makes no provider calls', 'real_user_causal_experiment': 'no randomized real cohort'},
        'latency_cost_policy': 'offline replay excludes service latency; use separately observed stage telemetry'}
    experiment_id = 'experiment_' + digest(report)
    with db.session.begin() as session:
        if not session.get(Experiment, experiment_id):
            session.add(Experiment(experiment_id=experiment_id, report=report, created_at=utcnow()))
    return {'experiment_id': experiment_id, **report}


def latest_release(db, scope='test'):
    with db.session() as session:
        row = session.scalar(select(Release).where(Release.scope == scope).order_by(Release.created_at.desc(), Release.release_id.desc()).limit(1))
        return {'release_id': row.release_id, 'config': row.config, 'action': row.action} if row else {'release_id': None, 'config': {}, 'action': 'baseline'}


def production_gates(db, report):
    with db.session() as session:
        annotations = list(session.scalars(select(ReviewAnnotation).where(ReviewAnnotation.annotation_kind == 'human_confirmed')))
        real = [a for a in annotations if a.annotation_data.get('grade') is not None and a.annotation_data.get('synthetic') is False]
    return {'minimum_human_labels': len(real) >= 200,
        'independent_tasks': report.get('uncertainty', {}).get('independent_tasks', 0) >= 30,
        'positive_paired_lower_bound': bool(report.get('uncertainty', {}).get('interval') and report['uncertainty']['interval'][0] > 0),
        'final_holdout': report.get('split') == 'holdout',
        'critical_privacy_grounding_latency_cost_guardrails_signed': False}


def release(db, experiment_id=None, *, scope='test', action='promote', approved_by='test_operator', target_id=None, approval_id=None):
    if scope not in ('test', 'production') or action not in ('promote', 'rollback'):
        raise ValueError('Invalid release scope or action')
    with db.session() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        previous = session.scalar(select(Release).where(Release.scope == scope).order_by(Release.created_at.desc(), Release.release_id.desc()).limit(1))
        if action == 'rollback':
            target = session.get(Release, target_id) if target_id else None
            if target_id and (not target or target.scope != scope):
                raise ValueError('Rollback target must exist in the same scope')
            config = target.config if target else {}
        else:
            experiment = session.get(Experiment, experiment_id)
            if not experiment:
                raise ValueError('Unknown experiment')
            config = experiment.report['candidate_config']
            if scope == 'production':
                from .release_control import verify_promotion
                gates = verify_promotion(session, experiment, approval_id, approved_by)
                if not all(gates.values()):
                    raise ValueError('Production promotion blocked: ' + ', '.join(k for k, passed in gates.items() if not passed))
        record = Release(release_id=new_id('release'), scope=scope, action=action, config=config,
            previous_id=previous.release_id if previous else None, experiment_id=experiment_id,
            approved_by=approved_by, created_at=utcnow())
        session.add(record)
        session.commit()
        return {'release_id': record.release_id, 'scope': scope, 'action': action, 'config': config,
                'previous_id': record.previous_id, 'production_changed': scope == 'production'}
