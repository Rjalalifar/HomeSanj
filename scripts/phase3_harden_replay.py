"""Keep public replay sanitized and distinguish delivery captures from later backfills."""
from pathlib import Path
p = Path('backend/app/evaluation.py')
s = p.read_text(encoding='utf-8').replace('catalog.lexical(query, advanced=True)', 'catalog.lexical(query, any_token=True)')
p.write_text(s, encoding='utf-8')
p = Path('backend/app/evaluation_replay.py')
s = p.read_text(encoding='utf-8').replace('def freeze_manifest(db, request_id):', 'def freeze_manifest(db, request_id, *, delivery_capture=False):')
s = s.replace("'capture_semantics': 'ranking_at_manifest_capture',\n            'historical_original_ranking_verified': False", "'capture_semantics': 'delivery_capture' if delivery_capture else 'ranking_at_manifest_capture',\n            'historical_original_ranking_verified': delivery_capture")
s = s.replace("            row['selected_itinerary'] = selected", "            if selected and not include_private:\n                allowed_route = ('itinerary_id', 'total_duration_seconds', 'walk_duration_seconds', 'walk_distance_meters', 'transfers', 'source_kind', 'schedule_basis', 'realtime_status', 'location_accuracy')\n                selected = {k: selected.get(k) for k in allowed_route}\n            row['selected_itinerary'] = selected\n            row['route_status'] = result.get('status', 'not_evaluated')")
if 'def capture_delivery' not in s:
    s += '''

def capture_delivery(db, snapshot):
    if snapshot.get('completion_status') != 'complete' or snapshot.get('semantic', {}).get('status') == 'pending':
        return
    with db.session() as session:
        manifests = session.scalars(select(ReplayManifest).where(ReplayManifest.request_id == snapshot['request_id']))
        if any(m.payload.get('historical_original_ranking_verified') for m in manifests):
            return
    freeze_manifest(db, snapshot['request_id'], delivery_capture=True)
'''
p.write_text(s, encoding='utf-8')
