"""Keep offline provider roles explicitly opt-in with independent reservation ceilings."""
from pathlib import Path
p = Path('backend/app/llm.py')
s = p.read_text(encoding='utf-8')
s = s.replace("        return self.enabled\n\n    def info", "        if role == 'improvement':\n            return os.getenv('AI_IMPROVEMENT_ENABLED', 'false').lower() == 'true'\n        return False\n\n    def info")
old = "            if role == 'judge':\n                judge_count = session.scalar(select(func.count()).select_from(ProviderCall).where(ProviderCall.day == day, ProviderCall.role == 'judge'))\n                if judge_count >= int(os.getenv('JUDGE_DAILY_MAX_REQUESTS', '100')):\n                    raise ProviderError('budget_stopped')"
new = """            if role in ('judge', 'improvement'):
                prefix = ROLE_ENV[role]
                role_count, role_tokens = session.execute(select(func.count(), func.coalesce(func.sum(ProviderCall.reserved_tokens), 0)).where(ProviderCall.day == day, ProviderCall.role == role)).one()
                if role_count >= int(os.getenv(prefix + '_DAILY_MAX_REQUESTS', '100')) or role_tokens + reserved > int(os.getenv(prefix + '_DAILY_MAX_RESERVED_TOKENS', '30000')):
                    raise ProviderError('budget_stopped')"""
s = s.replace(old, new)
s = s.replace("        output_cap = min(self.max_tokens, 64) if smoke else self.max_tokens", "        role_cap = min(2048, max(1, int(os.getenv(ROLE_ENV[role] + '_MAX_OUTPUT_TOKENS', str(self.max_tokens)))))\n        output_cap = min(role_cap, 64) if smoke else role_cap")
p.write_text(s, encoding='utf-8')
