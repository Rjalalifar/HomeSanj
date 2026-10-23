from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def edit(name, replacements):
    path = ROOT / name
    source = path.read_text(encoding="utf-8-sig")
    for before, after in replacements:
        if before not in source:
            raise RuntimeError(f"Expected source not found in {name}: {before[:100]}")
        source = source.replace(before, after)
    path.write_text(source, encoding="utf-8")


edit("frontend/src/api.ts", [
    ("export type ResultRow =", "export type AccessibilityStop = {stop_id?:string; id?:string; name?:string; name_fa?:string; modes?:string[]; latitude?:number; longitude?:number};\nexport type PropertyAccessibility = {semantics_version:string; mode:'destination'|'nearby_stop'; status:string; nearest_stop:AccessibilityStop|null; walking_stop:AccessibilityStop|null; total_duration_seconds:number|null; walk_duration_seconds:number|null; walk_distance_meters:number|null; straight_line_meters:number|null; calculated_at:string|null; effective_at:string|null; cache_policy_version:string};\nexport type ResultRow ="),
    ("qualifying_itineraries?:Itinerary[]", "qualifying_itineraries?:Itinerary[]; accessibility?:PropertyAccessibility"),
    ("cache_misses?:number};", "cache_misses?:number; accessibility?:{semantics_version:string; mode:'destination'|'nearby_stop'; effective_at:string|null; time_policy:string; stops_status?:string}};"),
])
edit("frontend/src/state.ts", [("if(next.travel.destination&&(!next.travel.date||!next.travel.time))", "if(next.travel.destination&&!next.accessibility?.enabled&&(!next.travel.date||!next.travel.time))")])
edit("frontend/src/stateValidation.ts", [("...structuredClone(defaults), travel:", "...structuredClone(defaults), accessibility: structuredClone(state.accessibility), travel:")])

path = ROOT / "frontend/src/PhaseTwoApp.tsx"
source = path.read_text(encoding="utf-8")
source = source.replace("import { operation, reducer, stateKey } from './state';", "import { operation, reducer } from './state';\nimport { accessibilitySearchKey as stateKey, accessibilitySorts, initializeAccessibility, writeDestination } from './accessibility';")
source = source.replace("useReducer(reducer, { state: initial, defaults: initial, error: null })", "useReducer(reducer, initial, value => ({ state: initializeAccessibility(value), defaults: initializeAccessibility(value), error: null }))")
source = source.replace("const currentKey = useRef(key); currentKey.current = key;", "const currentKey = useRef(key); currentKey.current = key;\n  const currentSort = useRef(state.sort); currentSort.current = state.sort;\n  const sortGeneration = useRef(0);")
source = source.replace("const [destinationLabel, setDestinationLabel] = useState('مقصد من');\n  const [travelDate, setTravelDate] = useState(state.travel.date ?? '');\n  const [travelTime, setTravelTime] = useState(state.travel.time?.slice(0, 5) ?? '');\n  const [timeMode, setTimeMode] = useState<'ARRIVE_BY' | 'DEPART_AT'>(state.travel.time_mode);", "const [destinationLabel, setDestinationLabel] = useState(state.travel.destination?.label ?? 'مقصد من');")
source = source.replace("}, [key, previewLimit]);", "}, [key, state.sort, previewLimit]);")
source = source.replace("const token = generation.current;\n    const abort", "const token = generation.current, sort = state.sort;\n    const abort")
source = source.replace("?offset=${offset}&limit=30`", "?offset=${offset}&limit=30&sort=${sort}`")
source = source.replace("if (token === generation.current && currentKey.current === stateKey(value.state)) setResult(value);", "if (token === generation.current && currentKey.current === stateKey(value.state) && currentSort.current === sort) setResult(value);")
source = source.replace("}, [result, latest, offset]);", "}, [result, latest, offset, state.sort]);")
source = source.replace("  useEffect(() => { setTravelDate(state.travel.date ?? ''); setTravelTime(state.travel.time?.slice(0,5) ?? ''); setTimeMode(state.travel.time_mode); }, [state.travel.date,state.travel.time,state.travel.time_mode]);\n", "")
start = source.index("  function confirmDestination() {")
end = source.index("  async function command(", start)
source = source[:start] + '''  function confirmDestination() {
    const point = draftDestination ?? state.travel.destination;
    if (!point) { setError('ابتدا نقطهٔ مقصد را روی نقشه انتخاب کنید.'); return; }
    const destination: Destination = { latitude: point.latitude, longitude: point.longitude, label: destinationLabel.trim() || 'مقصد من', confirmed: true };
    dispatch({ type: 'patch', operations: [operation('travel.destination', destination), operation('travel.date', null), operation('travel.time', null), operation('travel.time_mode', 'DEPART_AT'), operation('sort', 'recommended')] });
    try { writeDestination(window.localStorage, destination); setNotice('مقصد برای جست‌وجوهای بعدی در همین مرورگر ذخیره شد.'); }
    catch { setNotice('ذخیره‌سازی مرورگر در دسترس نیست؛ مقصد فقط تا پایان این صفحه نگه داشته می‌شود.'); }
    setChoosing(false); setDraftDestination(null); setError('');
  }
  function clearDestination() {
    const fields = ['travel.destination', 'travel.date', 'travel.time', 'travel.modes', 'travel.max_duration_seconds', 'travel.max_walk_seconds', 'travel.max_walk_meters', 'travel.max_transfers', 'travel.include_walk_only', 'sort'];
    dispatch({ type: 'patch', operations: fields.map(field => ({ field, value: null, remove: true })) });
    // Defaults can contain a saved destination, so removal explicitly clears it.
    dispatch({ type: 'patch', operations: [operation('travel.destination', null)] });
    try { writeDestination(window.localStorage, null); } catch { setNotice('پاک‌کردن ذخیرهٔ مرورگر ممکن نشد؛ مقصد این صفحه حذف شد.'); }
    setDraftDestination(null); setChoosing(false); setDestinationLabel('مقصد من');
  }
  async function changeSort(sort: SearchState['sort']) {
    patch('sort', sort);
    if (!result || !latest) return;
    const requestId = result.request_id, expected = key, token = ++sortGeneration.current;
    setBusy(true); setError('');
    try {
      const value = await api<SearchResult>(`/searches/${requestId}?offset=0&limit=30&sort=${sort}`);
      if (token === sortGeneration.current && currentKey.current === expected && resultRef.current?.request_id === requestId && currentSort.current === sort) { setResult(value); setOffset(0); }
    } catch (e) { if (token === sortGeneration.current) setError((e as Error).message); }
    finally { if (token === sortGeneration.current) setBusy(false); }
  }
''' + source[end:]
source = source.replace("const value = await api<SearchResult>(`/searches/${result.request_id}/${action}`, post({})); if (currentKey.current === stateKey(value.state))", "await api<SearchResult>(`/searches/${result.request_id}/${action}`, post({})); const value = await api<SearchResult>(`/searches/${result.request_id}?offset=0&limit=30&sort=${currentSort.current}`); if (currentKey.current === stateKey(value.state))")
source = source.replace("?offset=${next}&limit=30`", "?offset=${next}&limit=30&sort=${state.sort}`")
source = source.replace("بودجه و محله را انتخاب کنید؛ برای بررسی مسیر، مقصد و زمان را هم تأیید کنید.", "بودجه و محله را انتخاب کنید؛ دسترسی خانه‌ها به مقصد همیشگی شما یا ایستگاه‌های حمل‌ونقل عمومی بررسی می‌شود.")
start = source.index('        <section className="destination-editor">')
end = source.index('</section><label>اولویت', start)
source = source[:start] + '''        <section className="destination-editor" aria-label="مقصد همیشگی من"><h2>مقصد همیشگی من</h2>
          <p>{state.travel.destination ? `مقصد ذخیره‌شده: ${state.travel.destination.label}` : 'اختیاری؛ بدون مقصد، دسترسی به ایستگاه‌های مترو و اتوبوس بررسی می‌شود.'}</p>
          <button aria-pressed={choosing} onClick={() => { setChoosing(!choosing); setView('map'); setDrawer(false); }}>{state.travel.destination ? 'تغییر مقصد روی نقشه' : 'انتخاب مقصد روی نقشه'}</button>
          {(choosing || draftDestination) && <p className="notice">{draftDestination ? `نقطهٔ انتخاب‌شده: ${draftDestination.names.join('، ') || 'بیرون از محله‌های این داده'}` : 'روی نقشه بزنید و سپس مقصد را ذخیره کنید.'}</p>}
          {(draftDestination || choosing) && <><label>نام مقصد<input aria-label="نام مقصد" maxLength={120} value={destinationLabel} onChange={e => setDestinationLabel(e.target.value)} /></label><button disabled={!draftDestination} onClick={confirmDestination}>ذخیرهٔ مقصد</button><button onClick={() => { setDraftDestination(null); setChoosing(false); }}>لغو انتخاب مقصد</button></>}
          {state.travel.destination && <button onClick={clearDestination}>حذف مقصد همیشگی</button>}
          <p className="muted">{state.travel.destination ? 'زمان سفر هنگام اجرای جست‌وجو با ساعت تهران محاسبه می‌شود و برآورد همهٔ روزها و ساعت‌ها نیست.' : 'فاصلهٔ مستقیم و مسیر واقعی پیاده‌روی دو معیار جدا هستند.'} مقصد فقط در همین مرورگر ذخیره می‌شود.</p>
        ''' + source[end:]
source = source.replace("!['parking', 'elevator'].includes(value)", "!['parking', 'elevator', 'fewer_transfers'].includes(value)")
start = source.index('<select aria-label="مرتب‌سازی"')
end = source.index('</select>', start) + len('</select>')
source = source[:start] + '<select aria-label="مرتب‌سازی" value={state.sort} onChange={e => void changeSort(e.target.value as SearchState[\'sort\'])}>{accessibilitySorts(!!state.travel.destination).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>' + source[end:]
source = source.replace("{state.travel.destination && result.evaluated_count < result.candidate_count &&", "{result.evaluated_count < result.candidate_count &&")
source = source.replace("مسیر بررسی‌شده از", "آگهی با بررسی دسترسی از")
source = source.replace("<p>ترتیب دسترسی فقط در زیرمجموعهٔ بررسی‌شده معتبر است.</p>", "<p>ترتیب دسترسی فقط در زیرمجموعهٔ بررسی‌شده معتبر است؛ رتبه‌بندی کل هنوز نهایی نیست.</p>")
source = source.replace("{result.semantic?.status === 'pending' &&", "{result.accessibility?.mode === 'destination' && <p>زمان مبنای محاسبه: {dateText(result.accessibility.effective_at ?? result.state.accessibility?.effective_at)} (تهران). این برآورد به همین زمان وابسته است.</p>}{result.semantic?.status === 'pending' &&")
source = source.replace("['partial', 'cancelled'].includes(result.completion_status)", "['partial', 'capped', 'cancelled'].includes(result.completion_status)")
source = source.replace("این گزینه‌ها فقط شروط ملک را گذرانده‌اند؛ مسیرشان برای شرایط فعلی هنوز بررسی نشده است.", "این گزینه‌ها شروط ملک را گذرانده‌اند؛ محاسبهٔ دسترسی پس از اجرای جست‌وجو آغاز می‌شود.")
source = source.replace("{!latest && state.travel.destination &&", "{!latest &&")
source = source.replace("برای تعیین مقصد روی نقشه بزنید؛ سپس زمان را تأیید کنید.", "برای تعیین مقصد روی نقشه بزنید؛ سپس مقصد را ذخیره کنید.")
source = source.replace("destination={state.travel.destination}", "destination={draftDestination ? { latitude: draftDestination.latitude, longitude: draftDestination.longitude, label: destinationLabel || 'مقصد پیشنهادی', confirmed: true } : state.travel.destination}")
source = source.replace("setChoosing(false); setDrawer(true);", "setDrawer(true);")
source = source.replace("این گزینه‌ها نتیجهٔ منطبق با شروط سفر نیستند.", "دسترسی این گزینه‌ها نامعلوم است؛ آگهی‌ها همچنان در نتایج شروط ملک باقی می‌مانند.")
source = source.replace("const ref = useRef<HTMLElement | null>(null), p = row.property, route = row.selected_itinerary;", "const ref = useRef<HTMLElement | null>(null), p = row.property, route = row.selected_itinerary;")
source = source.replace("    {route ? <div className=\"route-summary\">", "    {row.accessibility ? <AccessibilitySummary row={row} /> : route ? <div className=\"route-summary\">")
source = source.replace("<h3>مسیر منتخب</h3>{details.selected_itinerary", "<h3>دسترسی این خانه</h3><AccessibilitySummary row={details} /><h3>مسیر منتخب</h3>{details.selected_itinerary")
source = source.replace("duration: duration(r?.total_duration_seconds ?? null), walk: duration(r?.walk_duration_seconds ?? null)", "duration: duration(row.accessibility?.total_duration_seconds ?? r?.total_duration_seconds ?? null), walk: duration(row.accessibility?.walk_duration_seconds ?? r?.walk_duration_seconds ?? null)")
source = source.replace("source: p.is_synthetic ? 'نمایشی' : p.is_synthetic ? 'تولیدکنندهٔ دادهٔ نمایشی' :", "source: p.is_synthetic ? 'نمایشی' :")
source = source.replace("complete: 'بررسی کامل', partial:", "complete: 'بررسی کامل', capped: 'بررسی بخشی از گزینه‌ها', partial:")
path.write_text(source, encoding="utf-8")

edit("frontend/src/PhaseTwoMap.tsx", [
    ("props.onSelectProperty(p.property_id); } }}>", "if (props.chooseDestination) props.onDestination(p.latitude!, p.longitude!, memberships(p.longitude!, p.latitude!, props.neighborhoods)); else props.onSelectProperty(p.property_id); } }}>"),
    ("{ambiguous.length > 1 &&", "{!props.chooseDestination && ambiguous.length > 1 &&"),
])
