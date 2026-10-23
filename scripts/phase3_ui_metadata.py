"""Expose review comparisons and source versions without persisting credentials in the browser."""
from pathlib import Path
p = Path('backend/app/integration.py')
s = p.read_text(encoding='utf-8').replace("{'adapter': ADAPTER_VERSION, 'graph':", "{'inventory': self.catalog().version, 'boundary_assignments': self.catalog().boundary_version, 'adapter': ADAPTER_VERSION, 'graph':")
p.write_text(s, encoding='utf-8')
p = Path('frontend/src/InternalReview.tsx')
s = p.read_text(encoding='utf-8')
s = s.replace("  providers: Json; otp: Json; retrieval: Json; jobs: Json; unavailable_metrics: Json;", "  providers: Json; otp: Json; retrieval: Json; jobs: Json; unavailable_metrics: Json; grounding: Json; human_judge_agreement: Json; stage_latency: Json[];")
s = s.replace("  const [issue, setIssue] = useState('');", "  const [issue, setIssue] = useState('');\n  const [version, setVersion] = useState('');\n  const [pair, setPair] = useState<Json | null>(null);")
s = s.replace("    if (issue) params.set('issue', issue);", "    if (issue) params.set('issue', issue);\n    if (version) params.set('version', version);")
s = s.replace("setPreferredId('');\n  }", "setPreferredId(''); setPair(null);\n  }")
s = s.replace("'jobs', 'unavailable_metrics']", "'jobs', 'grounding', 'human_judge_agreement', 'stage_latency', 'unavailable_metrics']")
s = s.replace("        <button disabled={busy} onClick={() => void perform(refresh)}>اعمال فیلتر</button>", "        <label>نسخهٔ نمونه‌گیری<input value={version} onChange={e => setVersion(e.target.value)} /></label>\n        <button disabled={busy} onClick={() => void perform(refresh)}>اعمال فیلتر</button>")
s = s.replace("value={preferredId} onChange={e => setPreferredId(e.target.value)}/></label></div>}", "value={preferredId} onChange={e => setPreferredId(e.target.value)}/></label><button disabled={busy || !otherId} onClick={() => void perform(async () => setPair(await api<Json>(`reviews/${selected.sample_id}/pair/${encodeURIComponent(otherId)}`)))}>مشاهدهٔ شواهد گزینهٔ دوم</button>{pair && <pre dir=\"ltr\">{format(pair)}</pre>}</div>}")
s = s.replace("        {job && <pre dir=\"ltr\">{format(job)}</pre>}", """        {job && <pre dir="ltr">{format(job)}</pre>}
        {job && typeof (job.result as Json | undefined)?.dataset_id === 'string' && <button onClick={() => void perform(async () => {
          const datasetId = String((job.result as Json).dataset_id);
          const response = await fetch('/api/internal/datasets/' + encodeURIComponent(datasetId) + '/annotations.jsonl', {headers: {'x-review-token': token}});
          if (!response.ok) throw new Error('دریافت فایل ناموفق بود');
          const url = URL.createObjectURL(await response.blob());
          const link = document.createElement('a'); link.href = url; link.download = datasetId + '.jsonl'; link.click(); URL.revokeObjectURL(url);
        })}>دانلود دیتاست JSONL</button>}""")
p.write_text(s, encoding='utf-8')
p = Path('frontend/playwright.phase3.config.ts')
s = p.read_text(encoding='utf-8').replace("testMatch: 'phase3*.spec.ts'", "testMatch: ['phase3*.spec.ts', 'phase2.spec.ts'], grep: /restricted internal|internal page|normal consumer|advanced confirmation/")
p.write_text(s, encoding='utf-8')
p = Path('.env.example')
s = p.read_text(encoding='utf-8')
if 'QS_FEEDBACK_WINDOW_HOURS' not in s:
    s += '''
# Phase 3: opt-in internal evaluation; credentials stay on the backend.
QS_FEEDBACK_WINDOW_HOURS=24
REVIEWER_TOKENS_JSON={}
REVIEW_QUEUE_MAX=100
AI_IMPROVEMENT_ENABLED=false
JUDGE_MAX_OUTPUT_TOKENS=768
JUDGE_DAILY_MAX_RESERVED_TOKENS=30000
JUDGE_MAX_CALLS_PER_MINUTE=10
JUDGE_MAX_CONCURRENCY=1
# Optional hard cost ceiling requires a confirmed conservative account-specific rate.
JUDGE_DAILY_MAX_COST_USD=
JUDGE_UPPER_COST_PER_MILLION_TOKENS_USD=
IMPROVEMENT_MAX_OUTPUT_TOKENS=768
IMPROVEMENT_DAILY_MAX_REQUESTS=20
IMPROVEMENT_DAILY_MAX_RESERVED_TOKENS=15000
IMPROVEMENT_MAX_CALLS_PER_MINUTE=5
IMPROVEMENT_MAX_CONCURRENCY=1
IMPROVEMENT_DAILY_MAX_COST_USD=
IMPROVEMENT_UPPER_COST_PER_MILLION_TOKENS_USD=
'''
p.write_text(s, encoding='utf-8')
