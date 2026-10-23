"""Repair proven task-feedback label leakage without changing historical freezes."""
from pathlib import Path
p = Path('backend/app/feedback.py')
s = p.read_text(encoding='utf-8')
s = s.replace("                if explicit_none:\n                    labels.update({pid: 0 for pid in frozen_ids})\n                else:\n                    labels.update({pid: 1 for pid in record.candidate_ids if pid in frozen_ids})", "                if not explicit_none:\n                    labels.update({pid: 1 for pid in record.candidate_ids if pid in frozen_ids})")
s = s.replace("    success = True if positives else False if complete_labels or explicit_none else None", "    success = False if explicit_none else True if positives else False if complete_labels else None")
s = s.replace("        'precision_at_5': positives / 5 if complete_labels else None,\n        'ndcg_at_5': (dcg / idcg if idcg else 0.0) if complete_labels else None,", "        'precision_at_5': None, 'ndcg_at_5': None,\n        'ranking_metrics_status': 'use_independently_graded_fixed_pool_evaluator',\n        'explicit_feedback_positive_fraction_at_5': positives / 5 if complete_labels else None,\n        'feedback_interpretation_version': 'task_outcome_not_candidate_grade-1',")
s = s.replace("        'denominator_policy': 'Success uses confirmed tasks; unresolved tasks are reported separately. Precision uses five slots only when all returned positions are judged; unreturned slots are empty.'", "        'denominator_policy': 'Immediate explicit outcome diagnostic only; Phase-3 qualified success uses its separate 24-hour window. Task rejection does not label candidates. Ranking metrics require independently graded reference pools.'")
p.write_text(s, encoding='utf-8')
p = Path('tests/test_feedback.py')
s = p.read_text(encoding='utf-8').replace("assert metrics['success_at_5'] is False and metrics['precision_at_5'] == 0", "assert metrics['success_at_5'] is False and metrics['precision_at_5'] is None")
s = s.replace("assert metrics['unjudged_count'] == 0", "assert metrics['unjudged_count'] == 2")
p.write_text(s, encoding='utf-8')
