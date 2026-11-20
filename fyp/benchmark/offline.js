(() => {
  const { queue, images } = JSON.parse(document.getElementById('practiceData').textContent);
  const storageKey = 'revalue-practice:' + queue + ':' + Object.values(images).map(row => row.image_sha256).join(':');
  const saved = {};
  let persisted = true;

  function check(row, annotation) {
    const { actor, kind, boxes, note } = annotation || {};
    if (typeof actor !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(actor)) {
      throw new Error('Enter a pseudonymous ID using letters, numbers or dashes.');
    }
    if (typeof note !== 'string' || !note.trim() || note.length > 2000) {
      throw new Error('Write a short evidence note or a reason for excluding the image.');
    }
    if (!['positive', 'clean', 'exclude'].includes(kind) || !Array.isArray(boxes) ||
        (kind === 'positive') !== Boolean(boxes.length) || boxes.length > 200) {
      throw new Error('Add boxes for visible damage. Clean and excluded images require zero boxes.');
    }
    const seen = new Set();
    for (const box of boxes) {
      if (!box || !['generic_crack', 'scratch'].includes(box.label) || !Array.isArray(box.xyxy) ||
          box.xyxy.length !== 4 || !box.xyxy.every(Number.isInteger)) {
        throw new Error('The label or box is invalid.');
      }
      const [x1, y1, x2, y2] = box.xyxy;
      const marker = [box.label, ...box.xyxy].join(':');
      if (!(0 <= x1 && x1 < x2 && x2 <= row.width && 0 <= y1 && y1 < y2 && y2 <= row.height) || seen.has(marker)) {
        throw new Error('Keep boxes inside the image and remove duplicates.');
      }
      seen.add(marker);
    }
    return { actor, kind, boxes: boxes.map(({ label, xyxy }) => ({ label, xyxy })), note: note.trim() };
  }

  function restore(backup, stored = false) {
    if (backup?.queue !== queue || !Array.isArray(backup.rows) || backup.rows.length > Object.keys(images).length) {
      throw new Error('Choose a labels file exported from this practice queue.');
    }
    const pending = {};
    for (const item of backup.rows) {
      if (!item || !Object.hasOwn(images, item.id) || Object.hasOwn(pending, item.id) ||
          images[item.id].image_sha256 !== item.image_sha256) {
        throw new Error('The labels file contains unfamiliar, repeated or changed images.');
      }
      const annotation = check(images[item.id], item.annotation);
      const existing = saved[item.id] || images[item.id].annotation;
      if (!stored && existing && JSON.stringify(existing) !== JSON.stringify(annotation)) {
        throw new Error('The file conflicts with an existing annotation. Your current work was kept.');
      }
      pending[item.id] = annotation;
    }
    Object.assign(saved, pending);
    return Object.keys(pending).length;
  }

  function exportLabels() {
    return { queue, rows: Object.values(images).filter(row => saved[row.id] || row.annotation).map(row => ({
      id: row.id, image_sha256: row.image_sha256, annotation: saved[row.id] || row.annotation
    })) };
  }

  function persist() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(exportLabels()));
      persisted = true;
    } catch {
      persisted = false;
    }
  }

  let warning = '';
  try {
    const previous = localStorage.getItem(storageKey);
    if (previous) restore(JSON.parse(previous), true);
  } catch (error) {
    warning = 'Could not restore browser storage. Use Import saved labels if you have a backup.';
  }

  window.practiceOffline = {
    queue, warning,
    image(id) { return images[id].image; },
    recordedCount() { return exportLabels().rows.length; },
    saveStatus() {
      return persisted ? 'Saved in this browser. Download your labels to back them up.'
                       : 'Saved for this session. Download your labels before closing.';
    },
    async api(path, data) {
      if (path === '/records') return Object.values(images).map(row => ({
        id: row.id, annotated: Boolean(saved[row.id] || row.annotation), practice: true
      }));
      const [, action, id] = path.split('/');
      if (!Object.hasOwn(images, id)) throw new Error('Practice image not found.');
      const row = images[id];
      if (action === 'record') return { ...row, annotation: saved[id] || row.annotation, review: null };
      if (action !== 'annotate') throw new Error('Practice accepts human annotations only.');
      saved[id] = check(row, data);
      persist();
      return { ok: true };
    },
    async import(file) {
      if (file.size > 500_000) throw new Error('Choose the small JSON labels file.');
      const count = restore(JSON.parse(await file.text()));
      persist();
      return count;
    },
    download() {
      const labels = exportLabels();
      if (!labels.rows.length) throw new Error('Save an annotation before downloading labels.');
      const url = URL.createObjectURL(new Blob([JSON.stringify(labels, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'revalue-practice-' + queue.slice(-1) + '-labels.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return labels.rows.length;
    }
  };
})();
