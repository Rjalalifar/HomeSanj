"""Let Playwright own the isolated backend lifecycle so interrupted sessions cannot stale it."""
from pathlib import Path
p = Path('frontend/playwright.phase3.config.ts')
s = p.read_text(encoding='utf-8')
s = s.replace("  fullyParallel: false, use:", "  webServer: { command: '.\\\\.venv\\\\Scripts\\\\python.exe scripts/serve_phase3_browser.py', cwd: '..', url: 'http://127.0.0.1:8001/api/health', reuseExistingServer: false, timeout: 60000 },\n  fullyParallel: false, use:")
p.write_text(s, encoding='utf-8')
