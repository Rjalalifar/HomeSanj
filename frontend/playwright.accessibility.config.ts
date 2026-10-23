import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', testMatch: ['accessibility*.spec.ts', 'phase3.spec.ts', 'phase2.spec.ts'],
  grep: /automatic accessibility|regular destination|advanced confirmation|late search|restricted internal|internal page|normal consumer|mobile filters/,
  timeout: 90000, fullyParallel: false, workers: 1,
  reporter: [['list'], ['json', { outputFile: '../docs/accessibility-browser-report.json' }]],
  webServer: { command: '.\\.venv\\Scripts\\python.exe scripts/serve_accessibility_browser.py', cwd: '..',
    url: 'http://127.0.0.1:8001/api/health', reuseExistingServer: false, timeout: 60000 },
  use: { baseURL: 'http://127.0.0.1:8001', browserName: 'chromium', channel: 'msedge', headless: true,
    viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure' },
});
