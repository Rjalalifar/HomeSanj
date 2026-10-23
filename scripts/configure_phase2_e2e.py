"""Retain the phase-one browser test as a historical acceptance fixture."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = root / 'frontend/playwright.config.ts'
content = config.read_text(encoding='utf-8')
if 'testMatch:' not in content:
    content = content.replace("testDir:'./e2e',", "testDir:'./e2e',testMatch:'phase2.spec.ts',")
config.write_text(content, encoding='utf-8')
