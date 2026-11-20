// Exercise a protected deployment over HTTPS with generated software fixture photos.
const assert = require('node:assert/strict');
const { chromium, devices, request } = require('playwright');

const url = new URL(process.env.REVALUE_DEMO_URL || 'https://127.0.0.1:18792');
const password = process.env.REVALUE_DEMO_PASSWORD;
const ignoreHTTPSErrors = process.env.REVALUE_ALLOW_LOCAL_TEST_CERT === '1' && url.hostname === '127.0.0.1';
assert.equal(url.protocol, 'https:');
assert.ok(!url.username && !url.password, 'Keep credentials out of the URL');
assert.ok(password, 'Set REVALUE_DEMO_PASSWORD in the local process environment');

(async () => {
  const anonymous = await request.newContext({ ignoreHTTPSErrors });
  try {
    assert.equal((await anonymous.get(new URL('/healthz', url).href)).status(), 200);
    for (const route of ['/', '/revalue-design.css', '/catalogue/search?q=Apple']) {
      const reply = await anonymous.get(new URL(route, url).href);
      assert.equal(reply.status(), 401, route);
      assert.match(reply.headers()['www-authenticate'], /Basic/);
    }
  } finally {
    await anonymous.dispose();
  }

  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  try {
    const layouts = [
      ['desktop', { viewport: { width: 1440, height: 900 } }],
      ['mobile', { ...devices['iPhone 13'], defaultBrowserType: 'chromium' }],
    ];
    for (const [layout, options] of layouts) {
      const context = await browser.newContext({ ...options, ignoreHTTPSErrors,
        httpCredentials: { username: 'supervisor', password, origin: url.origin } });
      const page = await context.newPage();
      page.setDefaultTimeout(90000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const home = await page.goto(url.origin);
      assert.equal(home.status(), 200);
      assert.equal(home.headers()['cache-control'], 'no-store');
      await page.getByRole('button', { name: 'Start Phone Assessment' }).click();
      await page.getByRole('button', { name: 'Value This Phone' }).click();
      await page.getByLabel('Brand or model').fill('iPhone 13 Pro');
      await page.locator('.catalogue-result').filter({ hasText: 'Apple iPhone 13 Pro' }).first().click();
      await page.getByLabel('Storage capacity').fill('256GB');
      await page.getByRole('button', { name: 'Confirm Storage', exact: true }).click();
      await page.getByText('The server does not save them.', { exact: false }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Create QR + Link' }).count(), 0);
      assert.equal(await page.locator('#verifyWithGemini').count(), 0);

      const views = ['front', 'back', 'camera', 'left_side', 'right_side'];
      for (const [i, view] of views.entries()) {
        const data = await page.evaluate(({ color, wide }) => {
          const canvas = document.createElement('canvas');
          canvas.width = wide ? 2400 : 300;
          canvas.height = wide ? 1000 : 200;
          const ctx = canvas.getContext('2d');
          ctx.fillStyle = color;
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          return canvas.toDataURL().split(',')[1];
        }, { color: ['#eeeeff', '#e0e7d3', '#e9dcc1', '#d0dfe9', '#ecd9e6'][i], wide: i === 0 });
        await page.locator(`#finalInput-${view}`).setInputFiles({ name: `fixture-${i}.png`, mimeType: 'image/png', buffer: Buffer.from(data, 'base64') });
        await page.locator('.final-slot.ready').nth(i).waitFor();
      }
      await page.waitForFunction(() => document.querySelector('.final-slot.ready img').naturalWidth === 2048);
      const received = page.waitForResponse(response => response.url() === new URL('/analyze-exterior', url).href);
      await page.getByRole('button', { name: 'Analyze Exterior', exact: true }).click();
      const analyzed = await received;
      assert.equal(analyzed.status(), 200);
      const body = await analyzed.json();
      assert.equal(body.status, 'ok');
      assert.equal(body.yolo_model, 'revalue_exterior_yolo11n_v0.2');
      assert.equal(body.gemini_status, 'skipped');
      assert.ok(body.assessment_receipt);
      const images = analyzed.request().postDataJSON().images;
      assert.deepEqual(images.map(image => [image.filename, image.mime_type]), views.map(view => [`${view}.jpg`, 'image/jpeg']));
      assert.ok(images.every(image => Buffer.from(image.bytes_b64, 'base64').length <= 2 * 1024 * 1024));
      await page.getByRole('button', { name: 'View Exterior Report' }).click();
      await page.getByRole('heading', { name: 'Assessment report' }).waitFor();
      assert.equal(await page.locator('#estimatedValue').textContent(), 'Insufficient market evidence');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`${layout}: HTTPS login, five uploads, real YOLO11n CPU inference and assessment report passed.`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
