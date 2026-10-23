import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { SearchState, ParseOutput, PropertyConditions } from './contracts.generated';
import { api, post, digits, money, duration, parseNumeric } from './api';
import type { Boundary, Health, SearchResult } from './api';
import SearchMap, { series } from './SearchMap';

const sortOptions = [['recommended','پیشنهادی'],['rent_asc','اجاره کمتر'],['deposit_asc','ودیعه کمتر'],['travel_time_asc','مسیر کوتاه‌تر'],['walk_time_asc','پیاده‌روی کمتر'],['transfers_asc','تعویض کمتر']] as const;
const statuses:Record<string,string>={queued:'در صف بررسی مسیرها',running:'در حال بررسی مسیرها',complete:'بررسی کامل',partial:'بررسی بخشی از کاندیداها',cancelled:'بررسی متوقف شد',routing_unavailable:'فقط شروط ملک بررسی شده است'};
function NumericField({label,value,onChange,unit=''}:{label:string;value:number|null;onChange:(v:number|null)=>void;unit?:string}) {
  const [draft,setDraft]=useState(value===null?'':String(value));
  const [error,setError]=useState('');
  useEffect(()=>setDraft(value===null?'':String(value)),[value]);
  return <label className="field">{label}<div className="input-unit"><input inputMode="decimal" value={draft} placeholder="بدون محدودیت" onChange={e=>{setDraft(e.target.value);try{onChange(parseNumeric(e.target.value));setError('');e.target.setCustomValidity('');}catch{setError('عدد نامعتبر');e.target.setCustomValidity('عدد نامعتبر');}}} aria-invalid={!!error}/><span>{unit}</span></div>{error&&<small className="error">{error}</small>}</label>;
}

export default function App() {
  const [health,setHealth]=useState<Health|null>(null);
  const [state,setState]=useState<SearchState|null>(null);
  const [defaults,setDefaults]=useState<SearchState|null>(null);
  const [neighborhoods,setNeighborhoods]=useState<Boundary[]>([]);
  const [districts,setDistricts]=useState<Boundary[]>([]);
  const [result,setResult]=useState<SearchResult|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [query,setQuery]=useState('');
  const [parsed,setParsed]=useState<ParseOutput|null>(null);
  const [placeSearch,setPlaceSearch]=useState('');
  const [choose,setChoose]=useState(false);
  const [pendingDestination,setPendingDestination]=useState<{latitude:number;longitude:number;memberships:string[]}|null>(null);
  const [showBoundaries,setShowBoundaries]=useState(false);
  const [date,setDate]=useState(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tehran',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()));
  const [time,setTime]=useState('08:00');
  useEffect(()=>{Promise.all([api<Health>('/health'),api<SearchState>('/state/default'),api<{features:Boundary[]}>('/neighborhoods'),api<{features:Boundary[]}>('/districts')]).then(([h,s,n,d])=>{setHealth(h);setState(s);setDefaults(s);setNeighborhoods(n.features);setDistricts(d.features);}).catch(e=>setError(e.message));},[]);
  useEffect(()=>{
    if(!result||!['queued','running'].includes(result.completion_status))return;
    const requestId=result.request_id;
    const timer=window.setInterval(()=>api<SearchResult>(`/searches/${requestId}`).then(next=>setResult(current=>current?.request_id===requestId?next:current)).catch(e=>setError(e.message)),1000);
    return ()=>clearInterval(timer);
  },[result?.request_id,result?.completion_status]);
  const updateProperty=(key:keyof PropertyConditions,value:number|boolean|null)=>setState(s=>s?{...s,property:{...s.property,[key]:value}}:s);
  const updateTravel=(key:string,value:unknown)=>setState(s=>s?{...s,travel:{...s.travel,[key]:value}}:s);
  const togglePlace=(key:'selected_neighborhood_ids'|'selected_district_ids',id:string)=>setState(s=>s?{...s,[key]:s[key].includes(id)?s[key].filter(x=>x!==id):[...s[key],id]}:s);
  async function search(event?:FormEvent) {
    event?.preventDefault();if(!state)return;
    setBusy(true);setError('');
    try {
      if(result&&['queued','running'].includes(result.completion_status)) await api(`/searches/${result.request_id}/cancel`,post({}));
      const next={...state,query,travel:{...state.travel,date:state.travel.destination?date:null,time:state.travel.destination?(time.length===5?`${time}:00`:time):null}};
      const response=await api<SearchResult>('/searches',post({state:next,task_id:result?.task_id??null,parent_request_id:result?.request_id??null}));
      setState(response.state);setResult(response);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function parseQuery(){setError('');try{setParsed(await api<ParseOutput>('/parse',post({text:query})));}catch(e){setError((e as Error).message);}}
  async function applyParsed(){if(!state||!parsed)return;try{setState(await api<SearchState>('/state/patch',post({state,operations:parsed.operations})));setParsed(null);}catch(e){setError((e as Error).message);}}
  async function command(action:'cancel'|'continue'){if(!result)return;try{setResult(await api<SearchResult>(`/searches/${result.request_id}/${action}`,post({})));}catch(e){setError((e as Error).message);}}
  const isStale=!!result&&!!state&&JSON.stringify({...state,query,travel:{...state.travel,date:state.travel.destination?date:null,time:state.travel.destination?(time.length===5?`${time}:00`:time):null}})!==JSON.stringify(result.state);
  const neighborhoodName=(id:string|null)=>neighborhoods.find(f=>String(f.id??f.properties.id)===id)?.properties.name_fa??'محله نامعلوم';
  if(!state||!health)return <main className="loading"><div className="brand-icon">خ</div><h1>خانه‌سنج</h1><p>{error||'در حال دریافت داده‌های محله‌ها…'}</p>{error&&<button onClick={()=>location.reload()}>تلاش دوباره</button>}</main>;
  return <>
    <header className="topbar"><a className="brand" href="/"><span className="brand-icon">خ</span><span>خانه‌سنج<small>خانه و مسیر، کنار هم</small></span></a><nav><span className="nav-active">جست‌وجوی اجاره</span><span className="phase-badge">نسخهٔ نمایشی · مرحلهٔ ۱</span></nav><span className="service-dot">{health.otp.routing_api_verified?'آزمون OTP موفق':health.otp.fixture_mode?'مسیر نمایشی':'مسیر تأییدنشده'}</span></header>
    <section className="intro"><div><span className="eyebrow">تهران، محله به محله</span><h1>خانه‌ای که به زندگی‌ات <em>نزدیک‌تر</em> است.</h1><p>بودجه و ویژگی‌های خانه را مشخص کنید؛ مسیر تا مقصدتان را هم کنار آن ببینید.</p></div><div className="dataset-stat"><strong>{digits(health.listing_count)}</strong><span>آگهی ذخیره‌شده</span><small>{digits(neighborhoods.length)} عارضهٔ محله · {digits(districts.length)} منطقه</small></div></section>
    {error&&<div className="global-error" role="alert">{error}<button onClick={()=>setError('')}>بستن</button></div>}
    <main className="workspace">
      <aside className="filters"><form onSubmit={search}>
        <div className="section-title"><h2>خواسته‌های شما</h2><button type="button" className="text-button" onClick={()=>{setState(defaults);setQuery('');setPendingDestination(null);}}>پاک‌کردن شروط</button></div>
        <label className="field">توضیح کوتاه<textarea placeholder="اجاره تا ۱۵ میلیون تومان، حداقل ۲ اتاق" value={query} onChange={e=>setQuery(e.target.value)} maxLength={1000}/></label>
        <button type="button" className="secondary full" onClick={parseQuery}>برداشت شروط از متن</button><small className="muted">{health.llm.mode}</small>
        {parsed&&<div className="parse-preview"><b>{digits(parsed.operations.length)} شرط پیشنهادی</b><pre>{JSON.stringify(parsed.operations,null,2)}</pre>{parsed.unsupported.length>0&&<p>بخش درک‌نشده: {parsed.unsupported.join('، ')}</p>}<button type="button" onClick={applyParsed}>اعمال شروط پیشنهادی</button></div>}
        <div className="divider"/><h3>بودجه و مشخصات</h3>
        <NumericField label="سقف ودیعه" value={state.property.max_deposit_toman} onChange={v=>updateProperty('max_deposit_toman',v)} unit="تومان"/>
        <NumericField label="سقف اجارهٔ ماهانه" value={state.property.max_monthly_rent_toman} onChange={v=>updateProperty('max_monthly_rent_toman',v)} unit="تومان"/>
        <div className="field-pair"><NumericField label="حداقل متراژ" value={state.property.min_area_m2} onChange={v=>updateProperty('min_area_m2',v)} unit="متر"/><NumericField label="حداقل اتاق" value={state.property.min_bedrooms} onChange={v=>updateProperty('min_bedrooms',v)}/></div>
        <div className="checks"><label><input type="checkbox" checked={!!state.property.parking_required} onChange={e=>updateProperty('parking_required',e.target.checked)}/>پارکینگ الزامی</label><label><input type="checkbox" checked={!!state.property.elevator_required} onChange={e=>updateProperty('elevator_required',e.target.checked)}/>آسانسور الزامی</label></div>
        <div className="divider"/><h3>محدودهٔ جست‌وجو</h3><label className="field">جست‌وجوی نام محله<input placeholder="نام محله…" value={placeSearch} onChange={e=>setPlaceSearch(e.target.value)}/></label>
        <details open={!!placeSearch}><summary>محله‌ها <span>{digits(state.selected_neighborhood_ids.length)} انتخاب</span></summary><div className="place-list">{neighborhoods.filter(f=>!placeSearch||f.properties.name_fa.includes(placeSearch.replace(/ي/g,'ی').replace(/ك/g,'ک'))).map(f=>{const id=String(f.id??f.properties.id);return <label key={id}><input type="checkbox" checked={state.selected_neighborhood_ids.includes(id)} onChange={()=>togglePlace('selected_neighborhood_ids',id)}/>{f.properties.name_fa}<small>انتساب منبع: {digits(f.properties.district_no)}</small></label>;})}</div></details>
        <details><summary>مناطق <span>{digits(state.selected_district_ids.length)} انتخاب</span></summary><div className="district-grid">{districts.map(f=>{const id=String(f.id??f.properties.id);return <label key={id}><input type="checkbox" checked={state.selected_district_ids.includes(id)} onChange={()=>togglePlace('selected_district_ids',id)}/>{f.properties.name_fa||`منطقه ${digits(f.properties.district_no)}`}</label>;})}</div></details>
        <small className="muted">محله‌ها با هم «یا»، مناطق با هم «یا»؛ این دو گروه با هم «و» ترکیب می‌شوند.</small>
        <div className="divider"/><h3>رفت‌وآمد تا یک مقصد</h3>{health.otp.transfer_count_available===false&&<small className="muted">شمارش تعویض در API فعلی نامعلوم است؛ شرط سقف تعویض بدون شاهد عبور نمی‌کند.</small>}
        <button type="button" className="secondary full" onClick={()=>setChoose(!choose)}>{choose?'پایان انتخاب روی نقشه':state.travel.destination?'تغییر مقصد روی نقشه':'انتخاب مقصد روی نقشه'}</button>
        {pendingDestination&&<div className="destination-preview"><b>مقصد انتخاب‌شده</b><span dir="ltr">{pendingDestination.latitude.toFixed(5)}, {pendingDestination.longitude.toFixed(5)}</span><small>{pendingDestination.memberships.length>1?'عضویت محله مبهم است':pendingDestination.memberships.length?neighborhoodName(pendingDestination.memberships[0]):'خارج از محلات این داده'}</small><button type="button" onClick={()=>{updateTravel('destination',{latitude:pendingDestination.latitude,longitude:pendingDestination.longitude,label:'مقصد روی نقشه',confirmed:true});setChoose(false);setPendingDestination(null);}}>تأیید مقصد</button></div>}
        {state.travel.destination&&<><p className="destination-label">● مقصد تأیید شده <button type="button" className="text-button" onClick={()=>setState({...state,travel:defaults!.travel})}>حذف</button></p><div className="field-pair"><label className="field">تاریخ میلادی<input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label><label className="field">ساعت تهران<input type="time" value={time} onChange={e=>setTime(e.target.value)} required/></label></div><label className="field">معنای زمان<select value={state.travel.time_mode} onChange={e=>updateTravel('time_mode',e.target.value)}><option value="DEPART_AT">حرکت پس از این ساعت</option><option value="ARRIVE_BY">رسیدن تا این ساعت</option></select></label>
        <NumericField label="سقف مدت خود سفر" value={state.travel.max_duration_seconds===null?null:state.travel.max_duration_seconds/60} onChange={v=>updateTravel('max_duration_seconds',v===null?null:Math.round(v*60))} unit="دقیقه"/>
        <NumericField label="سقف مجموع پیاده‌روی" value={state.travel.max_walk_seconds===null?null:state.travel.max_walk_seconds/60} onChange={v=>updateTravel('max_walk_seconds',v===null?null:Math.round(v*60))} unit="دقیقه"/>
        <NumericField label="سقف فاصلهٔ پیاده‌روی" value={state.travel.max_walk_meters} onChange={v=>updateTravel('max_walk_meters',v)} unit="متر"/>
        <NumericField label="سقف تعویض وسیله" value={state.travel.max_transfers} onChange={v=>updateTravel('max_transfers',v)}/>
        {health.otp.supported_modes.length>0&&<div className="checks">{health.otp.supported_modes.map(mode=><label key={mode}><input type="checkbox" checked={state.travel.modes.includes(mode)} onChange={e=>updateTravel('modes',e.target.checked?[...state.travel.modes,mode]:state.travel.modes.filter(m=>m!==mode))}/>{mode}</label>)}</div>}
        <label className="checkbox-line"><input type="checkbox" checked={state.travel.include_walk_only} onChange={e=>updateTravel('include_walk_only',e.target.checked)}/>سفر تماماً پیاده هم مجاز باشد</label></>}
        <label className="field preference">اولویت پیشنهاد<select value={state.preference} onChange={e=>setState({...state,preference:e.target.value as SearchState['preference']})}><option value="balanced">متعادل</option><option value="lower_rent">اجارهٔ کمتر</option><option value="faster_commute">رفت‌وآمد سریع‌تر</option><option value="less_walking">پیاده‌روی کمتر</option><option value="fewer_transfers">تعویض کمتر</option></select></label>
        <button className="primary full search-button" disabled={busy}>{busy?'در حال جست‌وجو…':'جست‌وجوی خانه‌ها'} <span>←</span></button>
      </form></aside>
      <section className="results-area"><div className="map-toolbar"><span>نقشهٔ محله‌ها و خانه‌ها</span><label><input type="checkbox" checked={showBoundaries} onChange={e=>setShowBoundaries(e.target.checked)}/>نمایش مرز همهٔ محله‌ها</label></div>
        <SearchMap neighborhoods={neighborhoods} districts={districts} rows={result?.results??[]} selected={state.selected_neighborhood_ids} selectedDistricts={state.selected_district_ids} choose={choose} onChoose={setPendingDestination} destination={state.travel.destination} showBoundaries={showBoundaries}/>
        <div className="data-note"><span>ⓘ</span> مرزهای منبع ۲۰۲۰؛ صحت امروز آن‌ها تأیید نشده است. کاشی OSM مستقل است. قیمت آگهی‌های نمایشی، قیمت بازار نیست.</div>
        <div className="results-heading"><div><h2>{result?`${digits(result.result_count)} نتیجه`:'از خواسته‌های خودتان شروع کنید'}</h2><small>{result?statuses[result.completion_status]:'فیلترها را تنظیم کنید و جست‌وجو را بزنید.'}</small></div><label>مرتب‌سازی <select value={state.sort} onChange={e=>setState({...state,sort:e.target.value as SearchState['sort']})}>{sortOptions.map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></label></div>
        {isStale&&<div className="notice">شروط تغییر کرده‌اند؛ برای دیدن نتایج جدید، «جست‌وجوی خانه‌ها» را بزنید.</div>}
        {result&&<><div className="progress-panel"><div><b>{digits(result.evaluated_count)} از {digits(result.candidate_count)}</b><span> کاندیدای ملک برای مسیر بررسی شده‌اند</span></div>{result.ranking_scope==='evaluated_subset'&&<small>پیشنهادها فقط در زیرمجموعهٔ بررسی‌شده‌اند؛ نتیجهٔ کل کاندیداها نیستند.</small>}<div className="progress-track"><span style={{width:`${result.candidate_count?result.evaluated_count/result.candidate_count*100:0}%`}}/></div><div className="progress-actions">{['queued','running'].includes(result.completion_status)&&<button className="secondary" onClick={()=>command('cancel')}>توقف بررسی</button>}{['partial','cancelled'].includes(result.completion_status)&&<button className="secondary" onClick={()=>command('continue')}>بررسی دستهٔ بعدی</button>}<a href={`/api/searches/${result.request_id}/snapshot`} target="_blank" rel="noreferrer">شواهد این جست‌وجو ↗</a></div></div>{result.warnings.map((w,i)=><div className="notice" key={i}>{w}</div>)}
        {result.excluded_evaluations.length>0&&<details className="excluded"><summary>{digits(result.excluded_evaluations.length)} ارزیابی بدون نتیجهٔ منطبق</summary><p>در مسیرهای بازگشتی برای این تنظیمات گزینهٔ منطبق پیدا نشد، یا ارزیابی با خطا روبه‌رو شد.</p>{Object.entries(result.excluded_evaluations.reduce<Record<string,number>>((counts,r)=>({...counts,[r.status]:(counts[r.status]??0)+1}),{})).map(([status,count])=><p key={status}>{status}: {digits(count)}</p>)}</details>}
        <div className="listing-grid">{result.results.map(({property:p,selected_itinerary:route})=>{const group=series[p.series_id as keyof typeof series];return <article className="listing-card" key={p.property_id}><div className="card-top"><span className="synthetic-tag">{p.is_synthetic?'آگهی نمایشی':'آگهی واردشده'}</span><span style={{color:group?.color}}>{group?.symbol} {group?.label}</span></div><h3>{p.title_fa}</h3><p className="location">⌖ {neighborhoodName(p.neighborhood_id)}</p><div className="specs"><span>{digits(p.area_m2)} متر</span><span>{digits(p.bedrooms)} اتاق</span><span>پارکینگ {p.parking===null?'نامعلوم':p.parking?'دارد':'ندارد'}</span><span>آسانسور {p.elevator===null?'نامعلوم':p.elevator?'دارد':'ندارد'}</span></div><div className="price-row"><span>ودیعه</span><strong>{money(p.deposit_toman)}</strong></div><div className="price-row"><span>اجارهٔ ماهانه</span><strong>{money(p.monthly_rent_toman)}</strong></div>{route?<div className="commute"><div><strong>{duration(route.total_duration_seconds)}</strong><span>مدت سفر</span></div><div><strong>{duration(route.walk_duration_seconds)}</strong><span>مجموع پیاده‌روی</span></div><div><strong>{digits(route.transfers)}</strong><span>تعویض</span></div><small>{route.source_kind==='synthetic_fixture'?'مسیر کاملاً نمایشی':route.schedule_basis==='synthetic_schedule'?'برآورد مبتنی بر برنامهٔ فرضی':route.schedule_basis==='official_schedule'?'مبتنی بر برنامهٔ زمان‌بندی رسمی':'مبنای برنامهٔ زمانی نامعلوم'} · {route.realtime_status==='available'?'دادهٔ بلادرنگ موجود':'بلادرنگ تأیید نشده'}</small>{route.request_to_start_seconds!=null&&<small>فاصلهٔ ساعت درخواست تا شروع: {duration(route.request_to_start_seconds)}</small>}</div>:<div className="route-empty">زمان رفت‌وآمد محاسبه نشده است</div>}<details className="provenance"><summary>منشأ و دقت مکان</summary><p>{p.location_accuracy} · {p.district_membership_status}</p><p>{p.source_records.map(s=>s.source).join('، ')}</p></details></article>;})}</div>
        {result.result_count>result.results.length&&<p className="notice">نمایش {digits(result.results.length)} نتیجهٔ اول؛ همهٔ کاندیداها در snapshot ذخیره شده‌اند.</p>}
        {!result.results.length&&<div className="empty-state"><span>⌂</span><h3>{['queued','running'].includes(result.completion_status)?'مسیرها در حال بررسی‌اند':'فعلاً نتیجه‌ای برای نمایش نیست'}</h3><p>شروط انتخاب‌شده حفظ شده‌اند. وضعیت بررسی و پیام‌های بالا را ببینید.</p></div>}</>}
        {!result&&<div className="empty-state"><span>⌂</span><h3>یک تصویر روشن‌تر از انتخاب خانه</h3><p>ودیعه و اجاره مستقل‌اند؛ برای بررسی مسیر، یک مقصد روی نقشه تأیید کنید.</p><div className="starter-chips"><span>بودجهٔ شفاف</span><span>مرزهای قابل بررسی</span><span>شواهد مسیر</span></div></div>}
      </section>
    </main><footer>خانه‌سنج · دادهٔ نمایشی برای ارزیابی محصول <span>مرزهای منبع قدیمی‌اند و پوشش کامل شهر ادعا نمی‌شود.</span></footer>
  </>;
}
