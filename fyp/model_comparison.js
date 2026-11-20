'use strict';

const photos = document.getElementById('photos');
const form = document.getElementById('compare-form');
const compareButton = document.getElementById('compare');
const csvButton = document.getElementById('csv');
const jsonButton = document.getElementById('json');
const statusLine = document.getElementById('status');
const results = document.getElementById('results');
const empty = document.getElementById('result-empty');
const legend = document.getElementById('result-legend');
const queue = document.getElementById('file-queue');
const progress = document.getElementById('batch-progress');
const dropZone = document.getElementById('drop-zone');
const dialog = document.getElementById('inspect-dialog');
const zoomArea = document.getElementById('zoom-area');
const inspectionDetails = document.getElementById('inspection-details');
const closeInspection = document.getElementById('close-inspect');
const zoomOut = document.getElementById('zoom-out');
const zoomIn = document.getElementById('zoom-in');
const LABELS = { generic_crack: 'Crack', scratch: 'Scratch', bump: 'Bump', paint: 'Paint' };
let metadata;
let records = [];
let selectedFiles = [];
let busy = false;
let zoom = 1;
let inspected;
let inspectorTrigger;

function element(tag, label, className) {
  const node = document.createElement(tag);
  if (label !== undefined) node.textContent = label;
  if (className) node.className = className;
  return node;
}

function status(text, error = false) {
  statusLine.textContent = text;
  statusLine.classList.toggle('rv-alert', error);
}

function updateQueue(focusIndex) {
  queue.replaceChildren();
  const visible = selectedFiles.length <= 20 ? selectedFiles : [];
  queue.hidden = visible.length === 0;
  for (const [index, file] of visible.entries()) {
    const row = element('li');
    const remove = element('button', 'Remove', 'file-remove');
    remove.type = 'button';
    remove.disabled = busy;
    remove.setAttribute('aria-label', `Remove ${file.name}`);
    remove.addEventListener('click', () => {
      selectedFiles.splice(index, 1);
      photos.value = '';
      updateQueue(index);
      describeSelection();
    });
    row.append(element('span', file.name), remove);
    queue.append(row);
  }
  compareButton.disabled = busy || !metadata || !visible.length;
  if (focusIndex !== undefined) {
    (queue.querySelectorAll('button')[Math.min(focusIndex, visible.length - 1)] || photos).focus();
  }
}

function describeSelection() {
  if (selectedFiles.length > 20) status('Choose no more than 20 photos for one comparison.', true);
  else if (selectedFiles.length) status(`${selectedFiles.length} ${selectedFiles.length === 1 ? 'photo ready' : 'photos ready'} to compare.`);
  else if (metadata) status('Ready to compare photos.');
}

photos.addEventListener('change', () => {
  selectedFiles = Array.from(photos.files);
  updateQueue();
  describeSelection();
});
dropZone.addEventListener('dragover', event => {
  event.preventDefault();
  if (!busy && event.dataTransfer.types.includes('Files')) dropZone.classList.add('drag-active');
});
dropZone.addEventListener('dragleave', event => {
  if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove('drag-active');
});
dropZone.addEventListener('drop', event => {
  event.preventDefault();
  dropZone.classList.remove('drag-active');
  if (busy || !event.dataTransfer.files.length) return;
  photos.value = '';
  selectedFiles = Array.from(event.dataTransfer.files);
  updateQueue();
  describeSelection();
});

function renderPhoto(title, jpeg, image, report) {
  const view = element('div', undefined, 'photo');
  view.style.aspectRatio = `${image.width} / ${image.height}`;
  view.style.setProperty('--image-ratio', image.width / image.height);
  const img = element('img');
  img.src = `data:image/jpeg;base64,${jpeg}`;
  img.alt = title;
  view.append(img);
  if (!report?.detections.length) return view;

  const overlay = element('div', undefined, 'overlay');
  overlay.setAttribute('aria-hidden', 'true');
  for (const item of report.detections) {
    const [x1, y1, x2, y2] = item.xyxy_px;
    const box = element('div', undefined, 'box');
    box.dataset.class = item.comparison_class;
    box.classList.toggle('label-left', x1 / image.width > 0.60);
    box.style.left = `${100 * x1 / image.width}%`;
    box.style.top = `${100 * y1 / image.height}%`;
    box.style.width = `${100 * (x2 - x1) / image.width}%`;
    box.style.height = `${100 * (y2 - y1) / image.height}%`;
    box.append(element('span', `${LABELS[item.comparison_class]} ${confidence(item)}`));
    overlay.append(box);
  }
  view.append(overlay);
  return view;
}

function confidence(item) {
  return `${(100 * item.confidence).toFixed(1)}%`;
}

function renderPanel(title, jpeg, image, report) {
  const panel = element('section', undefined, 'panel');
  const frame = element('div', undefined, 'panel-frame');
  frame.append(renderPhoto(title, jpeg, image, report));
  const inspect = element('button', 'Inspect image', 'rv-button-secondary inspect-button');
  inspect.type = 'button';
  inspect.setAttribute('aria-label', `Inspect ${title} image larger`);
  inspect.addEventListener('click', () => openInspection(inspect, title, jpeg, image, report));
  panel.append(element('h4', title), frame, inspect);
  if (report) appendPredictionDetails(panel, report);
  return panel;
}

function appendPredictionDetails(container, report) {
  const counts = element('div', undefined, 'counts');
  for (const [label, count] of Object.entries(report.counts)) {
    counts.append(element('span', `${LABELS[label]} ${count}`));
  }
  const timing = element('div', undefined, 'timing');
  timing.append(element('strong', `CPU inference ${report.cpu_inference_ms.toFixed(1)} ms`),
    element('span', `Whole prediction ${report.cpu_predict_wall_ms.toFixed(1)} ms`));
  container.append(counts, timing);
  if (report.detections.length) {
    const list = element('ul', undefined, 'detections');
    for (const item of report.detections) {
      const mapping = item.raw_class === item.comparison_class ? '' : ` (${item.raw_class} → ${item.comparison_class})`;
      list.append(element('li', `${LABELS[item.comparison_class]}${mapping} · ${confidence(item)}`));
    }
    container.append(list);
  } else {
    container.append(element('p', `No detections at ${metadata.settings.conf}.`, 'no-detections'));
  }
}

function openInspection(trigger, title, jpeg, image, report) {
  inspectorTrigger = trigger;
  zoom = 1;
  inspected = renderPhoto(title, jpeg, image, report);
  zoomArea.replaceChildren(inspected);
  inspectionDetails.replaceChildren();
  inspectionDetails.hidden = !report;
  if (report) appendPredictionDetails(inspectionDetails, report);
  document.getElementById('inspection-title').textContent = `Inspect · ${title}`;
  dialog.showModal();
  zoomArea.scrollTo(0, 0);
  sizeInspection();
  closeInspection.focus();
}

function sizeInspection() {
  if (!dialog.open) return;
  const fitted = Math.min(zoomArea.clientWidth - 18, (zoomArea.clientHeight - 18) * Number(inspected.style.getPropertyValue('--image-ratio')));
  inspected.style.width = `${Math.max(1, fitted) * zoom}px`;
  document.getElementById('zoom-level').textContent = `${Math.round(zoom * 100)}%`;
  zoomOut.disabled = zoom === 1;
  zoomIn.disabled = zoom === 3;
}

zoomOut.addEventListener('click', () => { zoom = Math.max(1, zoom - .25); sizeInspection(); });
zoomIn.addEventListener('click', () => { zoom = Math.min(3, zoom + .25); sizeInspection(); });
closeInspection.addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
dialog.addEventListener('close', () => {
  zoomArea.replaceChildren();
  inspectorTrigger?.focus();
});
window.addEventListener('resize', sizeInspection);

function renderResult(record, preview) {
  const article = element('article', undefined, 'rv-card');
  article.append(element('h3', `${record.image_id} · ${record.filename}`));
  if (record.error) {
    article.append(element('p', record.error, 'rv-alert error'));
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
  if (busy || !metadata || !selectedFiles.length || selectedFiles.length > 20) return;
  const files = selectedFiles.slice();
  busy = true;
  photos.disabled = csvButton.disabled = jsonButton.disabled = true;
  updateQueue();
  records = [];
  results.replaceChildren();
  results.setAttribute('aria-busy', 'true');
  empty.hidden = legend.hidden = true;
  progress.max = files.length;
  progress.value = 0;
  progress.hidden = false;
  let completed = 0;
  for (const [index, file] of files.entries()) {
    const record = { image_id: `Photo ${index + 1}`, filename: file.name };
    let preview;
    status(`Comparing photo ${index + 1} of ${files.length}…`);
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
    progress.value = index + 1;
  }
  busy = false;
  photos.disabled = csvButton.disabled = jsonButton.disabled = false;
  updateQueue();
  results.removeAttribute('aria-busy');
  progress.hidden = true;
  legend.hidden = completed === 0;
  const failed = files.length - completed;
  status(`${completed} of ${files.length} photos compared.${failed ? ` ${failed} could not be compared.` : ''} Exports are ready.`, completed === 0);
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
  const entries = [
    ['Image size', `${settings.imgsz} × ${settings.imgsz}`],
    ['Confidence threshold', settings.conf],
    ['NMS IoU', settings.iou.toFixed(2)],
    ['Device', settings.device.toUpperCase()],
  ];
  document.getElementById('settings').replaceChildren(...entries.map(([label, value]) => {
    const row = element('div');
    row.append(element('dt', label), element('dd', value));
    return row;
  }));
  status('Ready to compare photos.');
  updateQueue();
  describeSelection();
}).catch(() => {
  status('The local comparison is unavailable. Check the PowerShell window and reload this page.', true);
});
