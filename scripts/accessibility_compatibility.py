"""Retain legacy tests and align explanation evidence with automatic accessibility."""
from pathlib import Path


def replace(path, old, new):
    target = Path(path)
    source = target.read_text(encoding='utf-8-sig')
    if new in source:
        return
    if old not in source:
        raise RuntimeError(f'Missing source in {path}: {old[:90]}')
    target.write_text(source.replace(old, new, 1), encoding='utf-8')


p = 'backend/app/accessibility.py'
replace(p, "time_mode='DEPART_AT', include_walk_only=True)", "time_mode='DEPART_AT')")
replace(p, "        travel['modes'] = worker.adapter.settings.supported_modes", "        travel['modes'] = worker.adapter.settings.supported_modes\n        travel['include_walk_only'] = True")
p = 'backend/app/explanations.py'
replace(p, "EXPLANATION_VERSION = 'verified-templates-2'", "EXPLANATION_VERSION = 'verified-templates-3-accessibility'")
replace(p, "    'transfers': ('تعداد تعویض', 'بار', 'route'),", "    'transfers': ('تعداد تعویض', 'بار', 'route'),\n    'straight_line_meters': ('فاصلهٔ مستقیم تا ایستگاه', 'متر', 'accessibility'),")
replace(p, "'walk_duration_seconds', 'walk_distance_meters', 'transfers']", "'walk_duration_seconds', 'walk_distance_meters', 'transfers', 'straight_line_meters']")
replace(p, "    routing = snapshot['state']['travel'].get('destination') is not None\n    rows = []", "    automatic = bool((snapshot['state'].get('accessibility') or {}).get('enabled'))\n    routing = snapshot['state']['travel'].get('destination') is not None and not automatic\n    rows = []")
replace(p, "            value = row['property'].get(field) if origin == 'property' else (row.get('selected_itinerary') or {}).get(field)", """            access = row.get('accessibility') or {}
            value = row['property'].get(field) if origin == 'property' else access.get(field) if origin == 'accessibility' else (row.get('selected_itinerary') or {}).get(field)
            if access and origin == 'route':
                value = access.get(field) if access.get('status') == 'ok' else None""")
replace(p, "    if routing:\n        fields += ['total_duration_seconds', 'walk_duration_seconds', 'transfers']", """    automatic = bool((snapshot['state'].get('accessibility') or {}).get('enabled'))
    if automatic:
        fields += ['total_duration_seconds', 'walk_duration_seconds'] if routing else ['straight_line_meters', 'walk_duration_seconds', 'walk_distance_meters']
    elif routing:
        fields += ['total_duration_seconds', 'walk_duration_seconds', 'transfers']""")
replace(p, "    if not routing:\n        limitations.append('مقصد فعال نیست؛ رفت‌وآمد محاسبه نشده و در این مقایسه دخالت ندارد.')", """    if automatic and not routing:
        limitations.append('فاصلهٔ مستقیم تا ایستگاه با طول مسیر واقعی پیاده‌روی متفاوت است؛ وضعیت نامعلوم، دسترسی تأییدشده نیست.')
    elif not routing:
        limitations.append('مقصد فعال نیست؛ رفت‌وآمد محاسبه نشده و در این مقایسه دخالت ندارد.')""")
p = 'backend/app/event_evidence.py'
replace(p, "                if not req.state['travel'].get('destination') or result.get('status') == 'ok':", "                if (req.state.get('accessibility') or {}).get('enabled') or not req.state['travel'].get('destination') or result.get('status') == 'ok':")
p = 'backend/app/evaluation_experiments.py'
replace(p, '        if state.travel.destination:', '        if state.travel.destination and not (state.accessibility and state.accessibility.enabled):')
p = 'tests/test_phase2_integration.py'
replace(p, "        state['travel'].update(destination={'latitude': 1, 'longitude': 1, 'confirmed': True}, date='2026-10-20', time='08:00:00')", "        state['accessibility'] = None\n        state['travel'].update(destination={'latitude': 1, 'longitude': 1, 'confirmed': True}, date='2026-10-20', time='08:00:00')")
p = 'tests/test_phase3_api_diagnostics.py'
replace(p, "        state = client.get('/api/state/default').json()", "        state = client.get('/api/state/default').json()\n        state['accessibility'] = None")
p = 'scripts/serve_phase3_browser.py'
replace(p, 'app = create_app(settings, database=database, geo=geo, adapter=OTPAdapter(OTPSettings()))', """live_accessibility = os.getenv('ACCESSIBILITY_BROWSER_LIVE_OTP') == 'true'
if live_accessibility:
    settings.batch_limit = 3
app = create_app(settings, database=database, geo=geo,
    adapter=OTPAdapter(OTPSettings.from_env() if live_accessibility else OTPSettings()))""")
print('Aligned automatic input identity, explanation facts, event eligibility and legacy regression cases.')
