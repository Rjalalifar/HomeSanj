"""Connect verified foot-only routing and preserve new evidence in existing replay."""
from pathlib import Path


def replace(path, old, new):
    target = Path(path)
    source = target.read_text(encoding='utf-8-sig')
    if new and new in source:
        return
    if old not in source:
        raise RuntimeError(f'Missing source in {path}: {old[:90]}')
    target.write_text(source.replace(old, new, 1), encoding='utf-8')


p = 'backend/app/routing.py'
replace(p, '        requested_modes = travel.get("modes") or self.settings.supported_modes',
    '''        pedestrian = travel.get("routing_profile") == "walk_only"
        if pedestrian and self.settings.api_type != "transmodel_v3":
            return {"status": "not_configured", "itineraries": [], "error": "Pedestrian capability not verified for this API type"}
        requested_modes = [] if pedestrian else travel.get("modes") or self.settings.supported_modes''')
replace(p, '        if not requested_modes or set(requested_modes) - set(self.settings.supported_modes):',
    '        if not pedestrian and (not requested_modes or set(requested_modes) - set(self.settings.supported_modes)):')
replace(p, '            return await self._client.post(url, json={"query": TRANSMODEL_QUERY, "variables": variables}, timeout=self.settings.timeout_seconds)',
    '''            if travel.get("routing_profile") == "walk_only":
                # Installed schema and a recorded live contract verify empty transit modes.
                variables["modes"] = {"directMode": "foot", "transportModes": []}
            return await self._client.post(url, json={"query": TRANSMODEL_QUERY, "variables": variables}, timeout=self.settings.timeout_seconds)''')
replace(p, '        response_id = "synthetic_" + cache_key(origin, travel, self.settings)[:24]',
    '''        if travel.get("routing_profile") == "walk_only":
            raw["legs"] = [{"mode": "WALK", "transitLeg": False, "duration": duration, "distance": 1500}]
        response_id = "synthetic_" + cache_key(origin, travel, self.settings)[:24]''')
p = 'backend/app/accessibility_ranking.py'
replace(p, "    mode = _get(access, 'mode', 'destination')", "    mode = _get(access, 'mode') or ('destination' if _get(_get(state, 'travel'), 'destination') else 'nearby_stop')")
p = 'backend/app/evaluation_replay.py'
replace(p, "'candidate_refs': [{'property_id': c.property_id, 'hash': digest([c.property_snapshot, c.property_verdicts])} for c in candidates],",
    "'candidate_refs': [{'property_id': c.property_id, 'hash': digest([c.property_snapshot, c.property_verdicts]), **({'accessibility_hash': digest(c.accessibility_snapshot)} if c.accessibility_snapshot else {})} for c in candidates],")
replace(p, "            else:\n                facts = deepcopy(row.property_snapshot)",
    """            elif ref.get('accessibility_hash') and digest(row.accessibility_snapshot) != ref['accessibility_hash']:
                missing.append('accessibility:' + ref['property_id'])
            else:
                facts = deepcopy(row.property_snapshot)""")
replace(p, "rows[ref['property_id']] = {'property': facts, 'property_verdicts': row.property_verdicts}",
    "rows[ref['property_id']] = {'property': facts, 'property_verdicts': row.property_verdicts, **({'accessibility': deepcopy(row.accessibility_snapshot)} if ref.get('accessibility_hash') else {})}")
replace(p, "            selected = result.get('selected_itinerary')", """            if row.get('accessibility') and result.get('accessibility'):
                from .accessibility import select_result
                saved_sort = (req.state if req else payload['confirmed_state']).get('sort')
                result = select_result(result, 'less_walking' if saved_sort in ('walk_time_asc', 'stop_walk_time_asc') else 'faster_commute')
                row['accessibility'] = result['accessibility']
            selected = result.get('selected_itinerary')""")
print('Enabled verified pedestrian profile and content-addressed accessibility replay.')
