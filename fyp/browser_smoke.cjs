// Run against the private local ReValue server with Playwright and Chromium.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.REVALUE_SMOKE_URL || 'http://127.0.0.1:8765');
    await page.getByRole('button', { name: 'Value Another Phone' }).click();
    await page.getByPlaceholder('Search brand or model').fill('iPhone 13 Pro');
    await page.locator('.catalogue-result').filter({ hasText: 'Apple iPhone 13 Pro' }).first().click();
    await page.getByPlaceholder('Manual storage, e.g. 256GB').fill('256GB');
    await page.getByRole('button', { name: 'Confirm Storage' }).click();
    const encoded = await page.evaluate(() => document.createElement('canvas').toDataURL().split(',')[1]);
    const photo = { name: 'software-fixture.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
    for (const [i, view] of ['front', 'back', 'camera', 'left_side', 'right_side'].entries()) {
      await page.locator('#finalInput-' + view).setInputFiles(photo);
      await page.waitForFunction(n => document.querySelectorAll('.final-slot.ready').length === n, i + 1);
    }
    let review = true, valuations = 0;
    await page.route('**/analyze-exterior', route => route.fulfill({
      json: { status: 'ok', assessment_basis: review ? 'review_required' : 'provisional',
        grade: { exterior_grade: 'A', note: 'Software fixture' }, detections: [], merged_damage: [] },
    }));
    await page.route('**/live-valuation', route => {
      valuations++;
      return route.fulfill({ json: { status: 'insufficient_market_evidence' } });
    });
    const analyze = page.getByRole('button', { name: 'Analyze Exterior' });
    const report = page.getByRole('button', { name: 'View Exterior Report' });
    await analyze.click();
    await page.getByText('Review required. Software fixture').waitFor();
    assert.equal(await report.count(), 0);
    assert.equal(valuations, 0);

    review = false;
    await analyze.click();
    await report.click();
    await page.locator('#reportId').filter({ hasText: /^RVA-LIVE-/ }).waitFor();
    assert.match(await page.locator('#estimatedValue').textContent(), /Insufficient market evidence/);
    const previousId = await page.locator('#reportId').textContent();
    await page.evaluate(() => showPage('scan'));
    await page.locator('#finalInput-back').setInputFiles(photo);
    await report.waitFor({ state: 'detached' });
    await analyze.click();
    await report.click();
    assert.notEqual(await page.locator('#reportId').textContent(), previousId);
    assert.equal(valuations, 2);
    assert.deepEqual(errors, []);
    console.log('Browser smoke passed: review blocks pricing, no unsupported estimate is shown, and reruns get a new report ID.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
