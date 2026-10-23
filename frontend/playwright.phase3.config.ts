import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './e2e', testMatch: ['phase3*.spec.ts', 'phase2.spec.ts'], grep: /restricted internal|internal page|normal consumer|advanced confirmation/, timeout: 30000,
  reporter: [['list'], ['json', { outputFile: '../docs/phase-3-browser-report.json' }]],
  webServer: { command: '.\\.venv\\Scripts\\python.exe scripts/serve_phase3_browser.py', cwd: '..', url: 'http://127.0.0.1:8001/api/health', reuseExistingServer: false, timeout: 60000 },
  fullyParallel: false, use: { baseURL: 'http://127.0.0.1:8001', browserName: 'chromium',
    channel: 'msedge', headless: true, viewport: { width: 1440, height: 1000 } } });
