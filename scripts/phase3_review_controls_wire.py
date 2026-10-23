"""Expose assignment, priority and explicit evidence-linked issues on the internal surface."""
from pathlib import Path
p = Path('backend/app/review_workflow.py')
s = p.read_text(encoding='utf-8')
s = s.replace("'lease_until': workflow.get('lease_until', 0), 'initial_blind'", "'lease_until': workflow.get('lease_until', 0), 'assigned_to': workflow.get('assigned_to'), 'priority': workflow.get('priority', 'critical' if 'critical' in sample.reasons else 'normal'), 'issue_history': workflow.get('issue_history', []), 'initial_blind'")
s = s.replace('issue=None, version=None, limit=50):', 'issue=None, version=None, priority=None, limit=50):')
s = s.replace("            if version and row.sampler_version != version:\n                continue", "            if version and row.sampler_version != version:\n                continue\n            if priority and (row.workflow or {}).get('priority', 'critical' if 'critical' in row.reasons else 'normal') != priority:\n                continue")
s = s.replace("        if w.get('revision', 0) != revision:", "        if w.get('assigned_to') and w['assigned_to'] != reviewer:\n            raise HTTPException(409, 'Sample is assigned to another reviewer')\n        if w.get('revision', 0) != revision:")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/phase3_api.py')
s = p.read_text(encoding='utf-8').replace('issue: str | None = None, version: str | None = None):', 'issue: str | None = None, version: str | None = None, priority: str | None = None):')
s = s.replace('origin=origin, issue=issue, version=version)', 'origin=origin, issue=issue, version=version, priority=priority)')
classes = '''

class AssignmentInput(StrictModel):
    reviewer_id: str | None = Field(default=None, max_length=80)
    revision: int = Field(ge=0)


class IssueInput(StrictModel):
    issue: str = Field(max_length=80)
    evidence_refs: list[str] = Field(min_length=1, max_length=40)
'''
if 'class AssignmentInput' not in s:
    s = s.replace('\ndef install_phase3(', classes + '\ndef install_phase3(')
routes = '''    @app.get('/api/internal/reviewers')
    def reviewers(request: Request):
        import hashlib
        import json
        import os
        current = reviewer_identity(request)
        configured = json.loads(os.getenv('REVIEWER_TOKENS_JSON', '{}'))
        choices = [{'reviewer_id': 'reviewer_' + hashlib.sha256(name.encode()).hexdigest()[:16], 'label': name}
                   for name, token in configured.items() if isinstance(token, str) and len(token) >= 16]
        if not any(c['reviewer_id'] == current for c in choices):
            choices.append({'reviewer_id': current, 'label': 'Current reviewer'})
        return {'current': current, 'reviewers': choices}

    @app.post('/api/internal/reviews/{sample_id}/assign')
    def assign_sample(sample_id: str, body: AssignmentInput, request: Request):
        from .review_issues import assign
        identities = reviewers(request)
        if body.reviewer_id and body.reviewer_id not in {r['reviewer_id'] for r in identities['reviewers']}:
            raise HTTPException(422, 'Unknown configured reviewer')
        return assign(db, sample_id, identities['current'], body.reviewer_id, body.revision)

    @app.post('/api/internal/reviews/{sample_id}/issues')
    def issue(sample_id: str, body: IssueInput, request: Request):
        from .review_issues import add_issue
        try:
            return add_issue(db, sample_id, body.issue, body.evidence_refs, reviewer_identity(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post('/api/internal/reviews/refresh-issues')
    def refresh_issues(request: Request):
        from .review_issues import refresh_disagreements
        reviewer_identity(request)
        return refresh_disagreements(db)

'''
if "@app.get('/api/internal/reviewers')" not in s:
    s = s.replace('    return worker\n', routes + '    return worker\n')
p.write_text(s, encoding='utf-8')
p = Path('frontend/src/InternalReview.tsx')
s = p.read_text(encoding='utf-8').replace("  const [version, setVersion] = useState('');", "  const [version, setVersion] = useState('');\n  const [priority, setPriority] = useState('');")
s = s.replace("    if (version) params.set('version', version);", "    if (version) params.set('version', version);\n    if (priority) params.set('priority', priority);")
s = s.replace("        <label>نسخهٔ نمونه‌گیری", "        <label>اولویت<select value={priority} onChange={e => setPriority(e.target.value)}><option value=\"\">همه</option><option value=\"critical\">بحرانی</option><option value=\"high\">بالا</option><option value=\"normal\">عادی</option></select></label>\n        <label>نسخهٔ نمونه‌گیری")
p.write_text(s, encoding='utf-8')
