"""Apply the final smoke-accounting corrections and reconcile delivery documentation."""
from pathlib import Path


def replace(path, old, new):
    target = Path(path)
    source = target.read_text(encoding='utf-8-sig')
    if new in source:
        return
    if old not in source:
        raise RuntimeError(f'Expected source not found in {path}')
    target.write_text(source.replace(old, new, 1), encoding='utf-8')


replace('backend/app/llm.py', '        for attempt in range(self.retries + 1):',
    '        retries = 0 if smoke else self.retries\n        for attempt in range(retries + 1):')
replace('backend/app/llm.py', 'if not transient or attempt == self.retries:', 'if not transient or attempt == retries:')
replace('backend/app/llm.py', 'async def smoke(self):', 'async def smoke(self, *, max_requests=1):')
replace('backend/app/llm.py', '            missing = [model for model in desired if model not in available]',
    """            if len(desired) > max(0, max_requests):
                return {'status': 'budget_stopped', 'reason': 'Enabled distinct models exceed the explicit smoke request limit',
                        'required_requests': len(desired), 'max_requests': max(0, max_requests), 'paid_requests': 0}
            missing = [model for model in desired if model not in available]""")
replace('backend/app/llm.py', "'checked_at': utcnow(), 'max_output_tokens_per_call': min(self.max_tokens, 64),",
    "'checked_at': utcnow(), 'max_output_tokens_per_call': 64, 'paid_requests': len(verified),")
replace('backend/app/cli.py', 'Schema migrations 1-3 applied or already current; SQLite indexes, FTS5, sessions, and feedback ready.',
    'Schema migrations 1-4 applied or already current; search, feedback and evaluation tables ready.')
replace('backend/app/cli.py', '            provider.daily_limit = min(provider.daily_limit, max(0, args.max_requests))\n', '')
replace('backend/app/cli.py', 'report = asyncio.run(provider.smoke())', 'report = asyncio.run(provider.smoke(max_requests=max(0, args.max_requests)))')
replace('backend/app/evaluation_dashboard.py', "        subset = [c for c in calls if c.role == role]\n",
    """        subset = [c for c in calls if c.role == role]
        known_tokens = [(c.usage or {}).get('total_tokens') for c in subset]
        known_tokens = [value for value in known_tokens if type(value) is int and value >= 0]
""")
replace('backend/app/evaluation_dashboard.py',
    "'observed_total_tokens': sum(c.usage.get('total_tokens', 0) for c in subset if c.usage) if any(c.usage for c in subset) else None,",
    """'observed_total_tokens': sum(known_tokens) if subset and len(known_tokens) == len(subset) else None,
            'known_token_total': sum(known_tokens) if known_tokens else None,
            'token_usage_available_calls': len(known_tokens), 'token_usage_missing_calls': len(subset) - len(known_tokens),""")
replace('scripts/verify_phase3_delivery.py',
    "'prerequisite': 'Configure backend key, enable only the desired role and set its request/token/cost budgets first'",
    "'prerequisite': ('Backend key is present; enable only the desired role and set its request/token/cost budgets first' if provider.key else 'Configure a backend key, enable only the desired role and set its request/token/cost budgets first')")
replace('docs/handoff-phase-3.md',
    'AvalAI live judge/improvement and explanation smoke: **NOT RUN** without configured account access/activation; no paid calls were made.',
    'AvalAI live judge/improvement and explanation smoke: **NOT RUN** because all four roles are explicitly disabled. A backend key is present; account-visible model access remains unverified. No paid calls were made.')
replace('docs/phase-3-implementation-plan.md', '- [ ]', '- [x]')
plan = Path('docs/phase-3-implementation-plan.md')
plan.write_text(plan.read_text(encoding='utf-8').replace('- [ ]', '- [x]'), encoding='utf-8')
readme = Path('README.md')
content = readme.read_text(encoding='utf-8-sig')
historical = 'وضعیت تحویل: ۵۶۵۵ آگهی؛'
if historical in content:
    content = content[:content.index(historical)]
if '## تحویل مرحلهٔ سوم' not in content:
    content += """## تحویل مرحلهٔ سوم

پیاده‌سازی ارزیابی، بازبینی داخلی، دادهٔ برچسب‌گذاری نسخه‌دار، worker آفلاین و مقایسه/rollback کنترل‌شده تکمیل شده است. پنل در `/internal` از همان برنامه اجرا می‌شود؛ دسترسی آن نیازمند `REVIEW_API_TOKEN` یا توکن مستقل هر بازبین در تنظیمات backend است. کامنت‌های کد انگلیسی‌اند.

```powershell
.\\.venv\\Scripts\\python.exe -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

[راهنمای تحویل مرحلهٔ سوم](docs/handoff-phase-3.md)، [ماتریس پذیرش](docs/phase-3-acceptance-matrix.md) و [نتایج واقعی بررسی‌ها](docs/phase-3-verification-report.json) مرجع وضعیت فعلی‌اند. راهنمای مراحل پیشین: [مرحلهٔ اول](docs/handoff-phase-1.md) و [مرحلهٔ دوم](docs/handoff-phase-2.md).

۵۶۵۵ آگهی نمایشی ذخیره شده‌اند؛ اتصال واقعی OTP در `/otp/transmodel/v3` با پنج مسیر و سلامت ایندکس Qdrant بررسی شده‌اند. کلید backend مربوط به AvalAI موجود است، اما همهٔ نقش‌های مدل غیرفعال‌اند و آزمون پولی اجرا نشده است. شمارش تعویض و مبنای schedule همچنان تابع شواهد همان پاسخ مسیریابی‌اند.

چرخهٔ تغییر وزن رتبه‌بندی و rollback در محدودهٔ آزمایشی بررسی شده است. تعداد برچسب مستقل انسانی صفر است؛ بهبود واقعی کیفیت، QS کاربران واقعی و انتشار رتبه‌بندی جدید در محیط اصلی ادعا یا انجام نشده‌اند. دادهٔ خروجی بازبینی مرورگر با منشأ `test_fixture` نگه‌داری می‌شود.
"""
readme.write_text(content, encoding='utf-8')
print('Updated smoke accounting, unknown usage semantics and delivery documentation.')
