'use strict';

const photos = document.getElementById('photos');
const form = document.getElementById('compare-form');
const compareButton = document.getElementById('compare');
const csvButton = document.getElementById('csv');
const jsonButton = document.getElementById('json');
const statusLine = document.getElementById('status');
const results = document.getElementById('results');
const LABELS = { generic_crack: 'Crack', scratch: 'Scratch', bump: 'Bump', paint: 'Paint' };
let metadata;
let records = [];

const inspectDialog = document.getElementById('inspect-dialog');
const inspectContent = document.getElementById('inspect-content');
const closeInspect = document.getElementById('close-inspect');
closeInspect.addEventListener('click', () => inspectDialog.close());
inspectDialog.addEventListener('click', event => {
  if (event.target === inspectDialog) inspectDialog.close();
});

function inspectPanel(panel, title) {
  inspectContent.replaceChildren();
  const heading = element('h2', title);
  const copy = panel.cloneNode(true);
  copy.querySelector('.inspect-button')?.remove();
  inspectContent.append(heading, copy);
  inspectDialog.showModal();
  closeInspect.focus();
}


function element(tag, label, className) {
  const node = document.createElement(tag);
  if (label !== undefined) node.textContent = label;
  if (className) node.className = className;
  return node;
}

function renderPanel(title, photo, image, report) {
  const panel = element('section', undefined, 'panel');
  panel.append(element('h3', title));
  const view = element('div', undefined, 'photo');
  view.style.aspectRatio = `${image.width} / ${image.height}`;
  const img = element('img');
  img.src = `data:image/jpeg;base64,${photo}`;
  img.alt = title;
  view.append(img);
  panel.append(view);
  const inspect = element('button', 'Inspect image larger', 'inspect-button');
  inspect.type = 'button';
  inspect.setAttribute('aria-label', 'Inspect ' + title + ' image larger');
  inspect.addEventListener('click', () => inspectPanel(panel, title));
  // Insert the action after the rendered image and its annotations.
  if (!report) {
    panel.append(inspect);
    return panel;
  }

  const overlay = element('div', undefined, 'overlay');
  overlay.setAttribute('aria-hidden', 'true');
  const counts = element('div', undefined, 'counts');
  const list = element('ul', undefined, 'detections');
  for (const item of report.detections) {
    const [x1, y1, x2, y2] = item.xyxy_px;
    const confidence = `${(100 * item.confidence).toFixed(1)}%`;
    const label = LABELS[item.comparison_class];
    const box = element('div', undefined, 'box');
    box.dataset.class = item.comparison_class;
    box.style.left = `${100 * x1 / image.width}%`;
    box.style.top = `${100 * y1 / image.height}%`;
    box.style.width = `${100 * (x2 - x1) / image.width}%`;
    box.style.height = `${100 * (y2 - y1) / image.height}%`;
    box.append(element('span', `${label} ${confidence}`));
    overlay.append(box);
    const mapping = item.raw_class === item.comparison_class ? '' : ` (${item.raw_class} → ${item.comparison_class})`;
    list.append(element('li', `${label}${mapping} · ${confidence}`));
  }
  view.append(overlay);
  for (const [label, count] of Object.entries(report.counts)) {
    counts.append(element('span', `${LABELS[label]} ${count}`));
  }
  panel.append(counts, element('p', `CPU inference ${report.cpu_inference_ms.toFixed(1)} ms · whole prediction ${report.cpu_predict_wall_ms.toFixed(1)} ms`, 'timing'));
  if (report.detections.length) panel.append(list);
  else panel.append(element('p', 'No detections at 0.25.'));
  panel.append(inspect);
  return panel;
}

function renderResult(record, preview) {
  const article = element('article');
  article.append(element('h2', `${record.image_id} · ${record.filename}`));
  if (record.error) {
    article.append(element('p', record.error, 'error'));
  } else {
    const grid = element('div', undefined, 'panel-grid');
    grid.append(renderPanel('Original photo', preview, record.image));
    for (const [key, info] of Object.entries(metadata.models)) {
      grid.append(renderPanel(info.name, preview, record.image, record.models[key]));
    }
    article.append(grid);
  }
  results.append(article);
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const files = Array.from(photos.files);
  if (!files.length || files.length > 20) {
    statusLine.textContent = 'Choose between 1 and 20 photos.';
    return;
  }
  photos.disabled = compareButton.disabled = csvButton.disabled = jsonButton.disabled = true;
  records = [];
  results.replaceChildren();
  let completed = 0;
  for (const [index, file] of files.entries()) {
    const record = { image_id: `Photo ${index + 1}`, filename: file.name };
    let preview;
    statusLine.textContent = `Comparing photo ${index + 1} of ${files.length}…`;
    try {
      const response = await fetch('/compare', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error);
      record.image = payload.image;
      record.models = payload.models;
      preview = payload.preview_jpeg_base64;
      completed++;
    } catch (error) {
      record.error = error instanceof TypeError ? 'Cannot reach the local comparison. Check the PowerShell window.' : error.message;
    }
    records.push(record);
    renderResult(record, preview);
  }
  photos.disabled = compareButton.disabled = csvButton.disabled = jsonButton.disabled = false;
  const failed = files.length - completed;
  statusLine.textContent = `${completed} of ${files.length} photos compared.${failed ? ` ${failed} could not be compared.` : ''} Exports are ready.`;
});

function csvCell(value) {
  if (value == null) return '';
  let text = String(value);
  // A filename is user input. A leading apostrophe keeps spreadsheet software from evaluating it.
  if (typeof value === 'string' && /^[\s]*[=+@-]|^[\t\r\n]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function csvExport() {
  const { imgsz, conf, iou, device } = metadata.settings;
  const rows = [['scope', 'image_id', 'filename', 'source_sha256', 'width_px', 'height_px', 'image_size', 'confidence_threshold', 'nms_iou', 'device',
    'model', 'weights_sha256', 'crack_count', 'scratch_count', 'bump_count', 'paint_count', 'cpu_inference_ms', 'cpu_predict_wall_ms',
    'raw_class', 'comparison_class', 'confidence', 'x1_px', 'y1_px', 'x2_px', 'y2_px', 'error']];
  for (const record of records) {
    const shared = ['qualitative', record.image_id, record.filename, record.image?.source_sha256, record.image?.width, record.image?.height, imgsz, conf, iou, device];
    if (record.error) {
      rows.push([...shared, ...Array(15).fill(''), record.error]);
      continue;
    }
    for (const [key, info] of Object.entries(metadata.models)) {
      const { counts, detections, cpu_inference_ms, cpu_predict_wall_ms } = record.models[key];
      const summary = [...shared, info.name, info.sha256, counts.generic_crack, counts.scratch, counts.bump, counts.paint, cpu_inference_ms, cpu_predict_wall_ms];
      for (const box of detections.length ? detections : [null]) {
        const details = box ? [box.raw_class, box.comparison_class, box.confidence, ...box.xyxy_px] : Array(7).fill('');
        rows.push([...summary, ...details, '']);
      }
    }
  }
  return '\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

function download(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = element('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

csvButton.addEventListener('click', () => download('revalue-qualitative-comparison.csv', csvExport(), 'text/csv;charset=utf-8'));
jsonButton.addEventListener('click', () => download('revalue-qualitative-comparison.json', JSON.stringify({ ...metadata, images: records }, null, 2) + '\n', 'application/json'));

fetch('/metadata').then(response => {
  if (!response.ok) throw new Error('Metadata unavailable');
  return response.json();
}).then(data => {
  metadata = data;
  const settings = metadata.settings;
  document.getElementById('settings').textContent = `Both models · ${settings.imgsz} × ${settings.imgsz} · confidence ${settings.conf} · NMS IoU ${settings.iou.toFixed(2)} · CPU`;
  statusLine.textContent = 'Ready to compare photos.';
  compareButton.disabled = false;
}).catch(() => { statusLine.textContent = 'The local comparison is unavailable. Check the PowerShell window and reload this page.'; });
