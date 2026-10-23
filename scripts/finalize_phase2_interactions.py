"""Wire versioned interaction events and keep browser assertions aligned with copy."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'frontend/src/PhaseTwoApp.tsx'
content = path.read_text(encoding='utf-8')
content = content.replace("const patch = (field: string, value: unknown) => dispatch({ type: 'patch', operations: [operation(field, value)] });", """const patch = (field: string, value: unknown, source = 'form') => {
    dispatch({ type: 'patch', operations: [operation(field, value)] });
    const event = ({selected_neighborhood_ids:'neighborhood_filter_changed',selected_district_ids:'district_filter_changed',sort:'sort_changed'} as Record<string,string>)[field];
    if (result && event) sendEvent(result.request_id, event, null, {source});
  };""")
content = content.replace("const toggle = (field: 'selected_neighborhood_ids' | 'selected_district_ids', id: string) => patch(field, state[field].includes(id) ? state[field].filter(x => x !== id) : [...state[field], id]);", "const toggle = (field: 'selected_neighborhood_ids' | 'selected_district_ids', id: string, source = 'dropdown') => patch(field, state[field].includes(id) ? state[field].filter(x => x !== id) : [...state[field], id], source);")
content = content.replace("onToggleNeighborhood={id => toggle('selected_neighborhood_ids', id)}", "onToggleNeighborhood={id => toggle('selected_neighborhood_ids', id, 'map')}")
content = content.replace("candidateId: string, extra:", "candidateId: string | null, extra:")
content = content.replace("if (sentEvents.has(key)) return;\n  sentEvents.add(key);", "if (['result_rendered', 'result_impression'].includes(eventType)) {\n    if (sentEvents.has(key)) return;\n    sentEvents.add(key);\n  }")
content = content.replace("onClick={() => setMode('normal')}", "onClick={() => { setMode('normal'); if(result) sendEvent(result.request_id, 'search_mode_changed', null); }}")
content = content.replace("onClick={() => setMode('advanced')}", "onClick={() => { setMode('advanced'); if(result) sendEvent(result.request_id, 'search_mode_changed', null); }}")
content = content.replace("async function feedback(kind: 'property' | 'top5', positive: boolean, id?: string, requestId?: string)", "async function feedback(kind: 'property' | 'top5', positive: boolean, id?: string, requestId?: string, reasonCode?: string)")
content = content.replace("candidate_ids: id ? [id] : [] }", "candidate_ids: id ? [id] : [], reason_code: reasonCode || null }")
content = content.replace("onFeedback={positive => feedback('property', positive, row.property.property_id)}", "onFeedback={(positive, reason) => feedback('property', positive, row.property.property_id, undefined, reason)}")
content = content.replace("onFeedback: (positive: boolean) => void", "onFeedback: (positive: boolean, reason?: string) => void")
content = content.replace("const ref = useRef<HTMLElement | null>(null), p = row.property", "const [reason, setReason] = useState('');\n  const ref = useRef<HTMLElement | null>(null), p = row.property")
content = content.replace('onClick={() => onFeedback(true)}', 'onClick={() => onFeedback(true, reason)}').replace('onClick={() => onFeedback(false)}', 'onClick={() => onFeedback(false, reason)}')
content = content.replace('<div className="card-actions"><button onClick={onDetails}>', '<div className="card-actions">{requestId && <select className="feedback-reason" aria-label="دلیل اختیاری بازخورد" value={reason} onChange={e => setReason(e.target.value)}><option value="">دلیل بازخورد (اختیاری)</option><option value="budget">بودجه</option><option value="commute">رفت‌وآمد</option><option value="amenities">امکانات</option><option value="location">موقعیت</option><option value="missing_evidence">اطلاعات ناکافی</option><option value="other">دلیل دیگر</option></select>}<button onClick={onDetails}>')
path.write_text(content, encoding='utf-8')
path = root / 'frontend/src/phase2.css'
with path.open('a', encoding='utf-8') as stream:
    stream.write('\n.feedback-reason{font-size:10px;padding:4px 7px;width:auto;max-width:170px}\n')
path = root / 'frontend/e2e/phase2.spec.ts'
content = path.read_text(encoding='utf-8').replace("toContainText('بازیابی معنایی انجام شد')", "toContainText('کاندیدای معنایی بازیابی شد')")
path.write_text(content, encoding='utf-8')
path = root / 'frontend/playwright.config.ts'
content = path.read_text(encoding='utf-8').replace("testMatch:'phase2.spec.ts'", "testMatch:'phase2*.spec.ts'")
path.write_text(content, encoding='utf-8')
