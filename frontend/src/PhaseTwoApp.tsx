import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { Destination, Itinerary, SearchState } from './contracts.generated';
import { api, digits, duration, featureId, loadInventory, money, normalize, parseNumeric, post } from './api';
import type { Boundary, Explanation, Health, IntentProposal, Inventory, Measurement, ResultRow, SearchResult } from './api';
import { operation, reducer } from './state';
import { accessibilitySearchKey as stateKey, accessibilitySorts, initializeAccessibility, writeDestination } from './accessibility';
import PhaseTwoMap from './PhaseTwoMap';
import AccessibilitySummary from './AccessibilitySummary';
import './phase2.css';

type Bootstrap = { health: Health; initial: SearchState; neighborhoods: Boundary[]; districts: Boundary[]; inventory: Inventory };
type Comparison = { snapshot: string; request: string; key: string; rows: ResultRow[] };
const labels: Record<string, string> = {
  'property.max_deposit_toman': 'سقف ودیعه', 'property.max_monthly_rent_toman': 'سقف اجاره',
  'property.min_area_m2': 'حداقل متراژ', 'property.min_bedrooms': 'حداقل اتاق',
  'property.parking_required': 'پارکینگ الزامی', 'property.elevator_required': 'آسانسور الزامی',
  selected_neighborhood_ids: 'محله', selected_district_ids: 'منطقه', query: 'واژهٔ جست‌وجو',
  'travel.max_duration_seconds': 'سقف زمان سفر', 'travel.max_walk_seconds': 'سقف پیاده‌روی',
  'travel.max_walk_meters': 'سقف مسافت پیاده‌روی', 'travel.max_transfers': 'سقف تعویض',
  'travel.date': 'تاریخ', 'travel.time': 'ساعت', 'travel.time_mode': 'زمان‌بندی', soft_preferences: 'ترجیح‌ها', preference: 'اولویت',
};
const preferenceNames: Record<string, string> = { balanced: 'متعادل', lower_rent: 'اجاره کمتر', faster_commute: 'سفر سریع‌تر', less_walking: 'پیاده‌روی کمتر', fewer_transfers: 'تعویض کمتر', parking: 'پارکینگ', elevator: 'آسانسور' };
const routeNames: Record<string, string> = { ok: 'مسیر منطبق', not_evaluated: 'مسیر بررسی نشده', timeout: 'مهلت مسیریابی تمام شد', api_error: 'خطای سرویس مسیر', invalid_response: 'پاسخ مسیر نامعتبر', no_route_returned: 'مسیری برنگشت', no_feasible_returned_itinerary: 'در مسیرهای بازگشتی گزینهٔ منطبق پیدا نشد', out_of_coverage: 'خارج از پوشش تأییدشده', not_configured: 'مسیریابی تنظیم نشده' };
const statusNames: Record<string, string> = { routing_unavailable: 'مسیریابی آماده نیست', complete: 'بررسی کامل', capped: 'بررسی بخشی از گزینه‌ها', partial: 'بررسی بخشی از گزینه‌ها', queued: 'در صف بررسی', running: 'در حال بررسی', cancelled: 'متوقف شده', not_configured: 'مسیریابی آماده نیست' };
const yesNo = (value: boolean | null) => value === null ? 'نامعلوم' : value ? 'دارد' : 'ندارد';
const pending = (result: SearchResult) => ['queued', 'running'].includes(result.completion_status) || result.semantic?.status === 'pending';
const uuid = () => crypto.randomUUID();
const dateText = (value: string | null | undefined) => value ? new Date(value).toLocaleString('fa-IR', { timeZone: 'Asia/Tehran' }) : 'نامعلوم';

export default function PhaseTwoApp() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    Promise.all([api<Health>('/health'), api<SearchState>('/state/default'), api<{ features: Boundary[] }>('/neighborhoods'), api<{ features: Boundary[] }>('/districts'), loadInventory()])
      .then(([health, initial, n, d, inventory]) => { if (active) setData({ health, initial, neighborhoods: n.features, districts: d.features, inventory }); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [retry]);
  if (!data) return <main dir="rtl" className="boot"><h1>خانه‌سنج</h1>{error ? <><p role="alert">{error}</p><button onClick={() => { setError(''); setRetry(n => n + 1); }}>تلاش دوباره</button></> : <p role="status">در حال آماده‌کردن محله‌ها و آگهی‌ها…</p>}</main>;
  return <Workbench {...data} />;
}

function Workbench({ health, initial, neighborhoods, districts, inventory }: Bootstrap) {
  const [store, dispatch] = useReducer(reducer, initial, value => ({ state: initializeAccessibility(value), defaults: initializeAccessibility(value), error: null }));
  const state = store.state;
  const key = stateKey(state);
  const currentKey = useRef(key); currentKey.current = key;
  const currentSort = useRef(state.sort); currentSort.current = state.sort;
  const sortGeneration = useRef(0);
  const [mode, setMode] = useState<'normal' | 'advanced'>('normal');
  const [view, setView] = useState<'list' | 'map'>('list');
  const [drawer, setDrawer] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [queryText, setQueryText] = useState('');
  const queryRef = useRef(queryText); queryRef.current = queryText;
  const [proposal, setProposal] = useState<IntentProposal | null>(null);
  const [proposalKey, setProposalKey] = useState('');
  const [confirmedText, setConfirmedText] = useState('');
  const [useAI, setUseAI] = useState(false);
  const [neighborhoodQuery, setNeighborhoodQuery] = useState('');
  const [result, setResult] = useState<SearchResult | null>(null);
  const resultRef = useRef<SearchResult | null>(null); resultRef.current = result;
  const [offset, setOffset] = useState(0);
  const [preview, setPreview] = useState<{ count: number; rows: ResultRow[]; duration_ms: number }>({ count: 0, rows: [], duration_ms: 0 });
  const [previewLimit, setPreviewLimit] = useState(30);
  const [previewReady, setPreviewReady] = useState(false);
  const worker = useRef<Worker | null>(null);
  const revision = useRef(0);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [draftDestination, setDraftDestination] = useState<{ latitude: number; longitude: number; names: string[] } | null>(null);
  const [destinationLabel, setDestinationLabel] = useState(state.travel.destination?.label ?? 'مقصد من');
  const [selected, setSelected] = useState<string | null>(null);
  const [route, setRoute] = useState<Itinerary | null>(null);
  const [details, setDetails] = useState<ResultRow | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [topChoice, setTopChoice] = useState('');
  const [feedbackNote, setFeedbackNote] = useState('');
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [explainBusy, setExplainBusy] = useState(false);
  const latest = result !== null && stateKey(result.state) === key;
  const rows = latest ? result.results : preview.rows;
  const count = latest ? result.result_count : preview.count;
  const comparisonStale = comparison && (comparison.key !== key || comparison.snapshot !== result?.snapshot_id);
  const mapNeighborhoods = useMemo(() => new Map(neighborhoods.map(n => [featureId(n), n.properties.name_fa])), [neighborhoods]);
  const mapDistricts = useMemo(() => new Map(districts.map(n => [featureId(n), n.properties.name_fa])), [districts]);
  const namesFor = (ids: string[]) => ids.map(id => mapNeighborhoods.get(id) ?? mapDistricts.get(id) ?? id).join('، ');
  const patch = (field: string, value: unknown, source = 'form') => {
    dispatch({ type: 'patch', operations: [operation(field, value)] });
    const event = ({selected_neighborhood_ids:'neighborhood_filter_changed',selected_district_ids:'district_filter_changed',sort:'sort_changed'} as Record<string,string>)[field];
    if (result && event) sendEvent(result.request_id, event, null, {source});
  };
  const toggle = (field: 'selected_neighborhood_ids' | 'selected_district_ids', id: string, source = 'dropdown') => patch(field, state[field].includes(id) ? state[field].filter(x => x !== id) : [...state[field], id], source);
  const remove = (field: string) => dispatch({ type: 'patch', operations: [{ field, value: null, remove: true }] });

  useEffect(() => {
    const instance = new Worker(new URL('./filter.worker.ts', import.meta.url), { type: 'module' });
    worker.current = instance;
    instance.onmessage = event => { if (event.data.revision === revision.current) { setPreview(event.data); setPreviewReady(true); } };
    instance.onerror = () => setError('فیلتر محلی آماده نشد؛ جست‌وجوی ثبت‌شده همچنان از سرور قابل اجراست.');
    instance.postMessage({ inventory });
    return () => { instance.terminate(); worker.current = null; };
  }, [inventory]);
  useEffect(() => {
    revision.current += 1; setPreviewReady(false); setSelected(null); setRoute(null); setExplanation(null);
    const token = revision.current;
    const timer = window.setTimeout(() => worker.current?.postMessage({ state, revision: token, limit: previewLimit }), 100);
    return () => window.clearTimeout(timer);
  }, [key, state.sort, previewLimit]);
  useEffect(() => {
    if (!result || !latest || !pending(result)) return;
    const token = generation.current, sort = state.sort;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      api<SearchResult>(`/searches/${result.request_id}?offset=${offset}&limit=30&sort=${sort}`, { signal: abort.signal })
        .then(value => { if (token === generation.current && currentKey.current === stateKey(value.state) && currentSort.current === sort) setResult(value); })
        .catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    }, 900);
    return () => { window.clearTimeout(timer); abort.abort(); };
  }, [result, latest, offset, state.sort]);
  useEffect(() => {
    setMeasurement(null); setTopChoice('');
    if (!latest || !result || pending(result)) return;
    let active = true;
    api<Measurement>(`/measurements/${result.request_id}`).then(value => { if (active) setMeasurement(value); }).catch(() => {});
    return () => { active = false; };
  }, [result?.request_id, result?.completion_status, result?.semantic?.status, latest]);
  useEffect(() => () => { controller.current?.abort(); }, []);

  async function submitSearch() {
    setError(''); setNotice('');
    if (mode === 'advanced' && (!confirmedText || confirmedText !== queryText || proposal?.search_pending)) { setError('ابتدا متن را بررسی و شرط‌های پیشنهادی را تأیید کنید.'); return; }
    const sentState = structuredClone(state), sentKey = key;
    const token = ++generation.current;
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort;
    setBusy(true); setOffset(0); setExplanation(null);
    try {
      const previous = resultRef.current;
      if (previous && pending(previous)) await api(`/searches/${previous.request_id}/cancel`, post({}));
      const sameNeed = previous && JSON.stringify(previous.state.travel.destination) === JSON.stringify(sentState.travel.destination);
      const body = { state: sentState, task_id: sameNeed ? previous.task_id : null, parent_request_id: sameNeed ? previous.request_id : null, ...(mode === 'advanced' ? { semantic_text: confirmedText, confirmed: true } : {}) };
      const value = await api<SearchResult>(mode === 'advanced' ? '/advanced/searches' : '/searches', { ...post(body), signal: abort.signal });
      if (token === generation.current && currentKey.current === sentKey) { setResult({ ...value, results: value.results.slice(0, 30) }); setSelected(null); setDrawer(false); }
    } catch (e) { if ((e as Error).name !== 'AbortError') setError((e as Error).message); }
    finally { if (token === generation.current) setBusy(false); }
  }
  async function analyze() {
    if (!queryText.trim()) return;
    setBusy(true); setError(''); setProposal(null); setConfirmedText('');
    const expected = key, text = queryText;
    try {
      const value = await api<IntentProposal>('/intent', post({ state, text, use_ai: mode === 'advanced' && useAI }));
      if (currentKey.current === expected && queryRef.current === text) { setProposal(value); setProposalKey(expected); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function acceptProposal() {
    if (!proposal || proposal.search_pending || key !== proposalKey) return;
    setBusy(true); setError('');
    const expected = key, expectedText = queryText;
    try {
      const updated = await api<SearchState>('/state/patch', post({ state, operations: proposal.operations }));
      if (currentKey.current === expected && queryRef.current === expectedText) { dispatch({ type: 'replace', state: updated }); setConfirmedText(queryText); setProposalKey(stateKey(updated)); setNotice('شرط‌ها تأیید شد؛ جست‌وجو را اجرا کنید.'); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function confirmDestination() {
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
  async function command(action: 'cancel' | 'continue') {
    if (!result) return;
    setBusy(true); setError('');
    try { await api<SearchResult>(`/searches/${result.request_id}/${action}`, post({})); const value = await api<SearchResult>(`/searches/${result.request_id}?offset=0&limit=30&sort=${currentSort.current}`); if (currentKey.current === stateKey(value.state)) setResult({ ...value, results: value.results.slice(0, 30) }); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function page(next: number) {
    if (!result || !latest) return;
    setBusy(true);
    try { const value = await api<SearchResult>(`/searches/${result.request_id}?offset=${next}&limit=30&sort=${state.sort}`); if (currentKey.current === stateKey(value.state) && resultRef.current?.request_id === value.request_id) { setOffset(next); setResult(value); } }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function selectProperty(id: string) {
    setSelected(id); setRoute(rows.find(row => row.property.property_id === id)?.selected_itinerary ?? null);
    document.getElementById(`card-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function addComparison(row: ResultRow) {
    if (!result || !latest) { setNotice('برای مقایسهٔ ثبت‌شده، ابتدا جست‌وجو را اجرا کنید.'); return; }
    if (comparison && (comparison.snapshot !== result.snapshot_id || comparison.key !== key)) { setCompareOpen(true); setNotice('مقایسهٔ قبلی به شرایط دیگری تعلق دارد؛ آن را پاک کنید و مقایسهٔ تازه بسازید.'); return; }
    const old = comparison?.rows ?? [], id = row.property.property_id;
    if (!old.some(r => r.property.property_id === id) && old.length >= 3) { setNotice('حداکثر سه آگهی را می‌توانید مقایسه کنید.'); return; }
    const next = old.some(r => r.property.property_id === id) ? old.filter(r => r.property.property_id !== id) : [...old, structuredClone(row)];
    setComparison(next.length ? { snapshot: result.snapshot_id, request: result.request_id, key, rows: next } : null);

  }
  async function feedback(kind: 'property' | 'top5', positive: boolean, id?: string, requestId?: string, reasonCode?: string) {
    const target = requestId ?? result?.request_id;
    if (!target) return;
    setFeedbackNote('');
    try { await api('/feedback', post({ idempotency_key: uuid(), request_id: target, kind, label: positive ? 'positive' : 'negative', candidate_ids: id ? [id] : [], reason_code: reasonCode || null })); setFeedbackNote('نظر شما ثبت شد. داده‌های این دمو، نظر مستقل دربارهٔ بازار محسوب نمی‌شوند.'); }
    catch (e) { setError((e as Error).message); }
  }
  async function explain() {
    if (!result || !latest) return;
    const requestId = result.request_id;
    setExplainBusy(true); setError('');
    try { const value = await api<Explanation>(`/searches/${requestId}/explanation`, post({ use_ai: useAI })); if (resultRef.current?.request_id === requestId && currentKey.current === key) setExplanation(value); }
    catch (e) { setError((e as Error).message); } finally { setExplainBusy(false); }
  }
  const propertyFields: Array<[keyof SearchState['property'], string]> = [['max_deposit_toman', 'سقف ودیعه (تومان)'], ['max_monthly_rent_toman', 'سقف اجارهٔ ماهانه (تومان)'], ['min_area_m2', 'حداقل متراژ'], ['min_bedrooms', 'حداقل اتاق']];
  const chips: Array<{ id: string; text: string; remove: () => void }> = [];
  for (const [field, value] of Object.entries(state.property)) if (value !== null && value !== false) chips.push({ id: field, text: `${labels['property.' + field]}${value === true ? '' : ': ' + digits(value as number)}`, remove: () => remove('property.' + field) });
  for (const id of state.selected_neighborhood_ids) chips.push({ id, text: namesFor([id]), remove: () => toggle('selected_neighborhood_ids', id) });
  for (const id of state.selected_district_ids) chips.push({ id, text: `منطقه: ${namesFor([id])}`, remove: () => toggle('selected_district_ids', id) });
  for (const soft of state.soft_preferences) chips.push({id:'soft-'+soft,text:'ترجیح: '+preferenceNames[soft],remove:()=>patch('soft_preferences',state.soft_preferences.filter(value=>value!==soft))});
  if (state.query) chips.push({ id: 'query', text: state.query, remove: () => remove('query') });
  for (const field of ['max_duration_seconds', 'max_walk_seconds', 'max_walk_meters', 'max_transfers'] as const) if (state.travel[field] !== null) chips.push({ id: field, text: `${labels['travel.' + field]}: ${digits(state.travel[field])} ${field.endsWith('seconds') ? 'ثانیه' : field.endsWith('meters') ? 'متر' : ''}`, remove: () => remove('travel.' + field) });
  const filteredNeighborhoods = neighborhoods.filter(n => normalize(n.properties.name_fa).includes(normalize(neighborhoodQuery))).sort((a, b) => a.properties.name_fa.localeCompare(b.properties.name_fa, 'fa'));

  return <div dir="rtl" className="phase-two-app">
    <header className="site-header"><a className="brand" href="#">خانه‌سنج<span>خانه را با مسیر زندگی‌تان بسنجید</span></a><span className="demo-label">نسخهٔ نمایشی تهران</span><span className="header-count">{digits(inventory.count)} آگهی نمایشی</span></header>
    <section className="search-hero" aria-label="جست‌وجوی خانه">
      <div className="mode-tabs" role="group" aria-label="روش جست‌وجو"><button aria-pressed={mode === 'normal'} onClick={() => { setMode('normal'); if(result) sendEvent(result.request_id, 'search_mode_changed', null); }}>جست‌وجوی معمولی</button><button aria-pressed={mode === 'advanced'} onClick={() => { setMode('advanced'); if(result) sendEvent(result.request_id, 'search_mode_changed', null); }}>جست‌وجوی پیشرفته</button></div>
      <h1>خانهٔ مناسب، با حساب رفت‌وآمد</h1>
      <p>بودجه و محله را انتخاب کنید؛ دسترسی خانه‌ها به مقصد همیشگی شما یا ایستگاه‌های حمل‌ونقل عمومی بررسی می‌شود.</p>
      {mode === 'normal' && <div className="search-line"><label className="search-input">عنوان یا نام محله<input aria-label="عنوان یا نام محله" value={state.query} onChange={e => patch('query', e.target.value)} placeholder="مثلاً آپارتمان یا نام محله" /></label><button className="primary" disabled={busy} onClick={submitSearch}>جست‌وجوی خانه</button></div>}
      <details className="text-parser" open={mode === 'advanced'}><summary>بیان خواسته با متن</summary>
        <label className="search-input">خانه‌ای که می‌خواهید را توضیح دهید<textarea value={queryText} maxLength={2000} onChange={e => { setQueryText(e.target.value); setConfirmedText(''); setProposal(null); }} placeholder="مثلاً اجاره تا ۱۵ میلیون تومان، دو اتاق و ترجیحاً آسانسور" /></label>
        <div className="examples">{neighborhoods.slice(0, 3).map((n, i) => { const example = [`در ${n.properties.name_fa} اجاره تا ۱۵ میلیون تومان`, `دو اتاق در ${n.properties.name_fa}`, `در ${n.properties.name_fa} ترجیحاً پارکینگ`][i]; return <button key={featureId(n)} onClick={() => { setQueryText(example); setConfirmedText(''); setProposal(null); }}>{example}</button>; })}</div>
        <div className="action-row"><button disabled={busy || !queryText.trim()} onClick={analyze}>بررسی متن و پیشنهاد شرط‌ها</button>{mode === 'advanced' && <button className="primary" disabled={busy || !confirmedText || confirmedText !== queryText || proposal?.search_pending} onClick={submitSearch}>اجرای جست‌وجوی پیشرفته</button>}<span className="muted">{health.llm.enabled ? 'تحلیل متن با تأیید شما' : 'حالت نمونه بدون LLM'}</span>{health.advanced?.ai_enabled && <label><input type="checkbox" checked={useAI} onChange={e => setUseAI(e.target.checked)} /> استفاده از تحلیل مدل</label>}</div>
        {proposal && <div className="intent-preview" aria-label="شرط‌های پیشنهادی"><h2>پیش‌نمایش تغییر شرایط</h2><p>شرط‌های الزامی پس از تأیید شما اعمال می‌شوند.</p><ul>{proposal.operations.map((op, i) => <li key={i}>{labels[op.field] ?? op.field}: {Array.isArray(op.value) ? (op.field.includes('_ids') ? namesFor(op.value as string[]) : (op.value as string[]).map(x => preferenceNames[x] ?? x).join('، ')) : typeof op.value === 'boolean' ? (op.value ? 'الزامی' : 'اختیاری') : typeof op.value === 'number' ? digits(op.value) : String(op.value ?? 'تعیین نشده')}</li>)}</ul>{!proposal.operations.length && <p>شرط ساخت‌یافتهٔ تازه‌ای تشخیص داده نشد؛ متن برای جست‌وجوی معنایی استفاده می‌شود.</p>}<p>ترجیح‌های نرم: {proposal.soft_preferences.map(p => preferenceNames[p] ?? p).join('، ') || 'ندارد'}</p>{proposal.clarifications.map((c, i) => <p className="warning" key={i}>{c.message}</p>)}{proposal.notices.map((n, i) => <p key={i}>{n}</p>)}{proposal.search_pending && <p>متن یا فرم را اصلاح کنید و دوباره «بررسی متن» را بزنید.</p>}{key !== proposalKey && <p>شرایط عوض شده؛ متن را دوباره بررسی کنید.</p>}<button disabled={busy || proposal.search_pending || key !== proposalKey} onClick={acceptProposal}>تأیید شرط‌های پیشنهادی</button></div>}
      </details>
    </section>
    <div className="mobile-toolbar"><button onClick={() => setDrawer(true)}>فیلترها ({digits(chips.length)})</button><button aria-pressed={view === 'list'} onClick={() => setView('list')}>فهرست</button><button aria-pressed={view === 'map'} onClick={() => setView('map')}>نقشه</button></div>
    {(error || store.error) && <div className="error banner" role="alert">{error || store.error}<button onClick={() => setError('')}>بستن پیام</button></div>}
    {notice && <div className="notice banner" role="status">{notice}<button onClick={() => setNotice('')}>بستن</button></div>}
    {feedbackNote && <div className="notice banner" role="status">{feedbackNote}</div>}
    <div className="active-filters" aria-label="شرایط فعال">{chips.map(chip => <button className="chip" key={chip.id} onClick={chip.remove}>{chip.text} ×</button>)}{chips.length > 0 && <button onClick={() => dispatch({ type: 'clear' })}>پاک‌کردن فیلترها</button>}</div>
    <main className={`workspace view-${view}`}>
      <aside className={`filters ${drawer ? 'drawer-open' : ''}`} aria-label="فیلترهای جست‌وجو"><div className="filter-heading"><h2>شرایط خانه</h2><button className="mobile-only" onClick={() => setDrawer(false)}>بستن فیلترها</button></div>
        {propertyFields.map(([field, label]) => <NumericInput key={field} label={label} value={state.property[field] as number | null} onValue={value => patch(`property.${field}`, value)} />)}
        <label className="check"><input type="checkbox" checked={state.property.parking_required === true} onChange={e => patch('property.parking_required', e.target.checked)} /> پارکینگ الزامی</label><label className="check"><input type="checkbox" checked={state.property.elevator_required === true} onChange={e => patch('property.elevator_required', e.target.checked)} /> آسانسور الزامی</label>
        <section className="destination-editor" aria-label="مقصد همیشگی من"><h2>مقصد همیشگی من</h2>
          <p>{state.travel.destination ? `مقصد ذخیره‌شده: ${state.travel.destination.label}` : 'اختیاری؛ بدون مقصد، دسترسی به ایستگاه‌های مترو و اتوبوس بررسی می‌شود.'}</p>
          <button aria-pressed={choosing} onClick={() => { setChoosing(!choosing); setView('map'); setDrawer(false); }}>{state.travel.destination ? 'تغییر مقصد روی نقشه' : 'انتخاب مقصد روی نقشه'}</button>
          {(choosing || draftDestination) && <p className="notice">{draftDestination ? `نقطهٔ انتخاب‌شده: ${draftDestination.names.join('، ') || 'بیرون از محله‌های این داده'}` : 'روی نقشه بزنید و سپس مقصد را ذخیره کنید.'}</p>}
          {(draftDestination || choosing) && <><label>نام مقصد<input aria-label="نام مقصد" maxLength={120} value={destinationLabel} onChange={e => setDestinationLabel(e.target.value)} /></label><button disabled={!draftDestination} onClick={confirmDestination}>ذخیرهٔ مقصد</button><button onClick={() => { setDraftDestination(null); setChoosing(false); }}>لغو انتخاب مقصد</button></>}
          {state.travel.destination && <button onClick={clearDestination}>حذف مقصد همیشگی</button>}
          <p className="muted">زمان سفر هنگام اجرای جست‌وجو و بر اساس برنامه زمانی حمل‌ونقل عمومی تهران محاسبه می‌شود.</p>
        </section>
        <details open><summary>محله‌ها <small>انتخاب‌ها با «یا»</small></summary>{state.selected_neighborhood_ids.length > 0 && <button onClick={() => patch('selected_neighborhood_ids', [])}>پاک‌کردن فقط محله‌ها</button>}<input aria-label="جست‌وجوی نام محله" placeholder="جست‌وجوی محله" value={neighborhoodQuery} onChange={e => setNeighborhoodQuery(e.target.value)} /><div className="boundary-options">{filteredNeighborhoods.map(n => <label className="check" key={featureId(n)}><input type="checkbox" checked={state.selected_neighborhood_ids.includes(featureId(n))} onChange={() => toggle('selected_neighborhood_ids', featureId(n))} />{n.properties.name_fa}<small>منطقهٔ منبع {digits(n.properties.district_no)}</small></label>)}</div></details>
        <details><summary>مناطق <small>با محله‌ها «و» می‌شود</small></summary><div className="boundary-options">{districts.map(d => <label className="check" key={featureId(d)}><input type="checkbox" checked={state.selected_district_ids.includes(featureId(d))} onChange={() => toggle('selected_district_ids', featureId(d))} />{d.properties.name_fa}</label>)}</div><p className="muted">فیلتر منطقه بر اساس نقطهٔ ملک در مرز منطقه است؛ شمارهٔ منطقهٔ منبع محله تأیید نشده است.</p></details>
        <label>اولویت<select value={state.preference} onChange={e => patch('preference', e.target.value)}>{Object.entries(preferenceNames).filter(([value]) => !['parking', 'elevator', 'fewer_transfers'].includes(value)).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label><button className="primary full" disabled={busy} onClick={submitSearch}>{mode === 'normal' ? 'اعمال و ثبت جست‌وجو' : 'ثبت جست‌وجوی پیشرفته'}</button>
      </aside>
      <section className="results" aria-label="نتایج جست‌وجو" data-filter-duration-ms={preview.duration_ms} data-filter-ready={previewReady}><div className="results-toolbar"><div><h2>{digits(count)} گزینه</h2><small>{digits(rows.length)} مورد نمایش‌داده‌شده از {digits(count)} · {latest ? 'نتیجهٔ ثبت‌شده' : 'پیش‌نمایش فیلترهای فعلی'} {!previewReady && !latest ? '· در حال محاسبه…' : ''}</small></div><label>مرتب‌سازی<select aria-label="مرتب‌سازی" value={state.sort} onChange={e => void changeSort(e.target.value as SearchState['sort'])}>{accessibilitySorts(!!state.travel.destination).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div>
        {result && !latest && <p className="warning" role="status">شرایط تغییر کرده است. مسیرها و مقایسهٔ قبلی مربوط به جست‌وجوی پیشین‌اند؛ برای تأیید نتایج جدید، جست‌وجو را اجرا کنید.</p>}
        {!latest && <p className="warning">این گزینه‌ها شروط ملک را گذرانده‌اند؛ محاسبهٔ دسترسی پس از اجرای جست‌وجو آغاز می‌شود.</p>}
        {latest && <div className="search-progress" role="status"><strong>{statusNames[result.completion_status] ?? result.completion_status}</strong><p>{digits(result.evaluated_count)} آگهی با بررسی دسترسی از {digits(result.candidate_count)} کاندیدای ملک · {digits(result.cache_hits ?? 0)} استفاده از مسیر ذخیره‌شده</p>{result.evaluated_count < result.candidate_count && <p>ترتیب دسترسی فقط در زیرمجموعهٔ بررسی‌شده معتبر است؛ رتبه‌بندی کل هنوز نهایی نیست.</p>}{result.accessibility?.mode === 'destination' && <p>زمان مبنای محاسبه: {dateText(result.accessibility.effective_at ?? result.state.accessibility?.effective_at)} (تهران). این برآورد به همین زمان وابسته است.</p>}{result.semantic?.status === 'pending' && <p>جست‌وجوی معنایی در حال تکمیل است…</p>}{result.semantic?.status === 'ok' && <p>{digits(result.semantic?.retrieved_count ?? 0)} کاندیدای معنایی بازیابی شد؛ شروط قطعی روی هر {digits(result.candidate_count)} کاندیدای ساخت‌یافته اعمال می‌شوند. امتیاز معنایی فقط اولویت بررسی و تساوی امتیاز مطلوبیت را تعیین می‌کند.</p>}{result.semantic?.status === 'degraded' && <p className="warning">بازیابی معنایی در دسترس نیست؛ نتیجهٔ فیلترهای ساخت‌یافته حفظ شده است.</p>}{pending(result) && <button disabled={busy} onClick={() => command('cancel')}>توقف بررسی</button>}{['partial', 'capped', 'cancelled'].includes(result.completion_status) && <button disabled={busy} onClick={() => command('continue')}>بررسی دستهٔ بعدی</button>}{result.warnings.map((warning, i) => <p className="warning" key={i}>{warning}</p>)}</div>}
        {mode === 'advanced' && latest && <div className="explanation"><button disabled={explainBusy || pending(result)} onClick={explain}>{explainBusy ? 'در حال آماده‌سازی…' : 'چرا این گزینه‌ها پیشنهاد شدند؟'}</button>{explanation && <><h3>دلیل پیشنهاد: کدام خانه برای من مناسب‌تر است و چرا؟</h3><p>{explanation.summary}</p>{explanation.recommendations.map(rec => <details key={rec.property_id}><summary>{rows.find(r => r.property.property_id === rec.property_id)?.property.title_fa ?? 'گزینهٔ پیشنهادی'}</summary><p>{rec.suitability_reason}</p>{[...rec.strengths, ...rec.tradeoffs, ...rec.unknowns].map((claim, i) => <p key={i}>{claim.text} <button className="evidence-link" title={claim.evidence_refs.join(', ')} onClick={() => selectProperty(rec.property_id)}>مشاهده آگهی</button></p>)}<button onClick={() => selectProperty(rec.property_id)}>نمایش گزینه</button></details>)}{explanation.limitations.map((text, i) => <p className="muted" key={i}>{text}</p>)}</>}</div>}
        {!count && previewReady && <div className="empty"><h3>گزینه‌ای مطابق همهٔ شروط فعلی پیدا نشد</h3><p>انتخاب چند محله با «یا» است، اما انتخاب منطقه و محله هم‌زمان باید هر دو برقرار باشند. شرط‌ها بدون تأیید شما حذف نمی‌شوند.</p></div>}
        <div className="property-list">{rows.map(row => <PropertyCard key={`${latest ? result.request_id : 'preview'}-${row.property.property_id}`} row={row} neighborhood={namesFor(row.property.neighborhood_ids)} active={selected === row.property.property_id} requestId={latest ? result.request_id : null} compared={comparison?.rows.some(r => r.property.property_id === row.property.property_id) ?? false} onSelect={() => selectProperty(row.property.property_id)} onDetails={() => { setDetails(row); setSelected(row.property.property_id); setRoute(row.selected_itinerary); if (latest) { sendEvent(result.request_id, 'result_clicked', row.property.property_id); if (row.selected_itinerary) sendEvent(result.request_id, 'route_opened', row.property.property_id); } }} onCompare={() => addComparison(row)} onFeedback={(positive, reason) => feedback('property', positive, row.property.property_id, undefined, reason)} />)}</div>
        {latest ? <nav className="pagination" aria-label="صفحه‌های نتایج"><button disabled={busy || offset === 0} onClick={() => page(Math.max(0, offset - 30))}>صفحهٔ قبل</button><span>{digits(offset + (rows.length ? 1 : 0))} تا {digits(offset + rows.length)}</span><button disabled={busy || offset + 30 >= count} onClick={() => page(offset + 30)}>صفحهٔ بعد</button></nav> : preview.rows.length < preview.count && <button className="full" onClick={() => setPreviewLimit(n => n + 30)}>نمایش گزینه‌های بیشتر</button>}
        {latest && !!result.unverified_count && <details className="unverified"><summary>{digits(result.unverified_count)} گزینه با مسیر بررسی‌نشده یا ناموفق</summary><p>دسترسی این گزینه‌ها نامعلوم است؛ آگهی‌ها همچنان در نتایج شروط ملک باقی می‌مانند.</p>{result.unverified_results?.slice(0, 15).map(row => <p key={row.property.property_id}>{row.property.title_fa} — {routeNames[row.route_status] ?? 'وضعیت مسیر نامعلوم'}</p>)}</details>}
        {measurement?.freeze_at && <section className="top-feedback"><h3>ارزیابی پنج پیشنهاد ثبت‌شده</h3>{measurement.evaluation_request_id !== result?.request_id && <p>این ارزیابی به نخستین نتیجهٔ ثبت‌شدهٔ همین نیاز تعلق دارد و با تغییر فیلترها عوض نمی‌شود.</p>}<label>کدام گزینه برای شما مناسب بود؟<select aria-label="گزینهٔ مناسب از پنج پیشنهاد" value={topChoice} onChange={e => setTopChoice(e.target.value)}><option value="">انتخاب کنید</option>{measurement.top_k_snapshot.map(row => <option key={row.property_id} value={row.property_id}>{row.property.title_fa ?? row.property_id}</option>)}</select></label><button disabled={!topChoice} onClick={() => feedback('top5', true, topChoice, measurement.evaluation_request_id)}>ثبت گزینهٔ مناسب</button><button onClick={() => feedback('top5', false, undefined, measurement.evaluation_request_id)}>هیچ‌کدام مناسب نبود</button></section>}
      </section>
      <section className="map-panel" aria-label="نقشهٔ نتایج"><div className="map-heading"><h2>همین گزینه‌ها روی نقشه</h2><p>{choosing ? 'برای تعیین مقصد روی نقشه بزنید؛ سپس مقصد را ذخیره کنید.' : 'برای انتخاب محله روی محدودهٔ آن بزنید.'}</p></div><PhaseTwoMap neighborhoods={neighborhoods} districts={districts} results={rows} selected={state.selected_neighborhood_ids} selectedDistricts={state.selected_district_ids} destination={draftDestination ? { latitude: draftDestination.latitude, longitude: draftDestination.longitude, label: destinationLabel || 'مقصد پیشنهادی', confirmed: true } : state.travel.destination} chooseDestination={choosing} onDestination={(latitude, longitude, ids) => { setDraftDestination({ latitude, longitude, names: ids.map(id => mapNeighborhoods.get(id) ?? id) }); setDrawer(true); }} onToggleNeighborhood={id => toggle('selected_neighborhood_ids', id, 'map')} onSelectProperty={id => { selectProperty(id); if (latest) sendEvent(result.request_id, 'map_property_selected', id); }} selectedPropertyId={selected} route={route} /></section>
    </main>
    {comparison && <div className="comparison-bar"><span>{digits(comparison.rows.length)} آگهی برای مقایسه {comparisonStale && '· مربوط به شرایط قبلی'}</span><button onClick={() => { setCompareOpen(true); sendEvent(comparison.request, 'comparison_opened', comparison.rows[0].property.property_id); }}>نمایش مقایسه</button><button onClick={() => { setComparison(null); setCompareOpen(false); }}>پاک‌کردن مقایسه</button></div>}
    {compareOpen && comparison && <Modal title="مقایسهٔ آگهی‌های ثبت‌شده" onClose={() => setCompareOpen(false)}>{comparisonStale && <p className="warning">این مقایسه قدیمی است و از نسخهٔ ذخیره‌شدهٔ نتایج خوانده می‌شود.</p>}<div className="table-scroll"><table><thead><tr><th>ویژگی</th>{comparison.rows.map(row => <th key={row.property.property_id}>{row.property.title_fa}</th>)}</tr></thead><tbody>{(['rent', 'deposit', 'area', 'bedrooms', 'parking', 'elevator', 'duration', 'walk', 'transfers', 'source'] as const).map(field => <tr key={field}><th>{{ rent: 'اجاره ماهانه', deposit: 'ودیعه', area: 'متراژ', bedrooms: 'اتاق', parking: 'پارکینگ', elevator: 'آسانسور', duration: 'زمان مسیر', walk: 'پیاده‌روی', transfers: 'تعویض', source: 'منشأ' }[field]}</th>{comparison.rows.map(row => <td key={row.property.property_id}>{comparisonValue(row, field)}</td>)}</tr>)}</tbody></table></div><p>اعداد هر ستون از یک مسیر منتخب و یک نسخهٔ ذخیره‌شده هستند؛ مقدار نامعلوم صفر محسوب نمی‌شود.</p><button onClick={() => { setComparison(null); setCompareOpen(false); }}>پاک‌کردن و شروع مقایسهٔ تازه</button></Modal>}
    {details && <Modal title={details.property.title_fa} onClose={() => setDetails(null)}><p>{details.property.is_synthetic ? 'آگهی نمایشی؛ قیمت فرضی است.' : 'آگهی واردشده؛ اطلاعات منبع را بررسی کنید.'}</p><p>دقت موقعیت: {details.property.location_accuracy} · عضویت محله: {details.property.neighborhood_membership_status === 'ambiguous' ? 'مبهم به‌علت هم‌پوشانی' : namesFor(details.property.neighborhood_ids)}</p><p>انتشار: {dateText(details.property.published_at)} · گردآوری: {dateText(details.property.collected_at)}</p><h3>منشأ داده</h3>{details.property.source_records.map((source, i) => <p key={i}>{source.source} · <bdi>{source.source_id}</bdi>{source.url && /^https?:\/\//i.test(source.url) && <a href={source.url} target="_blank" rel="noopener noreferrer"> مشاهدهٔ منبع</a>}</p>)}<h3>دسترسی این خانه</h3><AccessibilitySummary row={details} /><h3>مسیر منتخب</h3>{details.selected_itinerary ? <RouteDetails itinerary={details.selected_itinerary} /> : <p>{routeNames[details.route_status] ?? 'مسیر تأییدشده‌ای ثبت نشده است.'}</p>}{(details.qualifying_itineraries?.length ?? 0) > 1 && <details><summary>مسیرهای جایگزینِ منطبق</summary>{details.qualifying_itineraries?.filter(i => i.itinerary_id !== details.selected_itinerary?.itinerary_id).map(i => <RouteDetails key={i.itinerary_id} itinerary={i} />)}</details>}<button onClick={() => { setRoute(details.selected_itinerary); setView('map'); setDetails(null); }}>نمایش روی نقشه</button></Modal>}
    <footer className="site-footer"><strong>خانه‌سنج</strong><p>آگهی‌ها و قیمت‌های نمایشی، پیشنهاد بازار نیستند. ودیعه و اجاره جدا محاسبه می‌شوند.</p><p>{health.otp.routing_api_verified ? 'اتصال واقعی مسیریابی قبلاً تأیید شده؛ هر درخواست ممکن است با خطا یا نبود مسیر مواجه شود.' : 'اتصال واقعی مسیریابی هنوز تأیید نشده است.'} {health.otp.schedule_basis === 'unknown' && 'مبنای برنامهٔ زمانی نامعلوم است.'}</p></footer>
  </div>;
}

function NumericInput({ label, value, onValue }: { label: string; value: number | null; onValue: (value: number | null) => void }) {
  const [text, setText] = useState(value === null ? '' : String(value));
  const [error, setError] = useState('');
  useEffect(() => { setText(value === null ? '' : String(value)); setError(''); }, [value]);
  return <label className="numeric-field">{label}<input inputMode="decimal" value={text} aria-invalid={!!error} placeholder="بدون محدودیت" onChange={event => { const next = event.target.value; setText(next); try { const number = parseNumeric(next); if (number !== null && number > Number.MAX_SAFE_INTEGER) throw new Error('عدد بیش از حد بزرگ است'); onValue(number); setError(''); } catch (e) { setError((e as Error).message); } }} />{error && <small role="alert">{error}</small>}</label>;
}

const sentEvents = new Set<string>();
function sendEvent(requestId: string, eventType: string, candidateId: string | null, extra: Record<string, unknown> = {}) {
  const key = `${requestId}:${eventType}:${candidateId}`;
  if (['result_rendered', 'result_impression'].includes(eventType)) {
    if (sentEvents.has(key)) return;
    sentEvents.add(key);
  }
  void api('/events', post({ event_id: uuid(), event_type: eventType, request_id: requestId, candidate_id: candidateId, ...extra })).catch(() => { sentEvents.delete(key); });
}

function PropertyCard({ row, neighborhood, active, requestId, compared, onSelect, onDetails, onCompare, onFeedback }: { row: ResultRow; neighborhood: string; active: boolean; requestId: string | null; compared: boolean; onSelect: () => void; onDetails: () => void; onCompare: () => void; onFeedback: (positive: boolean, reason?: string) => void }) {
  const [reason, setReason] = useState('');
  const ref = useRef<HTMLElement | null>(null), p = row.property, route = row.selected_itinerary;
  useEffect(() => {
    if (!requestId || !ref.current) return;
    sendEvent(requestId, 'result_rendered', p.property_id);
    let timer: number | undefined;
    const observer = new IntersectionObserver(entries => {
      window.clearTimeout(timer);
      if (entries[0].intersectionRatio >= 0.5) timer = window.setTimeout(() => sendEvent(requestId, 'result_impression', p.property_id, { visible_fraction: 0.5, visible_ms: 1000 }), 1000);
    }, { threshold: [0, 0.5, 1] });
    observer.observe(ref.current);
    return () => { observer.disconnect(); window.clearTimeout(timer); };
  }, [requestId, p.property_id]);
  return <article ref={ref} id={`card-${p.property_id}`} data-property-id={p.property_id} className={`property-card ${active ? 'selected' : ''}`} onFocus={onSelect}>
    <div className="card-top"><span className={`series-dot ${p.series_id ?? ''}`} aria-hidden="true">{p.series_id === 'demo_b' ? '■' : p.series_id === 'demo_c' ? '▲' : '●'}</span><span className="demo-label">{p.is_synthetic ? 'آگهی نمایشی' : 'آگهی واردشده'}</span><span className="neighborhood">{neighborhood || 'محله نامعلوم'}</span></div>
    <h3><button className="title-button" onClick={onDetails}>{p.title_fa}</button></h3><p className="property-specs">{digits(p.area_m2)} متر · {digits(p.bedrooms)} اتاق · پارکینگ {yesNo(p.parking)} · آسانسور {yesNo(p.elevator)}</p>
    <p className="card-provenance">{p.is_synthetic ? 'تولیدکنندهٔ دادهٔ نمایشی' : p.source_records.map(s => s.source).join('، ')} · {dateText(p.published_at)} · موقعیت {p.location_accuracy === 'exact' ? 'دقیقِ ثبت‌شده' : p.location_accuracy === 'approximate' ? 'تقریبی' : p.is_synthetic ? 'نمونه‌گیری نمایشی' : 'نامعلوم'}</p><dl className="prices"><div><dt>اجارهٔ ماهانه</dt><dd>{money(p.monthly_rent_toman)}</dd></div><div><dt>ودیعه</dt><dd>{money(p.deposit_toman)}</dd></div></dl>
    {row.accessibility ? <AccessibilitySummary row={row} /> : route ? <div className="route-summary"><strong>{duration(route.total_duration_seconds)} سفر</strong><span>{duration(route.walk_duration_seconds)} پیاده‌روی</span><span>{digits(route.walk_distance_meters)} متر پیاده‌روی</span><span>{digits(route.transfers)} تعویض</span><small>{[...new Set(route.legs.map(leg => leg.mode === 'WALK' ? 'پیاده' : leg.mode === 'BUS' ? 'اتوبوس' : String(leg.mode ?? 'نامعلوم')))].join(' + ')} · {route.legs.length > 0 && route.legs.every(leg => leg.mode === 'WALK') ? 'سفر تماماً پیاده · ' : ''}{route.source_kind === 'synthetic_fixture' ? 'مسیر ساختگی دمو' : route.source_kind === 'recorded_otp' ? 'پاسخ ذخیره‌شده' : 'دریافت جاری OTP'}؛ شروع {dateText(route.start_datetime)}؛ پایان {dateText(route.end_datetime)}</small>{route.schedule_basis === 'synthetic_schedule' && <small>برآورد مبتنی بر برنامهٔ فرضی</small>}{route.schedule_basis === 'unknown' && <small>مبنای برنامهٔ زمانی نامعلوم</small>}</div> : <p className="muted">{routeNames[row.route_status] ?? 'مسیر نامعلوم'}</p>}
    <div className="card-actions">{requestId && <select className="feedback-reason" aria-label="دلیل اختیاری بازخورد" value={reason} onChange={e => setReason(e.target.value)}><option value="">دلیل بازخورد (اختیاری)</option><option value="budget">بودجه</option><option value="commute">رفت‌وآمد</option><option value="amenities">امکانات</option><option value="location">موقعیت</option><option value="missing_evidence">اطلاعات ناکافی</option><option value="other">دلیل دیگر</option></select>}<button onClick={onDetails}>جزئیات و مسیر</button><button aria-pressed={compared} onClick={onCompare}>{compared ? 'حذف از مقایسه' : 'افزودن به مقایسه'}</button>{requestId && <><button aria-label={`مناسب است: ${p.title_fa}`} onClick={() => onFeedback(true, reason)}>مناسب است</button><button aria-label={`مناسب نیست: ${p.title_fa}`} onClick={() => onFeedback(false, reason)}>مناسب نیست</button></>}</div>
  </article>;
}

function comparisonValue(row: ResultRow, field: string) {
  const p = row.property, r = row.selected_itinerary;
  return ({ rent: money(p.monthly_rent_toman), deposit: money(p.deposit_toman), area: digits(p.area_m2), bedrooms: digits(p.bedrooms), parking: yesNo(p.parking), elevator: yesNo(p.elevator), duration: duration(row.accessibility?.total_duration_seconds ?? r?.total_duration_seconds ?? null), walk: duration(row.accessibility?.walk_duration_seconds ?? r?.walk_duration_seconds ?? null), transfers: digits(r?.transfers), source: p.is_synthetic ? 'نمایشی' : p.source_records.map(s => s.source).join('، ') } as Record<string, string>)[field];
}

function placeName(value: unknown): string { return value && typeof value === 'object' ? String((value as Record<string, unknown>).name ?? 'نامعلوم') : 'نامعلوم'; }

function lineName(leg: Record<string, unknown>): string {
  const line = leg.route ?? leg.line;
  if (line && typeof line === 'object') {
    const value = line as Record<string, unknown>;
    return String(value.publicCode ?? value.name ?? value.id ?? '');
  }
  return String(leg.route_short_name ?? line ?? '');
}

function RouteDetails({ itinerary: i }: { itinerary: Itinerary }) {
  return <div className="route-detail"><p><strong>{duration(i.total_duration_seconds)}</strong> سفر · {duration(i.walk_duration_seconds)} پیاده‌روی · {digits(i.walk_distance_meters)} متر · {digits(i.transfers)} تعویض</p><p>شروع: {dateText(i.start_datetime)}<br />پایان: {dateText(i.end_datetime)}</p>{i.time_mode === 'DEPART_AT' && <p>از ساعت درخواست تا شروع: {duration(i.request_to_start_seconds)}</p>}<p>{i.source_kind === 'synthetic_fixture' ? 'مسیر ساختگیِ دمو' : i.source_kind === 'live_otp' ? 'دریافت جاری از OTP' : 'پاسخ ذخیره‌شدهٔ OTP'} · {i.schedule_basis === 'synthetic_schedule' ? 'برآورد مبتنی بر برنامهٔ فرضی' : i.schedule_basis === 'official_schedule' ? 'برنامهٔ رسمی' : 'مبنای برنامه نامعلوم'} · {i.realtime_status === 'available' ? 'دادهٔ لحظه‌ای موجود' : 'دادهٔ لحظه‌ای تأیید نشده'}</p><ol className="route-legs">{i.legs.map((leg, index) => <li className={leg.mode === 'WALK' ? 'walk-leg' : 'transit-leg'} key={index}><strong>{leg.mode === 'WALK' ? 'پیاده‌روی' : leg.mode === 'BUS' ? 'اتوبوس' : String(leg.mode ?? 'نوع نامعلوم')}</strong> {lineName(leg)}<span>{placeName(leg.from)} ← {placeName(leg.to)}</span><span>{duration(typeof leg.duration_seconds === 'number' ? leg.duration_seconds : null)} · {digits(typeof leg.distance_meters === 'number' ? leg.distance_meters : null)} متر</span></li>)}</ol>{i.missing_fields.length > 0 && <p className="muted">بعضی اطلاعات مسیر، از جمله {i.missing_fields.includes('transfers') ? 'تعداد تعویض' : 'بخش‌هایی از جزئیات'} در پاسخ موجود نیست.</p>}{!i.geometry && <p>هندسهٔ قابل نمایش برای این مسیر موجود نیست.</p>}</div>;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement | null>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog ref={ref} className="detail-modal" aria-label={title} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}><header><h2>{title}</h2><button aria-label="بستن پنجره" onClick={onClose}>بستن ×</button></header>{children}</dialog>;
}
