"""Finish the shared parser, visible provenance, and map configuration."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'frontend/src/PhaseTwoApp.tsx'
content = path.read_text(encoding='utf-8')
content = content.replace("post({ state, text, use_ai: useAI })", "post({ state, text, use_ai: mode === 'advanced' && useAI })")
content = content.replace("const expected = key;\n    try {\n      const updated", "const expected = key, expectedText = queryText;\n    try {\n      const updated")
content = content.replace("if (currentKey.current === expected) { dispatch({ type: 'replace', state: updated });", "if (currentKey.current === expected && queryRef.current === expectedText) { dispatch({ type: 'replace', state: updated });")
content = content.replace("{mode === 'normal' ? <div className=\"search-line\">", "{mode === 'normal' && <div className=\"search-line\">")
content = content.replace('</button></div> : <>\n        <label className="search-input">', '</button></div>}\n      <details className="text-parser" open={mode === \'advanced\'}><summary>بیان خواسته با متن</summary>\n        <label className="search-input">')
content = content.replace('      </>}\n    </section>', '      </details>\n    </section>')
content = content.replace('<button className="primary" disabled={busy || !confirmedText || confirmedText !== queryText || proposal?.search_pending} onClick={submitSearch}>اجرای جست‌وجوی پیشرفته</button>', '{mode === \'advanced\' && <button className="primary" disabled={busy || !confirmedText || confirmedText !== queryText || proposal?.search_pending} onClick={submitSearch}>اجرای جست‌وجوی پیشرفته</button>}')
content = content.replace('<details open><summary>محله‌ها', '<details open><summary>محله‌ها')
content = content.replace('<input aria-label="جست‌وجوی نام محله"', '{state.selected_neighborhood_ids.length > 0 && <button onClick={() => patch(\'selected_neighborhood_ids\', [])}>پاک‌کردن فقط محله‌ها</button>}<input aria-label="جست‌وجوی نام محله"')
content = content.replace("    if (next.some(r => r.property.property_id === id)) sendEvent(result.request_id, 'comparison_opened', id);", '')
content = content.replace("<button onClick={() => setCompareOpen(true)}>نمایش مقایسه</button>", "<button onClick={() => { setCompareOpen(true); sendEvent(comparison.request, 'comparison_opened', comparison.rows[0].property.property_id); }}>نمایش مقایسه</button>")
content = content.replace("if (latest) sendEvent(result.request_id, 'result_clicked', row.property.property_id);", "if (latest) { sendEvent(result.request_id, 'result_clicked', row.property.property_id); if (row.selected_itinerary) sendEvent(result.request_id, 'route_opened', row.property.property_id); }")
content = content.replace("onSelectProperty={selectProperty}", "onSelectProperty={id => { selectProperty(id); if (latest) sendEvent(result.request_id, 'map_property_selected', id); }}")
content = content.replace('<p className="property-specs">', '<p className="property-specs">')
content = content.replace('<dl className="prices">', '<p className="card-provenance">{p.source_records.map(s => s.source).join(\'، \')} · {dateText(p.published_at)} · موقعیت {p.location_accuracy === \'exact\' ? \'دقیقِ ثبت‌شده\' : p.location_accuracy === \'approximate\' ? \'تقریبی\' : p.is_synthetic ? \'نمونه‌گیری نمایشی\' : \'نامعلوم\'}</p><dl className="prices">')
content = content.replace('<span>{digits(route.transfers)} تعویض</span>', '<span>{digits(route.walk_distance_meters)} متر پیاده‌روی</span><span>{digits(route.transfers)} تعویض</span><small>{[...new Set(route.legs.map(leg => leg.mode === \'WALK\' ? \'پیاده\' : leg.mode === \'BUS\' ? \'اتوبوس\' : String(leg.mode ?? \'نامعلوم\')))].join(\' + \')} · {route.legs.length > 0 && route.legs.every(leg => leg.mode === \'WALK\') ? \'سفر تماماً پیاده · \' : \'\'}{route.source_kind === \'synthetic_fixture\' ? \'مسیر ساختگی دمو\' : route.source_kind === \'recorded_otp\' ? \'پاسخ ذخیره‌شده\' : \'دریافت جاری OTP\'}؛ شروع {dateText(route.start_datetime)}؛ پایان {dateText(route.end_datetime)}</small>')
content = content.replace('<h3>دلیل پیشنهاد</h3>', '<h3>دلیل پیشنهاد: کدام خانه برای من مناسب‌تر است و چرا؟</h3>')
content = content.replace('<p key={i}>{claim.text}</p>', '<p key={i}>{claim.text} <button className="evidence-link" title={claim.evidence_refs.join(\', \')} onClick={() => selectProperty(rec.property_id)}>مشاهدهٔ آگهیِ شاهد</button></p>')
content = content.replace("<small>{latest ? 'نتیجهٔ ثبت‌شده' : 'پیش‌نمایش فیلترهای فعلی'}", "<small>{digits(rows.length)} مورد نمایش‌داده‌شده از {digits(count)} · {latest ? 'نتیجهٔ ثبت‌شده' : 'پیش‌نمایش فیلترهای فعلی'}")
content = content.replace('<p>بازیابی معنایی انجام شد؛ شروط قطعی همچنان روی همهٔ کاندیداها اعمال می‌شوند.</p>', '<p>{digits(result.semantic?.retrieved_count ?? 0)} کاندیدای معنایی بازیابی شد؛ شروط قطعی روی هر {digits(result.candidate_count)} کاندیدای ساخت‌یافته اعمال می‌شوند. امتیاز معنایی فقط اولویت بررسی و تساوی امتیاز مطلوبیت را تعیین می‌کند.</p>')
content = content.replace("routing_unavailable:", "routing_unavailable:")
content = content.replace("const statusNames: Record<string, string> = {", "const statusNames: Record<string, string> = { routing_unavailable: 'مسیریابی آماده نیست',")
content = content.replace('<li key={index}><strong>{leg.mode', '<li className={leg.mode === \'WALK\' ? \'walk-leg\' : \'transit-leg\'} key={index}><strong>{leg.mode')
content = content.replace('{lineName(leg)}<span>', '{lineName(leg)}<span>{placeName(leg.from)} ← {placeName(leg.to)}</span><span>')
content = content.replace('function lineName(', "function placeName(value: unknown): string { return value && typeof value === 'object' ? String((value as Record<string, unknown>).name ?? 'نامعلوم') : 'نامعلوم'; }\n\nfunction lineName(")
path.write_text(content, encoding='utf-8')
path = root / 'frontend/src/PhaseTwoMap.tsx'
content = path.read_text(encoding='utf-8')
content = content.replace("const [tileFailed, setTileFailed] = useState(false);", "const [tileFailed, setTileFailed] = useState(false);\n  const [showDistricts, setShowDistricts] = useState(false);\n  const environment = (import.meta as ImportMeta & {env: Record<string, string>}).env;")
content = content.replace('<TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution=', '<TileLayer url={environment.VITE_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"} attribution=')
content = content.replace('<Boundaries features={props.districts} selected={props.selectedDistricts} district />', '{(showDistricts || props.selectedDistricts.length > 0) && <Boundaries features={props.districts} selected={props.selectedDistricts} district />}')
content = content.replace('<div className="map-legend">', '<label className="district-overlay"><input type="checkbox" checked={showDistricts} onChange={e => setShowDistricts(e.target.checked)} /> نمایش مرز مناطق</label><div className="map-legend">')
path.write_text(content, encoding='utf-8')
path = root / 'frontend/src/phase2.css'
with path.open('a', encoding='utf-8') as stream:
    stream.write('\n.text-parser{text-align:right;margin-top:14px}.text-parser>summary{cursor:pointer;color:#a72c2c;font-size:12px;margin-bottom:10px}.card-provenance{font-size:10px;color:#667085;margin:8px 0}.evidence-link{font-size:10px;padding:2px 6px}.district-overlay{font-size:11px;display:flex;gap:7px;align-items:center;padding:8px 14px}.route-legs .walk-leg{border-right:2px dashed #718197}.route-legs .transit-leg{border-right:3px solid #a42b78}\n')
