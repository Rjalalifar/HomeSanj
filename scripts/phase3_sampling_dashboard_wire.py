"""Integrate explicit acquisition policy and evidence-based dashboard diagnostics."""
from pathlib import Path
p = Path('backend/app/review_workflow.py')
s = p.read_text(encoding='utf-8')
start = s.index("            verdicts = row['property_verdicts']", s.index('def acquire_batch'))
end = s.index('            strata[kind].append(key)', start) + len('            strata[kind].append(key)')
s = s[:start] + """            from .review_sampling import classify
            kind, reason = classify(row, frozen, labels[(rid, pid)])
            key = (rid, pid)
            frames[key] = (frozen, row, reason)
            strata[kind].append(key)""" + s[end:]
start = s.index('    rng = random.Random(seed)', s.index('def acquire_batch'))
end = s.index('    output = []', start)
s = s[:start] + '    from .review_sampling import select_batch\n    picked = select_batch(frames, strata, batch_size, seed)\n' + s[end:]
p.write_text(s, encoding='utf-8')
p = Path('backend/app/evaluation_dashboard.py')
s = p.read_text(encoding='utf-8')
s = s.replace('    groups = defaultdict(list)', "    from .explanations import ExplanationCache\n    from .evaluation_diagnostics import groundedness, human_judge_agreement, percentiles\n    with db.session() as session:\n        explanations = list(session.scalars(select(ExplanationCache)))\n    grounding = [groundedness(e.payload) for e in explanations]\n    stages = defaultdict(list)\n    for event in events:\n        mode = analyses[event.request_id].search_mode if event.request_id in analyses else 'normal'\n        if isinstance(event.payload.get('duration_ms'), (int, float)):\n            stages[(mode, event.event_type)].append(event.payload['duration_ms'])\n    for analysis in analyses.values():\n        if analysis.latency_ms is not None:\n            stages[(analysis.search_mode, 'retrieval_pipeline')].append(analysis.latency_ms)\n    by_sample = defaultdict(list)\n    for annotation in annotations:\n        by_sample[annotation.sample_id].append(annotation)\n    common = []\n    for values in by_sample.values():\n        human = [a for a in values if a.annotation_kind == 'human_confirmed' and a.annotation_data.get('blind_initial') and a.annotation_data.get('action') == 'annotate']\n        judge = [a for a in values if a.annotation_kind == 'ai_suggested' and a.annotation_data.get('origin') == 'ai_weak']\n        if human and judge:\n            common.append((human[0].annotation_data.get('grade'), judge[-1].annotation_data.get('grade')))\n    groups = defaultdict(list)")
s = s.replace("'providers': role_usage,", "'providers': role_usage,\n        'grounding': {'claim_count': sum(g['groundedness']['denominator'] for g in grounding), 'correct': sum(g['correct'] for g in grounding), 'unsupported': sum(g['unsupported'] for g in grounding), 'contradicted': sum(g['contradicted'] for g in grounding), 'unknown': sum(g['unknown'] for g in grounding), 'no_claim_cases': sum(g['no_claim'] for g in grounding), 'rate': ratio(sum(g['correct'] for g in grounding), sum(g['groundedness']['denominator'] for g in grounding))},\n        'human_judge_agreement': human_judge_agreement(common),\n        'stage_latency': [{'mode': k[0], 'stage': k[1], **percentiles(v)} for k, v in sorted(stages.items())],")
p.write_text(s, encoding='utf-8')
