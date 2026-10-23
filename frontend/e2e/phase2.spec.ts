import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/tile.openstreetmap.org/**', route => route.abort());
});

test('normal filtering stays local; snapshots, comparison and feedback remain scoped', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const submissions: string[] = [];
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/(advanced\/)?searches$/.test(request.url())) submissions.push(request.url()); });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'خانهٔ مناسب، با حساب رفت‌وآمد' })).toBeVisible();
  await expect(page.locator('.property-card').first()).toBeVisible();
  await page.locator('.boundary-options').first().locator('input').first().check();
  await expect(page.locator('.results-toolbar h2')).toHaveText('۱۵ گزینه');
  await page.getByLabel('مرتب‌سازی', { exact: true }).selectOption('rent_asc');
  await expect(page.locator('.property-card')).toHaveCount(15);
  expect(submissions).toHaveLength(0);
  await page.getByRole('button', { name: 'جست‌وجوی خانه', exact: true }).click();
  await expect(page.locator('.search-progress')).toContainText('بررسی کامل');
  expect(submissions).toHaveLength(1);
  for (let index = 0; index < 3; index++) await page.locator('.property-card').nth(index).getByRole('button', { name: 'افزودن به مقایسه' }).click();
  await page.locator('.property-card').nth(3).getByRole('button', { name: 'افزودن به مقایسه' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'حداکثر سه' })).toBeVisible();
  await page.getByRole('button', { name: 'نمایش مقایسه', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('نامعلوم');
  await expect(page.locator('dialog thead th')).toHaveCount(4);
  await page.getByRole('button', { name: 'بستن پنجره' }).click();
  await page.locator('.property-card').first().getByRole('button', { name: /^مناسب است:/ }).click();
  await expect(page.getByRole('status').filter({ hasText: 'نظر شما ثبت شد' })).toBeVisible();
  await page.getByRole('button', { name: 'هیچ‌کدام مناسب نبود' }).click();
  await page.getByLabel('سقف اجارهٔ ماهانه (تومان)', { exact: true }).fill('۱۵۰۰۰۰۰۰');
  await expect(page.locator('.comparison-bar')).toContainText('شرایط قبلی');
  await expect(page.locator('.results')).toContainText('شرایط تغییر کرده');
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({ path: 'test-results/phase-2-desktop.png', fullPage: false });
  expect(errors).toEqual([]);
});

test('advanced confirmation uses actual semantic retrieval and preserves hard conditions', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.property-card').first()).toBeVisible();
  await page.locator('.boundary-options').first().locator('input').first().check();
  await page.getByRole('button', { name: 'جست‌وجوی پیشرفته', exact: true }).click();
  await page.getByLabel('خانه‌ای که می‌خواهید را توضیح دهید').fill('اجاره تا ۱۵ میلیون تومان');
  await expect(page.getByRole('button', { name: 'اجرای جست‌وجوی پیشرفته', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'بررسی متن و پیشنهاد شرط‌ها' }).click();
  await expect(page.getByLabel('شرط‌های پیشنهادی')).toContainText('سقف اجاره');
  await page.getByRole('button', { name: 'تأیید شرط‌های پیشنهادی' }).click();
  await expect(page.getByLabel('سقف اجارهٔ ماهانه (تومان)', { exact: true })).toHaveValue('15000000');
  const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/api/advanced/searches'));
  await page.getByRole('button', { name: 'اجرای جست‌وجوی پیشرفته', exact: true }).click();
  const submitted = await (await response).json();
  expect(submitted.state.property.max_monthly_rent_toman).toBe(15000000);
  await expect(page.getByRole('button', { name: 'چرا این گزینه‌ها پیشنهاد شدند؟' })).toBeEnabled({ timeout: 30000 });
  await expect(page.locator('.search-progress')).toContainText('کاندیدای معنایی بازیابی شد');
  await page.getByRole('button', { name: 'چرا این گزینه‌ها پیشنهاد شدند؟' }).click();
  await expect(page.locator('.explanation')).toContainText('دلیل پیشنهاد');
  await page.getByRole('button', { name: 'جست‌وجوی معمولی', exact: true }).click();
  await expect(page.getByLabel('سقف اجارهٔ ماهانه (تومان)', { exact: true })).toHaveValue('15000000');
  await expect(page.locator('.boundary-options').first().locator('input:checked')).toHaveCount(1);
});

test('mobile filters and map survive tile failure without horizontal overflow', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.property-card').first()).toBeVisible();
  await page.getByRole('button', { name: /^فیلترها/ }).click();
  await page.getByLabel('حداقل اتاق', { exact: true }).fill('۲');
  await page.getByRole('button', { name: 'بستن فیلترها' }).click();
  await page.getByRole('button', { name: 'نقشه', exact: true }).click();
  await expect(page.locator('.leaflet-container')).toBeVisible();
  await page.getByRole('button', { name: 'فهرست', exact: true }).click();
  await expect(page.locator('.property-card').first()).toContainText('آگهی نمایشی');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({ path: 'test-results/phase-2-mobile.png', fullPage: false });
  expect(errors).toEqual([]);
});

test('destination is explicit and mode changes preserve confirmed travel state', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.property-card').first()).toBeVisible();
  await page.getByRole('button', { name: 'انتخاب مقصد روی نقشه', exact: true }).click();
  await page.locator('.leaflet-container').click({ position: { x: 190, y: 180 } });
  await expect(page.locator('.destination-editor')).toContainText('نقطهٔ پیشنهادی');
  await page.getByLabel('تاریخ سفر (میلادی)').fill('2026-10-21');
  await page.getByLabel('ساعت تهران').fill('08:30');
  await page.getByRole('button', { name: 'تأیید مقصد و زمان', exact: true }).click();
  await expect(page.locator('.destination-editor')).toContainText('مقصد تأییدشده');
  await page.getByLabel('سقف کل پیاده‌روی (دقیقه)').fill('۲۰');
  await page.getByRole('button', { name: 'جست‌وجوی پیشرفته', exact: true }).click();
  await expect(page.locator('.destination-editor')).toContainText('مقصد تأییدشده');
  await expect(page.getByLabel('سقف کل پیاده‌روی (دقیقه)')).toHaveValue('20');
  await page.getByRole('button', { name: 'پاک‌کردن فیلترها', exact: true }).click();
  await expect(page.getByLabel('سقف کل پیاده‌روی (دقیقه)')).toHaveValue('');
  await expect(page.locator('.destination-editor')).toContainText('مقصد تأییدشده');
});

test('a late search response cannot overwrite a newer filter state', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.property-card').first()).toBeVisible();
  await page.locator('.boundary-options').first().locator('input').first().check();
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  let arrived: () => void = () => {};
  const ready = new Promise<void>(resolve => { arrived = resolve; });
  await page.route('**/api/searches', async route => {
    const response = await route.fetch();
    arrived();
    await gate;
    await route.fulfill({ response });
  });
  await page.getByRole('button', { name: 'جست‌وجوی خانه', exact: true }).click();
  await ready;
  await page.getByLabel('سقف اجارهٔ ماهانه (تومان)', { exact: true }).fill('1');
  release();
  await expect(page.locator('.results-toolbar h2')).toHaveText('۰ گزینه');
  await expect(page.locator('.results-toolbar')).toContainText('پیش‌نمایش');
  await expect(page.locator('.search-progress')).toHaveCount(0);
});
