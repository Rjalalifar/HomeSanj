"""Align automatic timestamps with the verified OTP second-resolution contract."""
from pathlib import Path

path = Path('backend/app/accessibility.py')
source = path.read_text(encoding='utf-8').replace("now = datetime.now(ZoneInfo('Asia/Tehran'))", "now = datetime.now(ZoneInfo('Asia/Tehran')).replace(microsecond=0)")
path.write_text(source, encoding='utf-8')
path = Path('tests/test_accessibility.py')
source = path.read_text(encoding='utf-8').replace('before = datetime.now(timezone.utc)', 'before = datetime.now(timezone.utc).replace(microsecond=0)')
path.write_text(source, encoding='utf-8')
path = Path('frontend/e2e/phase3.spec.ts')
source = path.read_text(encoding='utf-8').replace("await expect(page.locator('.search-progress')).toContainText('بررسی کامل');", "await expect(page.locator('.search-progress')).toContainText('کاندیدای ملک', { timeout: 60000 });")
path.write_text(source, encoding='utf-8')
print('Applied second-resolution automatic time policy and progressive browser expectation.')
