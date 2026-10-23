"""Preserve experiment label evidence and separate background provider budgets."""
from pathlib import Path
p = Path('backend/app/llm.py')
s = p.read_text(encoding='utf-8')
start = s.index("            count, tokens = session.execute", s.index('def _reserve'))
end = s.index("            reservation = None", start)
s = s[:start] + """            if role in ('judge', 'improvement'):
                prefix = ROLE_ENV[role]
                role_count, role_tokens = session.execute(select(func.count(), func.coalesce(func.sum(ProviderCall.reserved_tokens), 0)).where(ProviderCall.day == day, ProviderCall.role == role)).one()
                if role_count >= int(os.getenv(prefix + '_DAILY_MAX_REQUESTS', '100')) or role_tokens + reserved > int(os.getenv(prefix + '_DAILY_MAX_RESERVED_TOKENS', '30000')):
                    raise ProviderError('budget_stopped')
                from datetime import timedelta
                recent = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
                minute_count = session.scalar(select(func.count()).select_from(ProviderCall).where(ProviderCall.role == role, ProviderCall.created_at >= recent))
                if minute_count >= int(os.getenv(prefix + '_MAX_CALLS_PER_MINUTE', '10')):
                    raise ProviderError('rate_budget_stopped')
                recent_reservation = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat()
                active = session.scalar(select(func.count()).select_from(ProviderCall).where(ProviderCall.role == role, ProviderCall.status == 'reserved', ProviderCall.created_at >= recent_reservation))
                if active >= int(os.getenv(prefix + '_MAX_CONCURRENCY', '1')):
                    raise ProviderError('concurrency_budget_stopped')
            else:
                count, tokens = session.execute(select(func.count(), func.coalesce(func.sum(ProviderCall.reserved_tokens), 0)).where(ProviderCall.day == day, ProviderCall.role.in_(['parser', 'explainer']))).one()
                if count >= self.daily_limit or tokens + reserved > self.token_limit:
                    raise ProviderError('budget_stopped')
""" + s[end:]
p.write_text(s, encoding='utf-8')
p = Path('backend/app/offline_evaluation.py')
s = p.read_text(encoding='utf-8').replace("'cost_budget_unverifiable')", "'cost_budget_unverifiable', 'rate_budget_stopped', 'concurrency_budget_stopped')")
s = s.replace("'reason': exc.status}", "'reason': exc.status, 'queue_status': 'deferred_due_to_budget' if 'budget' in exc.status else 'not_run'}")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/evaluation_experiments.py')
s = p.read_text(encoding='utf-8')
s = s.replace("grouped.setdefault(sample.candidate_id, []).append(meta)", "grouped.setdefault(sample.candidate_id, []).append(meta | {'annotation_id': a.annotation_id})")
s = s.replace("'synthetic': row['property'].get('is_synthetic', True)}", "'synthetic': row['property'].get('is_synthetic', True), 'annotation_ids': [m['annotation_id'] for m in grouped.get(pid, [])]}")
s = s.replace("'labels_hash': digest(labels),", "'frozen_labels': labels, 'labels_hash': digest(labels),")
s = s.replace("'metric_version': METRIC_VERSION, 'rubric_version': RUBRIC_VERSION, 'split': split, 'seed': seed,", "'metric_version': METRIC_VERSION, 'rubric_version': RUBRIC_VERSION, 'split': split, 'seed': seed,\n        'hypothesis': 'Increasing the rent weight by 25 percent may better match independently reviewed preference for lower rent',\n        'primary_metric': 'ndcg_at_5', 'target_cohort': 'independent_human_judged_fixed_pool',\n        'error_evidence_annotation_ids': sorted({aid for c in cases for label in c.get('frozen_labels', {}).values() for aid in label.get('annotation_ids', [])}),\n        'reviewer_time_seconds': None, 'candidate_diff': {'rent_weight_multiplier': {'before': 1.0, 'after': candidate['rent_weight_multiplier']}},\n        'guardrail_policy': {'hard_fail': 0, 'unknown_as_pass': 0, 'privacy_leaks': 0, 'minimum_human_labels': 200, 'minimum_independent_groups': 30, 'latency_cost_coverage': 'explicit human sign-off on measured evidence'},")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/annotation_datasets.py')
s = p.read_text(encoding='utf-8')
s = s.replace("'evidence_hash': digest(sample.evidence),", "'manifest_id': sample.evidence.get('manifest_id'), 'source_versions': sample.evidence.get('versions', {}),\n                'frozen_evidence_reference': {'table': 'review_samples', 'sample_id': sample.sample_id},\n                'evidence_hash': digest(sample.evidence),")
s = s.replace("        state = sample.evidence.get('confirmed_state')", "        state = deepcopy(sample.evidence.get('confirmed_state'))\n        if state:\n            state.pop('state_revision', None)")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/evaluation_metrics.py')
s = p.read_text(encoding='utf-8')
s = s.replace("    if not item or item.get('grade') is None or item.get('hard') == 'unknown':", "    if item and item.get('hard') == 'fail':\n        return False\n    if not item or item.get('grade') is None or item.get('hard') != 'pass':")
p.write_text(s, encoding='utf-8')
