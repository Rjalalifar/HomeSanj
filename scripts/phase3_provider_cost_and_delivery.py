"""Reserve optional offline cost caps and capture delivery ranking before future changes."""
from pathlib import Path
p = Path('backend/app/llm.py')
s = p.read_text(encoding='utf-8')
needle = "            call_id = new_id('llm')\n            session.add(ProviderCall"
replacement = """            reservation = None
            if role in ('judge', 'improvement'):
                prefix = ROLE_ENV[role]
                ceiling = os.getenv(prefix + '_DAILY_MAX_COST_USD', '')
                rate = os.getenv(prefix + '_UPPER_COST_PER_MILLION_TOKENS_USD', '')
                if ceiling and not rate:
                    raise ProviderError('cost_budget_unverifiable')
                if rate:
                    rate = float(rate)
                    if not 0 < rate < 1000000:
                        raise ProviderError('cost_budget_unverifiable')
                    reservation = reserved * rate / 1000000
                    prior_calls = session.scalars(select(ProviderCall).where(ProviderCall.day == day, ProviderCall.role == role))
                    prior_cost = sum((c.usage or {}).get('reserved_cost_usd') or 0 for c in prior_calls)
                    if ceiling and prior_cost + reservation > float(ceiling):
                        raise ProviderError('budget_stopped')
            call_id = new_id('llm')
            session.add(ProviderCall"""
if 'cost_budget_unverifiable' not in s:
    s = s.replace(needle, replacement)
    s = s.replace('created_at=utcnow(), usage=None)', "created_at=utcnow(), usage={'reserved_cost_usd': reservation, 'measured_cost_usd': None} if role in ('judge', 'improvement') else None)")
    s = s.replace('                row.usage = usage', '                row.usage = (row.usage or {}) | usage')
p.write_text(s, encoding='utf-8')
p = Path('backend/app/offline_evaluation.py')
s = p.read_text(encoding='utf-8').replace("('judge', 'improvement', 'acquisition', 'export')", "('judge', 'pairwise', 'improvement', 'acquisition', 'export')")
s = s.replace("            elif job.kind == 'improvement':", "            elif job.kind == 'pairwise':\n                from .judge_pairwise import evaluate_pair\n                result = await evaluate_pair(self.db, provider=self.provider, **job.payload)\n            elif job.kind == 'improvement':")
s = s.replace("('disabled', 'smoke_required', 'budget_stopped')", "('disabled', 'smoke_required', 'budget_stopped', 'cost_budget_unverifiable')")
p.write_text(s, encoding='utf-8')
p = Path('backend/app/integration.py')
s = p.read_text(encoding='utf-8')
if 'capture_delivery(self.db' not in s:
    s = s.replace("            record_system_event(self.db, owner, request_id, 'search_completed')", "            record_system_event(self.db, owner, request_id, 'search_completed')\n            from .evaluation_replay import capture_delivery\n            capture_delivery(self.db, snapshot)")
p.write_text(s, encoding='utf-8')
