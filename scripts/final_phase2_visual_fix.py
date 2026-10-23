"""Correct contrast and target the travel selector independently of label normalization."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'frontend/src/phase2.css'
with path.open('a', encoding='utf-8') as stream:
    stream.write('\n.comparison-bar button{color:#242b38}.comparison-bar button:hover{color:#9b2727}\n')
path = root / 'frontend/e2e/phase2-live-otp.spec.ts'
content = path.read_text(encoding='utf-8').replace("page.getByLabel('زمان‌بندی', { exact: true })", "page.locator('.destination-editor select').first()")
path.write_text(content, encoding='utf-8')
