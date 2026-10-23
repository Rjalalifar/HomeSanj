"""Apply focused event, replay presentation, and stale-intent safeguards."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'backend/app/feedback.py'
content = path.read_text(encoding='utf-8')
content = content.replace('from .llm import ProviderError', 'from .llm import ProviderError\nfrom .event_evidence import event_snapshot, request_actor')
content = content.replace("    if any(row['property'].get('is_synthetic') for row in source_rows):", "    if snapshot.get('actor_kind') == 'demo' or any(row['property'].get('is_synthetic') or (row.get('selected_itinerary') or {}).get('source_kind') == 'synthetic_fixture' for row in source_rows):")
content = content.replace("allowed_property = ['property_id',", "allowed_property = ['title_fa', 'property_id',")
needle = '    instant = now or datetime.now(timezone.utc)\n    snapshot, rows = eligible_snapshot(db, request_id)'
replacement = '''    instant = now or datetime.now(timezone.utc)
    with db.session() as session:
        req = session.get(SearchRequest, request_id)
        if req is None:
            raise KeyError(request_id)
        frozen = session.scalar(select(Measurement).where(Measurement.task_id == req.task_id))
        if frozen is not None and frozen.owner_session != owner_session:
            raise HTTPException(403, 'Measurement belongs to another session')
        if frozen is not None and frozen.freeze_at is not None:
            return frozen
    snapshot, rows = eligible_snapshot(db, request_id)'''
content = content.replace(needle, replacement)
content = content.replace("actor_kind='demo' if str(req.versions.get('dataset', '')).startswith('tehran-2020') else 'real_user'", 'actor_kind=request_actor(session, request_id)')
start = content.index('def record_event(')
end = content.index('\ndef submit_feedback(', start)
section = content[start:end].replace('snapshot, rows = eligible_snapshot(db, data.request_id)', 'snapshot, rows = event_snapshot(db, data.request_id, data.candidate_id)')
content = content[:start] + section + content[end:]
path.write_text(content, encoding='utf-8')
path = root / 'backend/app/search.py'
content = path.read_text(encoding='utf-8').replace('from .ranking import rank_rows, policy', 'from .ranking import rank_rows, policy\nfrom .event_evidence import qualifying_alternatives')
content = content.replace("'travel_verdicts': result.get('verdicts', []) if result else [],", "'travel_verdicts': result.get('verdicts', []) if result else [],\n                   'qualifying_itineraries': qualifying_alternatives(result),")
path.write_text(content, encoding='utf-8')
path = root / 'frontend/src/PhaseTwoApp.tsx'
content = path.read_text(encoding='utf-8')
content = content.replace("const [queryText, setQueryText] = useState('');", "const [queryText, setQueryText] = useState('');\n  const queryRef = useRef(queryText); queryRef.current = queryText;")
content = content.replace('if (currentKey.current === expected) { setProposal(value);', 'if (currentKey.current === expected && queryRef.current === text) { setProposal(value);')
content = content.replace("String(leg.route_short_name ?? leg.route ?? leg.line ?? '')", "lineName(leg)")
content = content.replace('function RouteDetails(', '''function lineName(leg: Record<string, unknown>): string {
  const line = leg.route ?? leg.line;
  if (line && typeof line === 'object') {
    const value = line as Record<string, unknown>;
    return String(value.publicCode ?? value.name ?? value.id ?? '');
  }
  return String(leg.route_short_name ?? line ?? '');
}

function RouteDetails(''')
path.write_text(content, encoding='utf-8')
