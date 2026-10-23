"""Finalize report capture and small evidence presentation details."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'frontend/src/PhaseTwoMap.tsx'
content = path.read_text(encoding='utf-8')
old = 'return <GeoJSON key={itinerary.itinerary_id} data={itinerary.geometry as unknown as GeoJsonObject} interactive={false} style={{ color: \'#a42b78\', weight: 5, opacity: .85 }} />;'
new = '''const legs = itinerary.legs.filter(leg => leg.geometry && typeof leg.geometry === 'object');
  if (legs.length) return <>{legs.map((leg, index) => <GeoJSON key={`${itinerary.itinerary_id}-${index}`} data={leg.geometry as GeoJsonObject} interactive={false} style={{color:leg.mode === 'WALK' ? '#42687b' : '#a42b78',weight:leg.mode === 'WALK' ? 4 : 5,dashArray:leg.mode === 'WALK' ? '6 5' : undefined,opacity:.9}} />)}</>;
  return <GeoJSON key={itinerary.itinerary_id} data={itinerary.geometry as unknown as GeoJsonObject} interactive={false} style={{ color: '#a42b78', weight: 5, opacity: .85 }} />;'''
assert old in content
path.write_text(content.replace(old, new), encoding='utf-8')
path = root / 'frontend/src/stateValidation.ts'
content = path.read_text(encoding='utf-8').replace('preference: state.preference, state_revision:', 'preference: state.preference, soft_preferences: structuredClone(state.soft_preferences), state_revision:')
path.write_text(content, encoding='utf-8')
path = root / 'frontend/src/PhaseTwoApp.tsx'
content = path.read_text(encoding='utf-8')
content = content.replace("  useEffect(() => () => { controller.current?.abort(); }, []);", """  useEffect(() => { setTravelDate(state.travel.date ?? ''); setTravelTime(state.travel.time?.slice(0,5) ?? ''); setTimeMode(state.travel.time_mode); }, [state.travel.date,state.travel.time,state.travel.time_mode]);
  useEffect(() => () => { controller.current?.abort(); }, []);""")
content = content.replace("  if (state.query) chips.push", "  for (const soft of state.soft_preferences) chips.push({id:'soft-'+soft,text:'ترجیح: '+preferenceNames[soft],remove:()=>patch('soft_preferences',state.soft_preferences.filter(value=>value!==soft))});\n  if (state.query) chips.push")
content = content.replace('<section className="results" aria-label="نتایج جست‌وجو">', '<section className="results" aria-label="نتایج جست‌وجو" data-filter-duration-ms={preview.duration_ms} data-filter-ready={previewReady}>')
content = content.replace("p.source_records.map(s => s.source).join('، ')", "p.is_synthetic ? 'تولیدکنندهٔ دادهٔ نمایشی' : p.source_records.map(s => s.source).join('، ')")
path.write_text(content, encoding='utf-8')
path = root / 'frontend/e2e/phase2.spec.ts'
content = path.read_text(encoding='utf-8').replace("  await page.screenshot({ path: 'test-results/phase-2-desktop.png'", "  await page.evaluate(() => window.scrollTo(0,0));\n  await page.screenshot({ path: 'test-results/phase-2-desktop.png'").replace("  await page.screenshot({ path: 'test-results/phase-2-mobile.png'", "  await page.evaluate(() => window.scrollTo(0,0));\n  await page.screenshot({ path: 'test-results/phase-2-mobile.png'")
path.write_text(content, encoding='utf-8')
path = root / 'frontend/playwright.config.ts'
content = path.read_text(encoding='utf-8').replace("timeout:45000,", "timeout:45000,reporter:[['list'],['json',{outputFile:'../docs/phase-2-browser-report.json'}]],")
path.write_text(content, encoding='utf-8')
path = root / 'backend/app/search.py'
content = path.read_text(encoding='utf-8').replace('from .event_evidence import qualifying_alternatives', 'from .event_evidence import qualifying_alternatives, request_actor')
content = content.replace("output = {'task_id': req.task_id,", "output = {'actor_kind': request_actor(session, request_id), 'task_id': req.task_id,")
path.write_text(content, encoding='utf-8')
