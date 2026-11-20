// Run against the private local ReValue server with Playwright and Chromium.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseUrl = process.env.REVALUE_SMOKE_URL || 'http://127.0.0.1:8765';

async function selectPhone(page, mode) {
  await page.goto(baseUrl);
  await page.keyboard.press('Tab');
  assert.equal(await page.getByRole('link', { name: 'Skip to content' }).evaluate(node => document.activeElement === node), true);
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#scanPage').evaluate(node => document.activeElement === node), true);
  await page.getByRole('button', { name: 'Start Phone Assessment' }).click();
  await page.getByRole('button', { name: mode }).click();
  const brand = page.getByRole('button', { name: 'Apple', exact: true });
  await brand.click();
  assert.equal(await brand.getAttribute('aria-pressed'), 'true');
  await page.getByLabel('Brand or model').fill('zzzz-nonexistent-zzzz');
  assert.equal(await brand.getAttribute('aria-pressed'), 'false');
  await page.getByText('No matching models.', { exact: false }).waitFor();
  await page.getByPlaceholder('Search brand or model').fill('iPhone 13 Pro');
  await page.locator('.catalogue-result').filter({ hasText: 'Apple iPhone 13 Pro' }).first().click();
  await page.getByRole('button', { name: 'Confirm Storage', exact: true }).click();
  await page.getByRole('alert').getByText('Select or enter a storage capacity.').waitFor();
  await page.getByPlaceholder('Manual storage, e.g. 256GB').fill('256GB');
  await page.getByRole('button', { name: 'Confirm Storage', exact: true }).click();
}

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(45000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await selectPhone(page, 'Value Another Phone');
    assert.equal(await page.getByLabel('Send photos to Gemini for optional verification').isChecked(), false);
    assert.equal(await page.getByRole('button', { name: 'Analyze Exterior' }).isEnabled(), false);
    await page.locator('#finalInput-front').setInputFiles({ name: 'bad.png', mimeType: 'image/png', buffer: Buffer.from('invalid') });
    await page.getByText('This photo could not be read.', { exact: false }).waitFor();
    const fixturePhoto = async index => {
      const encoded = await page.evaluate(n => {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        context.fillStyle = 'rgb(252,252,' + (240 + n) + ')';
        context.fillRect(0, 0, canvas.width, canvas.height);
        return canvas.toDataURL().split(',')[1];
      }, index);
      return { name: 'software-fixture.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
    };
    for (const [i, view] of ['front', 'back', 'camera', 'left_side', 'right_side'].entries()) {
      if (i === 1) {
        await page.locator('#finalInput-back').setInputFiles(await fixturePhoto(0));
        await page.getByText('Use a different photo for each view.').waitFor();
      }
      await page.locator('#finalInput-' + view).setInputFiles(await fixturePhoto(i));
      await page.waitForFunction(n => document.querySelectorAll('.final-slot.ready').length === n, i + 1);
    }
    const scanUrl = '**/analyze-exterior';
    const analyze = page.getByRole('button', { name: 'Analyze Exterior' });
    const report = page.getByRole('button', { name: 'View Exterior Report' });
    const valuations = [];
    page.on('request', request => {
      if (request.url().endsWith('/live-valuation')) valuations.push(request.postDataJSON());
    });
    await page.route(scanUrl, route => route.fulfill({ status: 503, json: { error: 'Detector unavailable' } }));
    await analyze.click();
    await page.getByRole('alert').getByText('Analysis did not complete.', { exact: false }).waitFor();
    assert.equal(await page.locator('.final-slot.ready').count(), 5);
    assert.equal(await report.count(), 0);
    await page.unroute(scanUrl);
    await page.route(scanUrl, async route => {
      await new Promise(resolve => setTimeout(resolve, 350));
      await route.fulfill({ json: { status: 'ok', assessment_basis: 'review_required', yolo_model: 'revalue_exterior_yolo11n_v0.2',
        grade: { exterior_grade: 'A', note: 'Software fixture' },
        detections: [{ raw_class: 'scratch', view: 'front', confidence: .87, bounding_box_xyxy: [10, 10, 80, 50], requires_gemini_resolution: true }], merged_damage: [] } });
    });
    await analyze.click();
    await page.getByText('Analyzing photos for visible damage…').waitFor();
    await page.getByRole('heading', { name: 'Review required' }).waitFor();
    await page.getByText('scratch · Front · 87.0% · Needs review').waitFor();
    await page.locator('.damage-tag').filter({ hasText: '87.0%' }).waitFor();
    assert.equal(await report.count(), 0);
    assert.equal(valuations.length, 0);

    await page.unroute(scanUrl);
    await analyze.click();
    await report.click();
    await page.locator('#reportId').filter({ hasText: /^RVA-LIVE-/ }).waitFor();
    assert.match(await page.locator('#estimatedValue').textContent(), /Insufficient market evidence/);
    assert.equal(await page.locator('#marketState').textContent(), 'No eligible estimate');
    assert.equal(valuations[0].valuation_basis, 'exterior_scan');
    assert.ok(valuations[0].assessment_receipt);
    const previousId = await page.locator('#reportId').textContent();
    await page.getByLabel('As-is sale offer, after fees').fill('400');
    await page.getByLabel('Total repair quote').fill('150');
    await page.getByLabel('Post-repair sale offer, after fees').fill('750');
    await page.getByRole('button', { name: 'Compare quotes' }).click();
    await page.locator('#decisionResult strong').filter({ hasText: 'Repair then sell' }).waitFor();
    assert.match(await page.locator('#decisionResult').textContent(), /RM600/);
    await page.evaluate(() => showPage('scan'));
    await page.locator('#finalInput-back').setInputFiles(await fixturePhoto(6));
    await report.waitFor({ state: 'detached' });
    // This route is a software fixture for the evidence panel, not an observed market price.
    await page.route('**/live-valuation', route => route.fulfill({
      json: { status: 'limited_local_market_evidence', value_low: 1050, value_high: 1150,
        price_basis: 'eligible_observations', condition_matched_count: 3,
        notes: ['Software fixture evidence'],
        eligible_observations: [
          { source: 'Fixture seller', source_url: 'https://fixture.invalid/item',
            price: 1100, price_type: 'asking_price', observed_at: '2026-11-01', evidence_origin: 'audited_csv' },
        ] },
    }));
    await analyze.click();
    await report.click();
    assert.notEqual(await page.locator('#reportId').textContent(), previousId);
    assert.equal(valuations.length, 2);
    assert.match(await page.locator('#estimatedValue').textContent(), /RM1,050–RM1,150/);
    assert.equal(await page.locator('#marketState').textContent(), 'Evidence-based estimate');
    assert.equal(await page.getByLabel('As-is sale offer, after fees').inputValue(), '');
    await page.getByRole('button', { name: 'How is this price estimated?' }).click();
    await page.getByText('operator-reviewed', { exact: false }).waitFor();
    assert.equal(await page.getByRole('link', { name: 'Fixture seller' }).getAttribute('href'), 'https://fixture.invalid/item');
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.getByRole('button', { name: 'Print / Save PDF' }).isVisible(), false);
    assert.equal(await page.locator('#marketState').isVisible(), true);
    await page.emulateMedia({ media: 'screen' });

    await page.unroute('**/live-valuation');
    await page.route('**/live-valuation', route => route.fulfill({ status: 503, json: { error: 'Software fixture outage' } }));
    await page.route(scanUrl, route => route.fulfill({ json: { status: 'ok', assessment_basis: 'provisional',
      yolo_model: 'revalue_exterior_yolo11n_v0.2', grade: { exterior_grade: 'A', note: 'Software fixture' },
      detections: [{ raw_class: 'scratch', view: 'back', confidence: .77, bounding_box_xyxy: [10, 10, 45, 35] }],
      merged_damage: [], assessment_receipt: 'software-fixture' } }));
    await page.evaluate(() => showPage('scan'));
    await analyze.click();
    await report.click();
    assert.equal(await page.locator('#estimatedValue').textContent(), 'Market estimate unavailable');
    assert.equal(await page.locator('#marketState').textContent(), 'Valuation request failed');
    assert.match(await page.locator('#reportDetections li').textContent(), /scratchBack77.0% model score/i);
    await page.unroute('**/live-valuation');
    await page.unroute(scanUrl);

    await selectPhone(page, 'Value This Phone');
    await page.getByRole('button', { name: 'Create QR + Link' }).click();
    const remoteLink = page.locator('#remoteLink');
    await remoteLink.waitFor();
    await page.waitForFunction(() => document.querySelector('img[alt="Scan session QR"]').naturalWidth > 0);
    const remoteContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const remote = await remoteContext.newPage();
    remote.on('pageerror', error => errors.push(error.message));
    await remote.goto(await remoteLink.inputValue());
    await remote.getByText('1 of 5 · Front', { exact: true }).waitFor();
    const usePhoto = remote.getByRole('button', { name: 'Use Photo' });
    for (let i = 0; i < 5; i++) {
      await remote.locator('#fileInput').setInputFiles(await fixturePhoto(i));
      await usePhoto.click();
      await usePhoto.waitFor({ state: 'hidden' });
    }
    await remote.getByText('All five views ready').waitFor();
    await remote.getByRole('button', { name: 'Send Photos' }).click();
    await remote.getByText('Photos sent successfully').waitFor();
    await page.bringToFront();
    await page.waitForFunction(() => document.querySelectorAll('.final-slot.ready').length === 5);

    const mobile = await remoteContext.newPage();
    mobile.on('pageerror', error => errors.push(error.message));
    await selectPhone(mobile, 'Value Another Phone');
    await mobile.getByRole('button', { name: 'Add right side photo' }).waitFor();
    assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await mobile.getByRole('button', { name: 'ReValue AI home' }).click();
    await mobile.getByRole('button', { name: 'Explore demo' }).click();
    await mobile.getByRole('button', { name: 'iPhone 13 Pro', exact: false }).waitFor();
    // Exercise the demo report presentation without waiting for the existing simulated checks.
    await mobile.evaluate(() => { exteriorDone = internalDone = true; showPage('report'); });
    assert.equal(await mobile.locator('#marketState').textContent(), 'Illustrative demo value');
    for (const width of [320, 390, 768]) {
      await mobile.setViewportSize({ width, height: 844 });
      assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    assert.deepEqual(errors, []);
    console.log('Browser smoke passed: catalogue and photo validation, loading/failure/review, real YOLO, reports, quotes, QR capture and mobile/demo layout.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
