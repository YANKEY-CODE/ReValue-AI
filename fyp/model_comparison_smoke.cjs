// Run against the local comparison server with Playwright and Chromium installed.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
    page.setDefaultTimeout(45000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.REVALUE_COMPARISON_URL || 'http://127.0.0.1:8766');
    await page.getByText('Ready to compare photos.').waitFor();
    const encodeFixture = color => page.evaluate(fill => {
      const canvas = document.createElement('canvas');
      canvas.width = 64;
      canvas.height = 48;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = fill;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/png').split(',')[1];
    }, color);
    const photo = async (name, color) => ({ name, mimeType: 'image/png', buffer: Buffer.from(await encodeFixture(color), 'base64') });
    const fileInput = page.getByLabel('Smartphone photos');
    await fileInput.setInputFiles([
      await photo('generated-front.png', '#c9ccd1'),
      { name: 'corrupt.png', mimeType: 'image/png', buffer: Buffer.from('invalid') },
      await photo('generated-back.png', '#658664'),
    ]);
    await page.getByRole('button', { name: 'Remove generated-back.png' }).waitFor();
    assert.equal(await page.getByRole('list', { name: 'Selected photos' }).getByRole('listitem').count(), 3);
    const realResponse = page.waitForResponse(response => response.url().endsWith('/compare') && response.ok());
    await page.getByRole('button', { name: 'Compare photos' }).click();
    const real = await (await realResponse).json();
    await page.getByText('2 of 3 photos compared.', { exact: false }).waitFor();
    assert.equal(await page.getByAltText('Original photo').count(), 2);
    assert.equal(await page.locator('.timing').count(), 4);
    assert.match(await page.locator('article.error, article .error').textContent(), /readable JPEG/);

    async function exportFile(buttonName) {
      const download = page.waitForEvent('download');
      await page.getByRole('button', { name: buttonName }).click();
      return fs.readFile(await (await download).path(), 'utf8');
    }

    const actual = JSON.parse(await exportFile('Export JSON'));
    assert.equal(actual.comparison_type, 'qualitative');
    assert.equal(actual.settings.imgsz, 640);
    assert.equal(actual.settings.conf, 0.25);
    assert.equal(actual.images.length, 3);
    assert.equal(actual.images[1].filename, 'corrupt.png');
    assert.ok(actual.images[2].models.houdan.cpu_inference_ms > 0);
    assert.notEqual(actual.images[0].image.source_sha256, actual.images[2].image.source_sha256);
    assert.ok(actual.images.every(record => !('preview_jpeg_base64' in record)));
    const actualCsv = await exportFile('Export CSV');
    const failedRow = actualCsv.split(/\r?\n/).find(row => row.includes('corrupt.png'));
    assert.match(failedRow, /"Upload a readable JPEG, PNG or WebP\."$/);

    // Controlled display fixture. No assertions about detection accuracy on the generated photos.
    const box = (raw_class, comparison_class) => ({ raw_class, comparison_class, confidence: 0.82, xyxy_px: [8, 4, 30, 24] });
    await page.route('**/compare', route => route.fulfill({ json: {
      ...real,
      models: {
        revalue: { ...real.models.revalue, counts: { generic_crack: 0, scratch: 0 }, detections: [] },
        houdan: { ...real.models.houdan, counts: { generic_crack: 1, scratch: 0, bump: 1, paint: 1 },
          detections: [box('crack', 'generic_crack'), box('bump', 'bump'), box('paint', 'paint')] },
      },
    } }));
    await fileInput.setInputFiles(await photo('=private-test.png', '#c9ccd1'));
    await page.getByRole('button', { name: 'Compare photos' }).click();
    await page.getByText('1 of 1 photos compared.', { exact: false }).waitFor();
    await page.getByText('Crack (crack → generic_crack) · 82.0%').waitFor();
    assert.equal(await page.locator('.box').count(), 3);
    assert.equal(await page.locator('.box[data-class=generic_crack]').evaluate(node => node.style.left), '12.5%');
    assert.equal(await page.locator('.counts').last().textContent(), 'Crack 1Scratch 0Bump 1Paint 1');
    const inspect = page.getByRole('button', { name: /Inspect Houdan YOLO11s.*image larger/ });
    await inspect.click();
    const dialog = page.getByRole('dialog', { name: 'Enlarged model image inspection' });
    await dialog.waitFor();
    await dialog.getByText('Crack (crack → generic_crack) · 82.0%').waitFor();
    await dialog.getByRole('button', { name: 'Zoom in' }).click();
    await dialog.getByText('125%').waitFor();
    assert.equal(await dialog.locator('.box[data-class=generic_crack]').count(), 1);
    const boxes = dialog.getByLabel('Show boxes');
    await boxes.uncheck();
    assert.equal(await dialog.locator('.overlay').isVisible(), false);
    assert.equal(await dialog.locator('.photo img').isVisible(), true);
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    assert.equal(await inspect.evaluate(node => document.activeElement === node), true);
    await inspect.click();
    assert.equal(await boxes.isChecked(), true);
    await dialog.getByRole('button', { name: 'Close inspection' }).click();
    await dialog.waitFor({ state: 'hidden' });
    await page.waitForFunction(() => [...document.images].every(img => img.complete && img.naturalWidth > 0));
    const csv = await exportFile('Export CSV');
    assert.ok(csv.startsWith('\uFEFF'));
    assert.match(csv, /"raw_class","comparison_class","confidence"/);
    assert.match(csv, /"crack","generic_crack","0.82","8","4","30","24"/);
    assert.match(csv, /"'=private-test\.png"/);
    assert.equal(csv.trim().split(/\r?\n/).length, 5);
    const panels = page.locator('.panel');
    assert.ok((await panels.nth(0).boundingBox()).x < (await panels.nth(1).boundingBox()).x);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok((await panels.nth(0).boundingBox()).y < (await panels.nth(1).boundingBox()).y);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const files = await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['contents'], 'dropped.png', { type: 'image/png' }));
      return transfer;
    });
    await page.locator('#drop-zone').dispatchEvent('drop', { dataTransfer: files });
    await page.getByRole('button', { name: 'Remove dropped.png' }).click();
    assert.equal(await page.getByRole('button', { name: 'Compare photos' }).isEnabled(), false);
    for (const width of [320, 768]) {
      await page.setViewportSize({ width, height: 844 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.getByRole('button', { name: 'Export CSV' }).isVisible(), false);
    assert.equal(await page.locator('#results .panel').count(), 3);
    assert.deepEqual(errors, []);
    console.log('Comparison browser checks passed: real multi-photo CPU inference, rejected input, overlays, counts and both downloads.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
