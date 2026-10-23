import { useState } from 'react';
import './internal-review.css';

type Json = Record<string, unknown>;
type Kpi = {
  status: 'ok' | 'insufficient_data'; value: number | null; reason: string | null;
  source_mode: string; sample_size: number;
  coverage: { value: number | null; numerator: number; denominator: number; reason?: string };
  period: { start: string | null; end: string | null; basis: string };
  policy_version: string | null; counts?: Record<string, number>; context_counts?: Record<string, number>;
  cohort: string; unit?: string;
};
type Sample = {
  sample_id: string; request_id: string; candidate_id: string; status: string; actor_kind: string;
  revision: number; initial_blind: boolean; leased_by_you: boolean; reasons: string[];
  evidence: { facts: Record<string, { value: unknown; unit?: string }>; frozen_candidate: Json; confirmed_state?: Json; search_mode?: string; versions?: Json; ranking_scope?: string };
  history: Json[];
};
type Dashboard = {
  primary_kpis: {
    normal: { qs_at_5: Kpi; human_ndcg_at_5: Kpi; finalized_search_p95_ms: Kpi };
    advanced: { qs_at_5: Kpi; human_ndcg_at_5: Kpi; gemini_groundedness: Kpi };
  };
  real_qs_status: string; qs: Array<{ mode: string; actor_cohort: string; N: number; S: number; F: number; U: number; pending: number; qs_at_5: { value: number | null } }>;
  review: { samples: number; annotations: number; independent_real_graded: number };
  search: { request_count: number }; experiments: Json[]; datasets: Json[]; releases: Json[];
  providers: Json; otp: Json; retrieval: Json; jobs: Json; unavailable_metrics: Json; grounding: Json; human_judge_agreement: Json; stage_latency: Json[];
};
const display = (value: unknown) => value === null || value === undefined ? 'نامعلوم' : typeof value === 'boolean' ? (value ? 'بله' : 'خیر') : typeof value === 'object' ? JSON.stringify(value) : String(value);
const format = (value: unknown) => JSON.stringify(value, null, 2);
const percentage = (value: number | null) => value === null ? 'نامعلوم' : `${(value * 100).toFixed(1)}٪`;

function PrimaryKpi({ id, title, metric, latency = false }: { id: string; title: string; metric: Kpi; latency?: boolean }) {
  const available = metric.status === 'ok' && metric.value !== null;
  return <article data-kpi={id} aria-label={title}>
    <span>{title}</span>
    <strong><bdi>{available ? (latency ? `${metric.value!.toFixed(1)} ms` : percentage(metric.value)) : 'insufficient_data'}</bdi></strong>
    {!available && <p className="review-kpi-reason">{metric.reason ?? 'دادهٔ معتبر برای محاسبه موجود نیست.'}</p>}
    <small>تعداد نمونه: {metric.sample_size} · پوشش: {percentage(metric.coverage.value)} ({metric.coverage.numerator}/{metric.coverage.denominator})</small>
    <details><summary>منشأ و دامنهٔ سنجش</summary>
      <dl><dt>حالت منبع</dt><dd><bdi>{metric.source_mode}</bdi></dd>
        <dt>گروه</dt><dd><bdi>{metric.cohort}</bdi></dd>
        <dt>دوره</dt><dd><bdi>{metric.period.start ?? 'ثبت نشده'} — {metric.period.end ?? 'ثبت نشده'}</bdi></dd>
        <dt>مبنای دوره</dt><dd><bdi>{metric.period.basis}</bdi></dd>
        <dt>نسخهٔ سیاست</dt><dd><bdi>{metric.policy_version ?? 'ثبت نشده'}</bdi></dd>
        {metric.coverage.reason && <><dt>محدودیت پوشش</dt><dd>{metric.coverage.reason}</dd></>}
      </dl>
      {metric.counts && <><p>شمارش نمونه‌ها؛ شامل نامعلوم و در انتظار</p><pre dir="ltr">{format(metric.counts)}</pre></>}
      {metric.context_counts && <><p>بافت دسترسی؛ مقصد یا ایستگاه</p><pre dir="ltr">{format(metric.context_counts)}</pre></>}
    </details>
  </article>;
}

export default function InternalReview() {
  const [token, setToken] = useState('');
  const [authenticated, setAuthenticated] = useState(false);
  const [report, setReport] = useState<Dashboard | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [selected, setSelected] = useState<Sample | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [mode, setMode] = useState('');
  const [origin, setOrigin] = useState('');
  const [issue, setIssue] = useState('');
  const [version, setVersion] = useState('');
  const [priority, setPriority] = useState('');
  const [pair, setPair] = useState<Json | null>(null);
  const [grade, setGrade] = useState('');
  const [kind, setKind] = useState('relevance_grade');
  const [refs, setRefs] = useState<string[]>([]);
  const [reason, setReason] = useState('other');
  const [patch, setPatch] = useState('[]');
  const [otherId, setOtherId] = useState('');
  const [preferredId, setPreferredId] = useState('');
  const [supersedes, setSupersedes] = useState('');
  const [requestIds, setRequestIds] = useState('');
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState<Json | null>(null);

  async function api<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch('/api/internal/' + path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: { 'x-review-token': token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : format(result.detail));
    return result as T;
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function refresh() {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (mode) params.set('mode', mode);
    if (origin) params.set('origin', origin);
    if (issue) params.set('issue', issue);
    if (version) params.set('version', version);
    if (priority) params.set('priority', priority);
    const [dashboard, queue] = await Promise.all([api<Dashboard>('dashboard'), api<{ samples: Sample[] }>('reviews?' + params)]);
    setReport(dashboard); setSamples(queue.samples); setAuthenticated(true);
  }
  async function take(sample: Sample) {
    const claimed = await api<Sample>(`reviews/${sample.sample_id}/claim`, { revision: sample.revision });
    setSelected(claimed); setGrade(''); setRefs([]); setSupersedes(''); setPatch('[]'); setOtherId(''); setPreferredId(''); setPair(null);
  }
  async function submit(action = 'annotate') {
    if (!selected) return;
    await api(`reviews/${selected.sample_id}/annotations`, {
      idempotency_key: crypto.randomUUID(), revision: selected.revision, annotation_type: kind,
      grade: kind === 'relevance_grade' && grade !== '' && action === 'annotate' ? Number(grade) : null,
      evidence_refs: refs, reason, action, supersedes: supersedes || null,
      operations: kind === 'corrected_intent_patch' ? JSON.parse(patch) : [],
      other_id: kind === 'pairwise_preference' ? otherId || null : null,
      preferred_id: kind === 'pairwise_preference' ? preferredId || null : null,
    });
    setSelected(null); await refresh(); setNotice('بازبینی ثبت شد؛ تاریخچهٔ قبلی حفظ شده است.');
  }
  return <main className="review-app" dir="rtl">
    <header className="review-header"><div><a href="/">خانه‌سنج</a><h1>ارزیابی و بازبینی داخلی</h1><p>شواهد ثابت · رأی مستقل · انتشار کنترل‌شده</p></div>
      {authenticated && <button onClick={() => { setToken(''); setAuthenticated(false); setReport(null); setSamples([]); setSelected(null); }}>خروج</button>}</header>
    {!authenticated ? <form className="review-login" onSubmit={e => { e.preventDefault(); void perform(refresh); }}>
      <h2>ورود بازبین</h2><p>نسخهٔ داخلی محلی. کلید فقط در حافظهٔ این صفحه نگه داشته می‌شود.</p>
      <label>کلید دسترسی<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required /></label>
      <button disabled={busy || !token}>ورود به پنل</button>
    </form> : <>
      {report && <>
        <section className="review-panel review-kpis" aria-label="شاخص‌های اصلی جست‌وجوی عادی">
          <h2>جست‌وجوی عادی</h2><div className="review-summary review-kpi-summary">
            <PrimaryKpi id="normal-qs_at_5" title="QS@5" metric={report.primary_kpis.normal.qs_at_5}/>
            <PrimaryKpi id="normal-human_ndcg_at_5" title="NDCG@5 با برچسب انسانی" metric={report.primary_kpis.normal.human_ndcg_at_5}/>
            <PrimaryKpi id="normal-finalized_search_p95_ms" title="صدک ۹۵ زمان جست‌وجوی نهایی‌شده" metric={report.primary_kpis.normal.finalized_search_p95_ms} latency/>
          </div>
        </section>
        <section className="review-panel review-kpis" aria-label="شاخص‌های اصلی جست‌وجوی پیشرفته">
          <h2>جست‌وجوی پیشرفته با AI</h2><div className="review-summary review-kpi-summary">
            <PrimaryKpi id="advanced-qs_at_5" title="QS@5" metric={report.primary_kpis.advanced.qs_at_5}/>
            <PrimaryKpi id="advanced-human_ndcg_at_5" title="NDCG@5 با برچسب انسانی" metric={report.primary_kpis.advanced.human_ndcg_at_5}/>
            <PrimaryKpi id="advanced-gemini_groundedness" title="Gemini Evidence Reliance" metric={report.primary_kpis.advanced.gemini_groundedness}/>
          </div>
        </section>
        <p className="review-cohort-note">گروه‌های دو حالت ممکن است متفاوت باشند؛ این اعداد بدون گروه‌های قابل مقایسه، برتری یک حالت را نشان نمی‌دهند.</p>
      </>}
      <details className="review-panel"><summary>نتایج ارزیابی و سلامت سرویس‌ها</summary>
      <section className="review-summary" aria-label="خلاصهٔ ارزیابی">
        <article><span>QS کاربران واقعی</span><strong>{report?.real_qs_status === 'available' ? 'دارای شواهد' : 'هنوز قابل محاسبه نیست'}</strong><small>تأیید صریح کاربر؛ مستقل از رأی مدل</small></article>
        <article><span>برچسب انسانی واقعی</span><strong>{report?.review.independent_real_graded ?? 0}</strong><small>دادهٔ نمایشی در این عدد وارد نمی‌شود</small></article>
        <article><span>صف بازبینی</span><strong>{report?.review.samples ?? 0}</strong><small>{report?.review.annotations ?? 0} رأی ثبت‌شده</small></article>
        <article><span>جست‌وجوی ذخیره‌شده</span><strong>{report?.search.request_count ?? 0}</strong><small>شواهد هر درخواست جدا حفظ می‌شود</small></article>
      </section>
        <p>QS فقط پس از پایان پنجرهٔ بازخورد محاسبه می‌شود. U به معنی نامعلوم است و شکست محسوب نمی‌شود.</p>
        <div className="review-table-wrap"><table><thead><tr><th>حالت / گروه</th><th>N</th><th>S</th><th>F</th><th>U</th><th>در انتظار</th><th>QS</th></tr></thead><tbody>
          {report?.qs.map((q, i) => <tr key={i}><td>{q.mode} / {q.actor_cohort}</td><td>{q.N}</td><td>{q.S}</td><td>{q.F}</td><td>{q.U}</td><td>{q.pending}</td><td>{q.qs_at_5.value === null ? 'نامعلوم' : (q.qs_at_5.value * 100).toFixed(1) + '٪'}</td></tr>)}
        </tbody></table></div>
        {(['otp', 'retrieval', 'providers', 'experiments', 'datasets', 'releases', 'jobs', 'grounding', 'human_judge_agreement', 'stage_latency', 'unavailable_metrics'] as const).map(key => <details key={key}><summary>{key}</summary><pre dir="ltr">{format(report?.[key])}</pre></details>)}
      </details>
      <section className="review-panel"><h2>صف شواهد</h2><div className="review-filters">
        <label>وضعیت<select value={status} onChange={e => setStatus(e.target.value)}><option value="">همه</option>{['pending', 'human_reviewed', 'skipped', 'insufficient_evidence', 'escalated', 'resolved'].map(v => <option key={v}>{v}</option>)}</select></label>
        <label>حالت<select value={mode} onChange={e => setMode(e.target.value)}><option value="">همه</option><option>normal</option><option>advanced</option></select></label>
        <label>منشأ<select value={origin} onChange={e => setOrigin(e.target.value)}><option value="">همه</option><option>demo</option><option>real_user</option><option>test</option></select></label>
        <label>نوع مسئله<input value={issue} onChange={e => setIssue(e.target.value)} placeholder="مثلاً missing_evidence" /></label>
        <label>اولویت<select value={priority} onChange={e => setPriority(e.target.value)}><option value="">همه</option><option value="critical">بحرانی</option><option value="high">بالا</option><option value="normal">عادی</option></select></label>
        <label>نسخهٔ نمونه‌گیری<input value={version} onChange={e => setVersion(e.target.value)} /></label>
        <button disabled={busy} onClick={() => void perform(refresh)}>اعمال فیلتر</button>
      </div>
      <div className="review-workspace"><aside className="review-queue" aria-label="نمونه‌های بازبینی">
        {!samples.length && <p>نمونه‌ای با این فیلتر وجود ندارد.</p>}
        {samples.map(sample => <button key={sample.sample_id} disabled={busy} className={selected?.sample_id === sample.sample_id ? 'selected' : ''} onClick={() => void perform(() => take(sample))}>
          <strong dir="ltr">{sample.candidate_id}</strong><span>{sample.actor_kind === 'real_user' ? 'دادهٔ واقعی' : 'دادهٔ نمایشی / آزمایشی'} · {sample.status}</span><small>{sample.reasons.join(' · ')}</small></button>)}
      </aside><section className="review-detail">
        {!selected ? <p>یک نمونه را انتخاب کنید. رزرو بازبینی ۱۰ دقیقه اعتبار دارد.</p> : <>
          <h3>بازبینی آگهی <bdi>{selected.candidate_id}</bdi></h3>
          <p className="review-badge">{selected.initial_blind ? 'رأی اولیهٔ مستقل؛ پیشنهاد AI و رتبه پنهان است' : 'رأی اولیه ثبت شده؛ تاریخچه قابل مشاهده است'}</p>
          <p>۰: نامناسب · ۱: ضعیف · ۲: مناسب · ۳: بسیار مناسب · نامعلوم: شواهد کافی نیست. امتیاز مناسب جایگزین عبور از شروط قطعی نمی‌شود.</p>
          <details><summary>نیاز تأییدشده و شواهد مسیر</summary><pre dir="ltr">{format(selected.evidence)}</pre></details>
          <fieldset><legend>شواهد مورد استناد</legend><div className="review-facts">{Object.entries(selected.evidence.facts).map(([ref, fact]) => <label key={ref}>
            <input type="checkbox" checked={refs.includes(ref)} onChange={e => setRefs(old => e.target.checked ? [...old, ref] : old.filter(v => v !== ref))}/><span><bdi>{ref.split(':').at(-1)}</bdi>: {display(fact.value)} <small>{fact.unit ?? ''}</small></span>
          </label>)}</div></fieldset>
          <div className="review-fields"><label>نوع بازبینی<select value={kind} onChange={e => setKind(e.target.value)}>{['relevance_grade', 'corrected_intent_patch', 'pairwise_preference', 'grounding_issue', 'explanation_comparison_issue', 'semantic_retrieval_miss', 'candidate_eligibility_issue', 'data_issue', 'infrastructure_issue'].map(v => <option key={v}>{v}</option>)}</select></label>
          {kind === 'relevance_grade' && <label>درجهٔ تناسب<select aria-label="درجهٔ تناسب" value={grade} onChange={e => setGrade(e.target.value)}><option value="">نامعلوم</option>{[0, 1, 2, 3].map(v => <option key={v}>{v}</option>)}</select></label>}
          <label>دلیل<select value={reason} onChange={e => setReason(e.target.value)}>{['other', 'budget', 'commute', 'amenities', 'location', 'missing_evidence'].map(v => <option key={v}>{v}</option>)}</select></label></div>
          {kind === 'corrected_intent_patch' && <label>پیشنهاد اصلاح شروط؛ بدون تغییر جست‌وجوی اصلی<textarea dir="ltr" value={patch} onChange={e => setPatch(e.target.value)} /></label>}
          {kind === 'pairwise_preference' && <div className="review-fields"><label>شناسهٔ گزینهٔ دوم<input value={otherId} onChange={e => setOtherId(e.target.value)}/></label><label>شناسهٔ گزینهٔ ترجیحی؛ خالی یعنی تساوی<input value={preferredId} onChange={e => setPreferredId(e.target.value)}/></label><button disabled={busy || !otherId} onClick={() => void perform(async () => setPair(await api<Json>(`reviews/${selected.sample_id}/pair/${encodeURIComponent(otherId)}`)))}>مشاهدهٔ شواهد گزینهٔ دوم</button>{pair && <pre dir="ltr">{format(pair)}</pre>}</div>}
          {!!selected.history.length && <><details><summary>تاریخچهٔ تغییرناپذیر</summary><pre dir="ltr">{format(selected.history)}</pre></details><label>اصلاح رأی قبلی؛ شناسهٔ رأی<input value={supersedes} onChange={e => setSupersedes(e.target.value)}/></label></>}
          <div className="review-actions"><button disabled={busy} onClick={() => void perform(() => submit())}>ثبت بازبینی</button><button disabled={busy} onClick={() => void perform(() => submit('insufficient_evidence'))}>شواهد ناکافی</button><button disabled={busy} onClick={() => void perform(() => submit('skip'))}>عبور</button><button disabled={busy} onClick={() => void perform(() => submit('escalate'))}>ارجاع مسئله</button><button disabled={busy} onClick={() => void perform(() => submit('resolve'))}>حل شد</button></div>
        </>}
      </section></div></section>
      <details className="review-panel"><summary>عملیات ارزیابی</summary><p>کارها در صف مستقل اجرا می‌شوند. مدل فقط با فعال‌سازی صریح backend فراخوانی می‌شود.</p>
        <label>شناسهٔ درخواست‌ها؛ جدا با ویرگول<input dir="ltr" value={requestIds} onChange={e => setRequestIds(e.target.value)} /></label>
        <div className="review-actions"><button disabled={busy || !requestIds} onClick={() => void perform(async () => { const r = await api<{ job_id: string }>('acquire', { request_ids: requestIds.split(',').map(s => s.trim()).filter(Boolean), seed: 17, batch_size: 20 }); setJobId(r.job_id); })}>نمونه‌گیری برای بازبینی</button>
        <button disabled={busy} onClick={() => void perform(async () => { const r = await api<{ job_id: string }>('datasets/export', {}); setJobId(r.job_id); })}>خروجی نسخه‌دار JSONL</button></div>
        <label>شناسهٔ کار<input dir="ltr" value={jobId} onChange={e => setJobId(e.target.value)} /></label><button disabled={busy || !jobId} onClick={() => void perform(async () => setJob(await api<Json>('jobs/' + encodeURIComponent(jobId))))}>بررسی نتیجهٔ کار</button>
        {job && <pre dir="ltr">{format(job)}</pre>}
        {job && typeof (job.result as Json | undefined)?.dataset_id === 'string' && <button onClick={() => void perform(async () => {
          const datasetId = String((job.result as Json).dataset_id);
          const response = await fetch('/api/internal/datasets/' + encodeURIComponent(datasetId) + '/annotations.jsonl', {headers: {'x-review-token': token}});
          if (!response.ok) throw new Error('دریافت فایل ناموفق بود');
          const url = URL.createObjectURL(await response.blob());
          const link = document.createElement('a'); link.href = url; link.download = datasetId + '.jsonl'; link.click(); URL.revokeObjectURL(url);
        })}>دانلود دیتاست JSONL</button>}
      </details>
    </>}
    {error && <p role="alert" className="review-error">{error}</p>}{notice && <p role="status" className="review-notice">{notice}</p>}
    <footer>دادهٔ نمایشی پس از بازبینی هم نمایشی می‌ماند. مدل، بازبین و تأیید واقعی کاربر سه منشأ مستقل هستند.</footer>
  </main>;
}
