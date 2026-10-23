"""Use existing explicit positive feedback and conservative linked intent groups."""
from pathlib import Path
p = Path('backend/app/evaluation_metrics.py')
s = p.read_text(encoding='utf-8')
start = s.index("        task_events = [f for f in events")
end = s.index("        terminal_empty =", start)
s = s[:start] + """        success = failure = False
        confirmed = set()
        for event in events:
            ids = set(event['candidate_ids'])
            if event['label'] == 'positive':
                if ids & valid:
                    confirmed = ids & valid
                    success, failure = True, False
                elif event['kind'] == 'top5':
                    success = failure = False
            elif event['kind'] == 'top5' and not ids:
                success, failure, confirmed = False, True, set()
            elif ids & confirmed:
                confirmed -= ids
                success = bool(confirmed)
""" + s[end:]
p.write_text(s, encoding='utf-8')
p = Path('backend/app/evaluation_experiments.py')
s = p.read_text(encoding='utf-8')
old = "    for manifest_id in sorted(set(manifest_ids)):\n        replay = replay_manifest(db, manifest_id, include_private=True)"
new = """    from types import SimpleNamespace
    from .annotation_datasets import linked_groups
    replays = {mid: replay_manifest(db, mid, include_private=True) for mid in sorted(set(manifest_ids))}
    group_rows = []
    for r in replays.values():
        intent = dict(r['confirmed_state'])
        intent.pop('state_revision', None)
        for pid in r['rows']:
            group_rows.append(SimpleNamespace(task_id=r['task_id'], candidate_id=pid, evidence={'confirmed_state': intent}))
    groups = linked_groups(group_rows)
    for manifest_id, replay in replays.items():"""
s = s.replace(old, new)
s = s.replace("        task = replay['task_id']", "        task = replay['task_id']\n        group = groups.get(task, task)")
s = s.replace("group_split(task, seed) != split", "group_split(group, seed) != split")
s = s.replace("pairs.append((task, difference))", "pairs.append((group, difference))")
s = s.replace("'manifest_id': manifest_id, 'task_id': task, 'mode'", "'manifest_id': manifest_id, 'task_id': task, 'intent_group': group, 'mode'")
s = s.replace("len({c.get('task_id') for c in cases if c.get('task_id')})", "len({c.get('intent_group') for c in cases if c.get('intent_group')})")
s = s.replace("rank_rows(deepcopy(eligible), state, config={})", "rank_rows(deepcopy(eligible), state, replay.get('retrieval_priority_ids', []), config={})")
s = s.replace("rank_rows(deepcopy(eligible), state, config=candidate)", "rank_rows(deepcopy(eligible), state, replay.get('retrieval_priority_ids', []), config=candidate)")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/evaluation_replay.py')
s = p.read_text(encoding='utf-8').replace("'analysis_hash': digest(analysis.metadata_json) if analysis else None,", "'analysis_hash': digest(analysis.metadata_json) if analysis else None,\n            'retrieval_priority_ids': list(analysis.priority_ids) if analysis else [],")
p.write_text(s, encoding='utf-8')
