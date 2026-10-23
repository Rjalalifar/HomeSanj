import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const config = JSON.parse(readFileSync('../runtime/phase3-browser-config.json', 'utf8'));

test('restricted internal review remains blind, leased and provenance-aware', async ({ page, request }) => {
  expect((await request.get('/api/internal/dashboard')).status()).toBe(403);
  expect((await request.get('/api/internal/reviews')).status()).toBe(403);
  await page.goto('/internal');
  await expect(page.locator('[data-kpi]')).toHaveCount(0);
  await page.getByLabel('کلید دسترسی').fill(config.token);
  await page.getByRole('button', { name: 'ورود به پنل' }).click();
  await expect(page.locator('[data-kpi]')).toHaveCount(6);
  await expect(page.getByRole('region', { name: 'شاخص‌های اصلی جست‌وجوی عادی', exact: true }).locator('[data-kpi]')).toHaveCount(3);
  await expect(page.getByRole('region', { name: 'شاخص‌های اصلی جست‌وجوی پیشرفته', exact: true }).locator('[data-kpi]')).toHaveCount(3);
  const initialDashboard = await (await request.get('/api/internal/dashboard', { headers: { 'x-review-token': config.token } })).json();
  for (const id of ['normal-qs_at_5', 'normal-human_ndcg_at_5', 'advanced-qs_at_5', 'advanced-human_ndcg_at_5', 'advanced-gemini_groundedness']) {
    const [mode, key] = id.split('-');
    const metric = initialDashboard.primary_kpis[mode][key];
    expect(metric.status).toBe('insufficient_data');
    expect(metric.value).toBeNull();
    expect(metric.reason).toBeTruthy();
    await expect(page.locator(`[data-kpi="${id}"] strong`)).toHaveText('insufficient_data');
    await expect(page.locator(`[data-kpi="${id}"] .review-kpi-reason`)).toHaveText(metric.reason);
  }
  await page.getByText('نتایج ارزیابی و سلامت سرویس‌ها', { exact: true }).click();
  await expect(page.getByText('هنوز قابل محاسبه نیست', { exact: true })).toBeVisible();
  await expect(page.getByText('otp', { exact: true })).toBeVisible();
  await expect(page.getByText('retrieval', { exact: true })).toBeVisible();
  await page.locator('.review-queue button').first().click();
  await expect(page.locator('.review-badge')).toContainText('رأی اولیهٔ مستقل');
  await page.locator('.review-facts input').first().check();
  await page.getByLabel('درجهٔ تناسب', { exact: true }).selectOption('2');
  await page.screenshot({ path: '../docs/screenshots/phase-3-review-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'ثبت بازبینی', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('بازبینی ثبت شد');
  const dashboard = await (await request.get('/api/internal/dashboard', { headers: { 'x-review-token': config.token } })).json();
  expect(dashboard.review.independent_real_graded).toBe(0);
  await page.getByRole('button', { name: 'خروج', exact: true }).click();
  await expect(page.locator('[data-kpi]')).toHaveCount(0);
  await expect(page.getByLabel('کلید دسترسی')).toHaveValue('');
  expect(await page.evaluate(() => Object.keys(localStorage).filter(k => /token|review/i.test(k)))).toHaveLength(0);
});

test('internal page works on mobile without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/internal');
  await page.getByLabel('کلید دسترسی').fill(config.token);
  await page.getByRole('button', { name: 'ورود به پنل' }).click();
  await expect(page.locator('.review-queue button').first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../docs/screenshots/phase-3-review-mobile.png', fullPage: true });
});

test('normal consumer search stays independent of internal evaluation services', async ({ page }) => {
  const forbidden: string[] = [];
  page.on('request', req => { if (/\/api\/(advanced|internal)|:6333|avalai/.test(req.url())) forbidden.push(req.url()); });
  await page.route('**/tile.openstreetmap.org/**', route => route.abort());
  await page.goto('/');
  await expect(page.locator('.property-card').first()).toBeVisible();
  await page.getByLabel('مرتب‌سازی', { exact: true }).selectOption('rent_asc');
  await page.getByRole('button', { name: 'جست‌وجوی خانه', exact: true }).click();
  await expect(page.locator('.search-progress')).toContainText('کاندیدای ملک', { timeout: 60000 });
  expect(forbidden).toEqual([]);
});
