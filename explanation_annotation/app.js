/* Explanation Quality Annotation — static, no backend, no external dependency.
 *
 * BASELINE STUDY (current): VisExMEM-9B is excluded. Three blinded systems only.
 *
 * Flow: login -> DASHBOARD -> sample. A sample has two tasks:
 *   Task A: rate all 3 blinded explanations (Explanation A/B/C), one at a time, no
 *           highlighted regions shown.
 *   Task B: unlocked only once every Task-A question is answered for all 3 labels;
 *           shows up to 3 evidence claims (with highlighted image regions) for ONLY the
 *           labels whose underlying system genuinely produced grounded evidence -- other
 *           labels simply have no Task B panel, which is expected and not a bug.
 *
 * The bundle NEVER contains which real system a label (A/B/C) corresponds to -- that
 * mapping exists only in the researcher's private/blinding_map.json, not here.
 *
 * Encrypted bundle -> Web Crypto -> IndexedDB. Nothing leaves the browser except the
 * JSON file the annotator explicitly downloads and emails back.
 */
'use strict';

const APP_VERSION = '2.1.0';
const CONTENT_VERSION = 'explanation-quality-v6-baseline-no-visexmem';
const LABELS = ['A', 'B', 'C'];

const TECH_REASONS = [
  ['image_failed', 'Image failed to load'],
  ['image_corrupt', 'Image unreadable / corrupt'],
  ['duplicate', 'Duplicate sample'],
  ['malformed_text', 'Malformed text'],
  ['app_problem', 'App problem'],
];

/* FROZEN WORDING -- exact question text and 1-5 anchor labels, do not edit without
   re-freezing. */
const TASKA_QS = [
  { key: 'diagnostic_correctness', name: 'Diagnostic Correctness',
    desc: 'How accurately does the explanation identify the relevant matches or mismatches between the image and caption?',
    anchors: ['Completely incorrect', 'Mostly incorrect', 'Partially correct', 'Mostly correct', 'Completely correct'] },
  { key: 'visual_grounding', name: 'Visual Grounding',
    desc: 'How well are the statements in the explanation supported by what is visibly present in the image and stated in the caption?',
    anchors: ['Not supported', 'Mostly unsupported', 'Partially supported', 'Mostly supported', 'Fully supported'] },
  { key: 'clarity', name: 'Clarity',
    desc: 'How easy is the explanation to understand, without unnecessary or confusing information?',
    anchors: ['Very unclear', 'Somewhat unclear', 'Neither clear nor unclear', 'Clear', 'Very clear'] },
  { key: 'diagnostic_usefulness', name: 'Diagnostic Usefulness', primary: true,
    desc: 'How useful is the explanation for understanding why the image and caption align or fail to align?',
    anchors: ['Not useful', 'Slightly useful', 'Moderately useful', 'Very useful', 'Extremely useful'] },
];
const UNSUPPORTED_Q = {
  name: 'Unsupported Content',
  desc: 'Does this explanation contain any specific factual statement that is contradicted by, or unsupported by, the image/caption?',
};
const FLAG_OPTIONS = [['yes', 'Yes'], ['no', 'No'], ['unsure', 'Unsure']];
const TASKB_QS = [
  { key: 'localization_accuracy', name: 'Evidence Localization Accuracy',
    desc: 'How accurately do the highlighted region(s) identify the visual evidence relevant to this claim?',
    anchors: ['Completely incorrect', 'Mostly incorrect', 'Partially correct', 'Mostly correct', 'Completely correct'] },
  { key: 'sufficiency', name: 'Evidence Sufficiency',
    desc: 'How sufficient are the highlighted region(s) for deciding whether this claim is supported by the image?',
    anchors: ['Completely insufficient', 'Mostly insufficient', 'Partially sufficient', 'Mostly sufficient', 'Fully sufficient'] },
];

const $ = (id) => document.getElementById(id);
const onAll = (ids, ev, fn) => ids.forEach((i) => { const e = $(i); if (e) e.addEventListener(ev, fn); });
const setAll = (ids, prop, v) => ids.forEach((i) => { const e = $(i); if (e) e[prop] = v; });
const textAll = (ids, v) => ids.forEach((i) => { const e = $(i); if (e) e.textContent = v; });
let S = null; // {bundle, ann, idx, db, filter, editing, curTab}

/* ---------------- crypto ---------------- */
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decryptBundle(enc, password) {
  const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(password),
    'PBKDF2', false, ['deriveKey']);
  const aes = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(enc.salt), iterations: enc.iterations, hash: 'SHA-256' },
    km, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(enc.iv) }, aes, b64(enc.ciphertext));
  return JSON.parse(new TextDecoder().decode(pt));
}
async function sha256Hex(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/* ---------------- storage ---------------- */
function dbName(b) {
  return `visexmem_explan_${b.annotator_id}_${b.assignment_hash.slice(0, 12)}_${CONTENT_VERSION}`;
}
const openDB = (n) => new Promise((res, rej) => {
  const r = indexedDB.open(n, 1);
  r.onupgradeneeded = () => r.result.createObjectStore('ann', { keyPath: 'sample_id' });
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const idbPut = (db, rec) => new Promise((res, rej) => {
  const t = db.transaction('ann', 'readwrite'); t.objectStore('ann').put(rec);
  t.oncomplete = res; t.onerror = () => rej(t.error);
});
const idbAll = (db) => new Promise((res, rej) => {
  const q = db.transaction('ann', 'readonly').objectStore('ann').getAll();
  q.onsuccess = () => res(q.result || []); q.onerror = () => rej(q.error);
});

function chip(state, text) {
  const c = $('saveChip'); c.className = 'save-chip ' + (state || ''); c.textContent = text;
}
async function persist(sid) {
  const r = S.ann[sid]; if (!r) return;
  r.last_modified_at = new Date().toISOString();
  chip('busy', 'Saving…');
  try {
    if (S.db) await idbPut(S.db, r);
    else localStorage.setItem(dbName(S.bundle) + ':' + sid, JSON.stringify(r));
    chip('ok', 'Saved');
  } catch (e) { chip('err', 'Error saving'); console.error(e); }
}

/* ---------------- records & status ---------------- */
function blankTaskA() {
  const o = {};
  LABELS.forEach((l) => {
    o[l] = { diagnostic_correctness: null, visual_grounding: null, clarity: null,
             diagnostic_usefulness: null, unsupported_flag: null };
  });
  return o;
}
function blankTiming() {
  return {
    card_ms: { A: 0, B: 0, C: 0, D: 0 },
    task_a_ms: 0, task_b_ms: 0, total_ms: 0,
    task_a_first_started_at: null, task_a_last_stopped_at: null,
    task_b_first_started_at: null, task_b_last_stopped_at: null,
    dropped_idle_ms: 0, dropped_idle_segments: 0, segments: [],
  };
}
function blank(item) {
  const tb = {};
  LABELS.forEach((l) => {
    const ex = item.explanations[l];
    if (ex && ex.evidence) tb[l] = ex.evidence.map((e) => ({
      part_id: e.part_id, localization_accuracy: null, sufficiency: null }));
  });
  return {
    sample_id: item.sample_id, order: item.order,
    task_a: blankTaskA(), task_b: tb, timing: blankTiming(),
    // Set true the FIRST moment Task B reveals (i.e. the moment all 3 Task-A sets become
    // complete). Once true, Task A becomes permanently non-editable for this sample --
    // this is intentional and NOT reversible via "Edit / redo annotation", so that seeing
    // Evidence regions in Task B can never retroactively contaminate the
    // independently-recorded Task-A judgments (anchoring-bias prevention).
    task_a_locked: false,
    technical_issue: null, technical_note: '', skipped_for_now: false, status: 'pending',
    first_started_at: null, first_completed_at: null, last_modified_at: null, revision_count: 0,
  };
}

/* ---------------- timing instrumentation (pilot workload measurement) ----------------
 * A "segment" is the current thing being timed: either a specific Task-A explanation
 * card (kind:'taskA', label:A-D) or the whole Task-B panel (kind:'taskB'). Only one
 * segment runs at a time. flushTiming() closes it out into the record's running totals;
 * startTiming() flushes whatever was running, then opens a new segment. Segments longer
 * than 30 minutes are dropped (not counted) as an "idle tab left open" guard rather than
 * inflating the estimate -- this is a best-effort PILOT measurement, not lab-grade.
 */
const TIMING_MAX_SEGMENT_MS = 30 * 60 * 1000;
function flushTiming(stopReason = 'transition') {
  if (!S || !S.timingSeg) return Promise.resolve();
  const seg = S.timingSeg; S.timingSeg = null;
  const r = S.ann[seg.sampleId];
  if (!r) return Promise.resolve();
  const endedAt = Date.now();
  const elapsed = endedAt - seg.startedAt;
  if (elapsed <= 0) return Promise.resolve();
  r.timing ||= blankTiming();
  r.timing.segments ||= [];
  const dropped = elapsed > TIMING_MAX_SEGMENT_MS;
  r.timing.segments.push({
    kind: seg.kind, label: seg.label, started_at: new Date(seg.startedAt).toISOString(),
    stopped_at: new Date(endedAt).toISOString(), elapsed_ms: elapsed,
    counted_ms: dropped ? 0 : elapsed, dropped_as_idle: dropped, stop_reason: stopReason,
  });
  if (dropped) {
    r.timing.dropped_idle_ms = (r.timing.dropped_idle_ms || 0) + elapsed;
    r.timing.dropped_idle_segments = (r.timing.dropped_idle_segments || 0) + 1;
  } else if (seg.kind === 'taskA') {
    r.timing.card_ms[seg.label] = (r.timing.card_ms[seg.label] || 0) + elapsed;
    r.timing.task_a_ms = (r.timing.task_a_ms || 0) + elapsed;
  } else if (seg.kind === 'taskB') {
    r.timing.task_b_ms = (r.timing.task_b_ms || 0) + elapsed;
  }
  if (!dropped) r.timing.total_ms = (r.timing.total_ms || 0) + elapsed;
  r.timing[seg.kind === 'taskA' ? 'task_a_last_stopped_at' : 'task_b_last_stopped_at'] =
    new Date(endedAt).toISOString();
  return persist(seg.sampleId);
}
function startTiming(kind, label) {
  flushTiming('transition');
  if (!S || !items().length || document.hidden) return;
  const startedAt = Date.now(), r = rec();
  r.timing ||= blankTiming();
  const firstKey = kind === 'taskA' ? 'task_a_first_started_at' : 'task_b_first_started_at';
  if (!r.timing[firstKey]) r.timing[firstKey] = new Date(startedAt).toISOString();
  S.timingSeg = { kind, label, sampleId: cur().sample_id, startedAt };
}
function resumeVisibleTiming() {
  if (!S || document.hidden || $('sample').classList.contains('hidden')) return;
  const r = rec();
  if (r.task_a_locked && evidenceLabels(cur()).length) startTiming('taskB', null);
  else startTiming('taskA', S.curTab);
}
const items = () => S.bundle.items;
const cur = () => items()[S.idx];
const rec = () => (S.ann[cur().sample_id] ||= blank(cur()));

function taskADone(r, label) {
  const a = r.task_a[label];
  return TASKA_QS.every((q) => Number.isInteger(a[q.key]) && a[q.key] >= 1 && a[q.key] <= 5) &&
         ['yes', 'no', 'unsure'].includes(a.unsupported_flag);
}
function allTaskADone(r) { return LABELS.every((l) => taskADone(r, l)); }
function evidenceLabels(it) { return LABELS.filter((l) => it.explanations[l] && it.explanations[l].evidence); }
function taskBDone(r, it) {
  return evidenceLabels(it).every((l) => (r.task_b[l] || []).every((e) =>
    Number.isInteger(e.localization_accuracy) && Number.isInteger(e.sufficiency)));
}
function allDone(r, it) { return allTaskADone(r) && taskBDone(r, it); }

function statusOf(it) {
  const r = S.ann[it.sample_id];
  if (!r) return 'pending';
  if (r.technical_issue) return 'tech';
  if (r.status === 'completed') return 'done';
  if (r.skipped_for_now) return 'skip';
  const any = LABELS.some((l) => TASKA_QS.some((q) => r.task_a[l][q.key] != null) || r.task_a[l].unsupported_flag != null);
  return any ? 'prog' : 'pending';
}
function counts() {
  const c = { done: 0, prog: 0, skip: 0, tech: 0, pending: 0 };
  items().forEach((it) => { c[statusOf(it)]++; });
  return c;
}

/* ---------------- dashboard ---------------- */
const LABEL_TXT = { done: 'completed', prog: 'in progress', skip: 'skipped — needs revisit',
                    tech: 'technical issue', pending: 'not started' };
const MARK = { done: '✓', prog: '◐', skip: '↺', tech: '⚑', pending: '' };

function renderDash() {
  flushTiming();
  $('tutorial').classList.add('hidden');
  renderWorkedCards();
  const c = counts(), n = items().length;
  $('dashName').textContent = S.bundle.annotator_name;
  $('dashSub').textContent = `${c.done} of ${n} samples completed`;
  $('sDone').textContent = c.done; $('sProg').textContent = c.prog;
  $('sSkip').textContent = c.skip; $('sTech').textContent = c.tech;
  $('sLeft').textContent = c.pending;
  const bar = $('bigbar'); bar.textContent = '';
  [['b-ok', c.done], ['b-prog', c.prog], ['b-skip', c.skip], ['b-tech', c.tech]]
    .forEach(([cl, v]) => {
      if (!v) return;
      const i = document.createElement('i');
      i.className = cl; i.style.width = (100 * v / n) + '%'; bar.append(i);
    });
  $('reviewSkipBtn').classList.toggle('hidden', c.skip === 0);
  $('jumpNo').max = String(n);

  const host = $('grids'); host.textContent = '';
  const BLOCK = 50;
  for (let start = 0; start < n; start += BLOCK) {
    const end = Math.min(start + BLOCK, n);
    const cells = [];
    for (let i = start; i < end; i++) {
      const st = statusOf(items()[i]);
      if (S.filter !== 'all' && S.filter !== st) continue;
      const b = document.createElement('button');
      b.className = 'numcell' + (st === 'pending' ? '' : ' ' + st);
      b.textContent = String(i + 1);
      b.title = `Sample ${i + 1} — ${LABEL_TXT[st]}`;
      b.setAttribute('aria-label', `Sample ${i + 1}, ${LABEL_TXT[st]}`);
      if (MARK[st]) {
        const m = document.createElement('span'); m.className = 'mark';
        m.textContent = MARK[st]; m.setAttribute('aria-hidden', 'true'); b.append(m);
      }
      b.addEventListener('click', () => openSample(i));
      cells.push(b);
    }
    if (!cells.length) continue;
    const blk = document.createElement('div'); blk.className = 'grid-block';
    const h = document.createElement('h3'); h.textContent = `${start + 1} – ${end}`;
    const g = document.createElement('div'); g.className = 'numgrid';
    cells.forEach((x) => g.append(x));
    blk.append(h, g); host.append(blk);
  }
  if (!host.children.length) {
    const p = document.createElement('p'); p.className = 'hint';
    p.textContent = 'No samples in this filter.'; host.append(p);
  }
  $('dash').classList.remove('hidden');
  $('sample').classList.add('hidden');
  $('donePanel').classList.add('hidden');
}

/* ---------------- sample screen ---------------- */
function renderExplanationBlocks(host, ex) {
  // Bold claim + plain explanation, one block per claim/aspect, comfortable spacing
  // between blocks -- never one long paragraph. Falls back to a single block from
  // `ex.text` only if `ex.blocks` is missing/empty (should not happen once bundles are
  // rebuilt from the current generator).
  if (ex.summary) {
    const summary = document.createElement('p');
    summary.className = 'explan-summary';
    summary.textContent = ex.summary;
    host.append(summary);
  }
  const appendBlocks = (parent, items) => {
    items.forEach((b) => {
      const blk = document.createElement('div'); blk.className = 'explan-block';
      if (b.claim) {
        const c = document.createElement('p'); c.className = 'explan-claim';
        c.textContent = b.quote_claim ? `“${b.claim}”` : b.claim;
        blk.append(c);
      }
      const t = document.createElement('p'); t.className = 'explan-text'; t.textContent = b.text;
      blk.append(t);
      parent.append(blk);
    });
  };
  const wrap = document.createElement('div'); wrap.className = 'explan-blocks';
  const hasHiddenDetails = Boolean(ex.details_blocks && ex.details_blocks.length);
  const blocks = (ex.blocks && ex.blocks.length) ? ex.blocks
    : (!hasHiddenDetails && ex.text ? [{ claim: null, text: ex.text }] : []);
  if (!blocks.length && !hasHiddenDetails) {
    const p = document.createElement('p'); p.className = 'explan-text';
    p.textContent = '(no explanation text available)'; wrap.append(p);
  } else {
    appendBlocks(wrap, blocks);
  }
  host.append(wrap);
}
function optButton(label, pressed, onClick, extra) {
  const b = document.createElement('button');
  b.className = 'opt' + (extra ? ' ' + extra : ''); b.type = 'button';
  b.textContent = label; b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
  b.addEventListener('click', onClick);
  return b;
}
function loadImage(imgEl, src) {
  const frame = imgEl.closest('.image-frame') || imgEl.closest('.evidence-imgwrap');
  const old = frame && frame.querySelector('.imgerr'); if (old) old.remove();
  imgEl.classList.remove('hidden');
  imgEl.onerror = () => {
    imgEl.classList.add('hidden');
    if (!frame) return;
    const e = document.createElement('div'); e.className = 'imgerr';
    e.textContent = 'This image could not be loaded. Please use “Report a technical issue”.';
    frame.append(e);
  };
  imgEl.src = src;
}

function openSample(i) {
  flushTiming();
  S.idx = Math.max(0, Math.min(i, items().length - 1));
  localStorage.setItem(dbName(S.bundle) + ':idx', String(S.idx));
  const it = cur(), r = rec();
  if (!r.first_started_at) { r.first_started_at = new Date().toISOString(); persist(it.sample_id); }
  S.editing = r.status !== 'completed';
  S.curTab = LABELS.find((l) => !taskADone(r, l)) || 'A';
  startTiming('taskA', S.curTab);
  renderSample();
  $('dash').classList.add('hidden');
  $('donePanel').classList.add('hidden');
  $('tutorial').classList.add('hidden');
  $('sample').classList.remove('hidden');
  window.scrollTo({ top: 0 });
}

function renderSample() {
  const it = cur(), r = rec(), c = counts();
  textAll(['posNow'], String(S.idx + 1));
  textAll(['posAll'], String(items().length));
  textAll(['posNowB'], String(S.idx + 1));
  textAll(['posAllB'], String(items().length));
  $('posDone').textContent = `${c.done} completed`;
  $('capText').textContent = it.text;
  loadImage($('img'), it.image);
  setAll(['prevBtn', 'prevBtnB'], 'disabled', S.idx === 0);
  setAll(['nextBtn', 'nextBtnB'], 'disabled', S.idx === items().length - 1);
  const done = r.status === 'completed';
  $('reviewBar').classList.toggle('hidden', !done || S.editing);
  $('completeBtn').textContent = done && S.editing ? 'Save revision' : 'Save & complete';
  $('techBox').classList.add('hidden');
  $('errS').classList.add('hidden');
  renderTaskTabs();
  renderExplanCard();
  renderTaskB();
}

function renderTaskTabs() {
  const it = cur(), r = rec();
  const host = $('tasktabs'); host.textContent = '';
  LABELS.forEach((l) => {
    const b = document.createElement('button');
    b.className = 'tasktab' + (taskADone(r, l) ? ' tt-done' : '');
    b.setAttribute('aria-current', String(l === S.curTab));
    const n = document.createElement('span'); n.className = 'ttn'; n.textContent = `Explanation ${l}`;
    const k = document.createElement('span'); k.className = 'ttk';
    k.textContent = taskADone(r, l) ? 'rated' : 'not rated';
    b.append(n, k);
    b.addEventListener('click', () => {
      if (l !== S.curTab) startTiming('taskA', l);
      S.curTab = l; renderExplanCard(); renderTaskTabs();
    });
    host.append(b);
  });
}

function likertRow(host, q, current, onSet, locked) {
  // FROZEN WORDING: every one of the 5 options shows its own anchor label (not just a
  // bare number), since the 5 anchor phrases differ per question and must be exact.
  const wrap = document.createElement('div'); wrap.className = 'likert-q';
  const head = document.createElement('div'); head.className = 'likert-qhead';
  const nm = document.createElement('span'); nm.className = 'likert-qname' + (q.primary ? ' primary' : '');
  nm.textContent = q.name; head.append(nm); wrap.append(head);
  const desc = document.createElement('p'); desc.className = 'likert-qdesc'; desc.textContent = q.desc;
  wrap.append(desc);
  const col = document.createElement('div'); col.className = 'likert5col';
  for (let v = 1; v <= 5; v++) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'likertopt' + (locked ? ' locked' : '');
    b.setAttribute('aria-pressed', String(current === v));
    b.disabled = !!locked;
    const n = document.createElement('span'); n.className = 'likertopt-n'; n.textContent = String(v);
    const t = document.createElement('span'); t.className = 'likertopt-t'; t.textContent = q.anchors[v - 1];
    b.append(n, t);
    if (!locked) b.addEventListener('click', () => onSet(v));
    col.append(b);
  }
  wrap.append(col);
  host.append(wrap);
}

function renderExplanCard() {
  const it = cur(), r = rec(), l = S.curTab;
  const ex = it.explanations[l];
  const host = $('explanCard'); host.textContent = '';
  const locked = !!r.task_a_locked;
  const card = document.createElement('div'); card.className = 'explan-card';
  const lab = document.createElement('div'); lab.className = 'explan-label';
  const badge = document.createElement('span'); badge.className = 'explan-badge';
  badge.textContent = `Explanation ${l}`; lab.append(badge); card.append(lab);
  if (locked) {
    const lk = document.createElement('span'); lk.className = 'locked-badge';
    lk.textContent = 'Task A locked — Task B evidence has been revealed';
    lab.append(lk);
  }
  renderExplanationBlocks(card, ex);

  const a = r.task_a[l];
  TASKA_QS.forEach((q) => {
    likertRow(card, q, a[q.key], (v) => {
      a[q.key] = v; persist(it.sample_id); renderExplanCard(); renderTaskTabs(); renderTaskB();
    }, locked);
  });

  const flagWrap = document.createElement('div'); flagWrap.className = 'likert-q';
  const fh = document.createElement('div'); fh.className = 'likert-qhead';
  const fn = document.createElement('span'); fn.className = 'likert-qname';
  fn.textContent = UNSUPPORTED_Q.name; fh.append(fn); flagWrap.append(fh);
  const fd = document.createElement('p'); fd.className = 'likert-qdesc';
  fd.textContent = UNSUPPORTED_Q.desc;
  flagWrap.append(fd);
  const frow = document.createElement('div'); frow.className = 'flagrow';
  FLAG_OPTIONS.forEach(([v, txt2]) => {
    const fb = optButton(txt2, a.unsupported_flag === v, () => {
      a.unsupported_flag = v; persist(it.sample_id); renderExplanCard(); renderTaskTabs(); renderTaskB();
    });
    if (locked) fb.disabled = true;
    frow.append(fb);
  });
  flagWrap.append(frow); card.append(flagWrap);

  const nav = document.createElement('div'); nav.className = 'tasknav';
  const idx = LABELS.indexOf(l);
  if (idx > 0) {
    const pb = document.createElement('button'); pb.className = 'btn sm';
    pb.textContent = '← Previous explanation';
    pb.addEventListener('click', () => {
      startTiming('taskA', LABELS[idx - 1]); S.curTab = LABELS[idx - 1]; renderExplanCard(); renderTaskTabs();
    });
    nav.append(pb);
  }
  const spacer = document.createElement('div'); spacer.className = 'spacer'; nav.append(spacer);
  if (idx < LABELS.length - 1) {
    const nb = document.createElement('button'); nb.className = 'btn sm primary';
    nb.textContent = 'Next explanation →';
    nb.addEventListener('click', () => {
      startTiming('taskA', LABELS[idx + 1]); S.curTab = LABELS[idx + 1]; renderExplanCard(); renderTaskTabs();
    });
    nav.append(nb);
  }
  card.append(nav);
  host.append(card);
}

/* ---- Task B: evidence-region rating, unlocked once all 3 Task-A sets are rated ---- */
function convertBox(box, coordSystem, natW, natH) {
  const [x1, y1, x2, y2] = box;
  let left, top, w, h;
  if (coordSystem === 'normalized_0_1000_xyxy') {
    left = x1 / 1000 * 100; top = y1 / 1000 * 100;
    w = (x2 - x1) / 1000 * 100; h = (y2 - y1) / 1000 * 100;
  } else { // native_pixels_xyxy
    left = x1 / natW * 100; top = y1 / natH * 100;
    w = (x2 - x1) / natW * 100; h = (y2 - y1) / natH * 100;
  }
  const clamp = (v) => Math.max(0, Math.min(100, v));
  return { left: clamp(left), top: clamp(top), width: clamp(w), height: clamp(h) };
}

function renderTaskB() {
  const it = cur(), r = rec();
  const host = $('taskB'); host.textContent = '';
  const evLabels = evidenceLabels(it);
  if (!evLabels.length) return; // nothing to show for this sample at all

  if (!allTaskADone(r)) {
    const lock = document.createElement('div'); lock.className = 'taskb-lock';
    lock.textContent = 'Rate all 3 explanations above (Task A) to unlock the evidence-region task.';
    host.append(lock);
    return;
  }
  if (!r.task_a_locked) {
    // First moment Task B becomes visible for this sample -- lock Task A permanently so
    // seeing the evidence regions below can never retroactively change those judgments.
    r.task_a_locked = true;
    persist(it.sample_id);
    renderExplanCard(); renderTaskTabs();
  }
  if (!(S.timingSeg && S.timingSeg.kind === 'taskB' && S.timingSeg.sampleId === it.sample_id)) {
    startTiming('taskB', null);
  }

  const heading = document.createElement('h3');
  heading.style.cssText = 'font-size:13px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin:0 0 10px';
  heading.textContent = 'Task B — highlighted evidence regions';
  host.append(heading);

  evLabels.forEach((l) => {
    const ex = it.explanations[l];
    const secTitle = document.createElement('p');
    secTitle.style.cssText = 'font-weight:700;font-size:13.5px;margin:14px 0 8px';
    secTitle.textContent = `Explanation ${l} — evidence regions`;
    host.append(secTitle);

    if (!ex.evidence.length) {
      const none = document.createElement('div'); none.className = 'evidence-nobox';
      none.textContent = 'No grounded evidence region was available for this explanation on this sample.';
      host.append(none);
      return;
    }

    ex.evidence.forEach((claim, ci) => {
      const rows = r.task_b[l];
      const rr = rows[ci];
      const card = document.createElement('div'); card.className = 'evidence-claim';
      const ct = document.createElement('p'); ct.className = 'evidence-claimtext';
      ct.textContent = `Claim: “${claim.text}”`; card.append(ct);

      const boxes = claim.evidence_boxes || [];
      if (boxes.length) {
        const wrap = document.createElement('div'); wrap.className = 'evidence-imgwrap';
        const im = document.createElement('img'); im.alt = 'evidence region';
        wrap.append(im);
        loadImage(im, it.image);
        const natW = it.image_native_width, natH = it.image_native_height;
        boxes.forEach((box) => {
          const pos = convertBox(box, ex.box_coord_system, natW, natH);
          const d = document.createElement('div'); d.className = 'evidence-box';
          d.style.left = pos.left + '%'; d.style.top = pos.top + '%';
          d.style.width = pos.width + '%'; d.style.height = pos.height + '%';
          wrap.append(d);
        });
        card.append(wrap);
      } else {
        const none = document.createElement('div'); none.className = 'evidence-nobox';
        none.textContent = 'No box coordinates recorded for this claim.';
        card.append(none);
      }

      TASKB_QS.forEach((q) => {
        likertRow(card, q, rr[q.key], (v) => {
          rr[q.key] = v; persist(it.sample_id); renderTaskB();
        });
      });
      host.append(card);
    });
  });
}

/* ---------------- practice examples (read-only) ---------------- */
let TUT = { list: null, i: 0 };
async function loadTutorial() {
  if (TUT.list) return TUT.list;
  const r = await fetch('examples/tutorial_examples.json', { cache: 'no-store' });
  const j = await r.json();
  TUT.list = j.examples || [];
  return TUT.list;
}
function practiceRatingRow(host, name, rating, anchors, rationale) {
  const row = document.createElement('div'); row.className = 'prac-rating-row';
  const head = document.createElement('div'); head.className = 'prac-rating-head';
  const nm = document.createElement('span'); nm.className = 'prac-rating-name';
  nm.textContent = name;
  const val = document.createElement('span'); val.className = 'prac-rating-value';
  val.textContent = (typeof rating === 'number' && anchors) ? `${rating} — ${anchors[rating - 1]}` : String(rating);
  head.append(nm, val); row.append(head);
  const rat = document.createElement('p'); rat.className = 'prac-rating-rationale';
  rat.textContent = rationale; row.append(rat);
  host.append(row);
}
function renderPracticeRatings(host, title, questions, ratings, unsupportedQ) {
  const wrap = document.createElement('div'); wrap.className = 'prac-ratings';
  const h = document.createElement('p'); h.className = 'prac-ratings-title'; h.textContent = title;
  wrap.append(h);
  questions.forEach((q) => {
    const r = ratings[q.key];
    if (r) practiceRatingRow(wrap, q.name, r.rating, q.anchors, r.rationale);
  });
  if (unsupportedQ && ratings.unsupported_content) {
    const u = ratings.unsupported_content;
    practiceRatingRow(wrap, unsupportedQ.name, u.answer, null, u.rationale);
  }
  host.append(wrap);
}
function renderPracticeTaskB(host, ex) {
  const tb = ex.task_b; if (!tb) return;
  const heading = document.createElement('h3'); heading.className = 'prac-taskb-heading';
  heading.textContent = `Task B example — Explanation ${tb.label}`;
  host.append(heading);
  const card = document.createElement('div'); card.className = 'evidence-claim';
  const ct = document.createElement('p'); ct.className = 'evidence-claimtext';
  ct.textContent = `Claim: “${tb.claim_text}”`; card.append(ct);
  const wrap = document.createElement('div'); wrap.className = 'evidence-imgwrap';
  const im = document.createElement('img'); im.alt = 'evidence region';
  wrap.append(im); loadImage(im, ex.image);
  (tb.evidence_boxes || []).forEach((box) => {
    const pos = convertBox(box, tb.box_coord_system, ex.image_native_width, ex.image_native_height);
    const d = document.createElement('div'); d.className = 'evidence-box';
    d.style.left = pos.left + '%'; d.style.top = pos.top + '%';
    d.style.width = pos.width + '%'; d.style.height = pos.height + '%';
    wrap.append(d);
  });
  card.append(wrap);
  renderPracticeRatings(card, 'Example Task-B ratings', TASKB_QS, tb.ratings, null);
  host.append(card);
}
function renderTutorial() {
  const ex = TUT.list[TUT.i];
  textAll(['tutNow'], String(TUT.i + 1));
  textAll(['tutAll'], String(TUT.list.length));
  $('tutWalk').textContent = ex.walkthrough_note;
  $('tutText').textContent = ex.text;
  $('tutImg').src = ex.image;

  const host = $('tutExplans'); host.textContent = '';
  Object.keys(ex.explanations).forEach((l) => {
    const e = ex.explanations[l];
    const card = document.createElement('div'); card.className = 'explan-card';
    const lab = document.createElement('div'); lab.className = 'explan-label';
    const badge = document.createElement('span'); badge.className = 'explan-badge';
    badge.textContent = `Explanation ${l}`; lab.append(badge); card.append(lab);
    renderExplanationBlocks(card, e);
    if (e.ratings) renderPracticeRatings(card, 'Example Task-A ratings', TASKA_QS, e.ratings, UNSUPPORTED_Q);
    host.append(card);
  });
  if (ex.final_comparison) {
    const fc = document.createElement('div'); fc.className = 'prac-final-comparison';
    const h = document.createElement('p'); h.className = 'prac-ratings-title'; h.textContent = 'Final comparison';
    const p = document.createElement('p'); p.className = 'prac-final-comparison-text'; p.textContent = ex.final_comparison;
    fc.append(h, p); host.append(fc);
  }
  renderPracticeTaskB(host, ex);
  setAll(['tutPrev'], 'disabled', TUT.i === 0);
  setAll(['tutNext'], 'disabled', TUT.i === TUT.list.length - 1);
  $('tutDone').textContent = TUT.i === TUT.list.length - 1 ? 'Start annotating' : 'Skip the examples';
  window.scrollTo({ top: 0 });
}
function renderWorkedCards() {
  const host = $('whCards'), sec = $('workedHome');
  if (!host || !sec) return;
  if (!TUT.list || !TUT.list.length) { sec.classList.add('hidden'); return; }
  sec.classList.remove('hidden');
  host.textContent = '';
  TUT.list.forEach((ex, i) => {
    const b = document.createElement('button'); b.className = 'whcard'; b.type = 'button';
    const n = document.createElement('span'); n.className = 'whn'; n.textContent = ex.display_name;
    const m = document.createElement('span'); m.className = 'whmeta'; m.textContent = ex.walkthrough_note.slice(0, 90) + '…';
    b.append(n, m);
    b.addEventListener('click', () => openTutorial(i));
    host.append(b);
  });
}
async function openTutorial(i) {
  try { await loadTutorial(); } catch { return false; }
  if (!TUT.list.length) return false;
  TUT.i = Math.max(0, Math.min(i || 0, TUT.list.length - 1));
  $('dash').classList.add('hidden'); $('sample').classList.add('hidden');
  $('donePanel').classList.add('hidden'); $('menu').classList.add('hidden');
  $('tutorial').classList.remove('hidden');
  renderTutorial();
  return true;
}
function exitTutorial() { $('tutorial').classList.add('hidden'); renderDash(); }

/* ---------------- actions ---------------- */
function completeSample() {
  const it = cur(), r = rec();
  if (!allTaskADone(r)) {
    const missing = LABELS.filter((l) => !taskADone(r, l));
    $('errS').textContent = `Please finish rating explanation${missing.length > 1 ? 's' : ''} ${missing.join(', ')} (Task A) first.`;
    $('errS').classList.remove('hidden');
    S.curTab = missing[0]; renderExplanCard(); renderTaskTabs();
    return;
  }
  if (!taskBDone(r, it)) {
    $('errS').textContent = 'Please rate every evidence region in Task B before completing this sample.';
    $('errS').classList.remove('hidden');
    $('taskB').scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  const was = r.status === 'completed';
  if (was) r.revision_count = (r.revision_count || 0) + 1;
  else r.first_completed_at = new Date().toISOString();
  r.status = 'completed'; r.skipped_for_now = false;
  persist(it.sample_id);
  S.editing = false;
  const next = items().findIndex((x, i) => i > S.idx && statusOf(x) === 'pending');
  if (next >= 0) openSample(next); else renderDash();
}
function skipForNow() {
  const it = cur(), r = rec();
  if (r.status !== 'completed') { r.skipped_for_now = true; r.status = 'skipped_for_now'; }
  persist(it.sample_id);
  if (S.idx + 1 < items().length) { openSample(S.idx + 1); return; }
  const nxt = items().findIndex((x) => ['pending', 'prog'].includes(statusOf(x)));
  if (nxt >= 0) openSample(nxt); else renderDash();
}
function continueAnnotation() {
  const prog = items().findIndex((it) => statusOf(it) === 'prog');
  const pend = items().findIndex((it) => statusOf(it) === 'pending');
  const i = prog >= 0 ? prog : pend;
  if (i >= 0) openSample(i);
  else {
    const sk = items().findIndex((it) => statusOf(it) === 'skip');
    if (sk >= 0) openSample(sk); else showDone();
  }
}
function showDone() {
  const c = counts();
  $('doneCount').textContent = `Completed: ${c.done} / ${items().length}` +
    (c.skip ? ` · ${c.skip} skipped still require review` : '') +
    (c.tech ? ` · ${c.tech} technical issue(s)` : '');
  $('dash').classList.add('hidden'); $('sample').classList.add('hidden');
  $('donePanel').classList.remove('hidden');
}

/* ---------------- export ---------------- */
function buildExport() {
  flushTiming();
  const c = counts();
  return {
    schema_version: S.bundle.schema_version, app_version: APP_VERSION,
    content_version: CONTENT_VERSION, manifest_hash: S.bundle.manifest_hash,
    assignment_hash: S.bundle.assignment_hash,
    annotator_id: S.bundle.annotator_id, annotator_name: S.bundle.annotator_name,
    annotator_role: S.bundle.annotator_role,
    export_timestamp: new Date().toISOString(),
    assignment_size: items().length,
    completed_count: c.done, skipped_count: c.skip, technical_count: c.tech, in_progress_count: c.prog,
    annotations: items().map((it, i) => {
      const r = S.ann[it.sample_id] || blank(it);
      return {
        sample_id: it.sample_id, assignment_index: i + 1, status: statusOf(it),
        task_a: LABELS.map((l) => ({ label: l, ...r.task_a[l] })),
        task_b: evidenceLabels(it).map((l) => ({
          label: l,
          claims: (r.task_b[l] || []).map((e) => ({
            part_id: e.part_id, localization_accuracy: e.localization_accuracy,
            sufficiency: e.sufficiency })),
        })),
        technical_issue: r.technical_issue, technical_note: r.technical_note || '',
        skipped_for_now: !!r.skipped_for_now, task_a_locked: !!r.task_a_locked,
        first_started_at: r.first_started_at, first_completed_at: r.first_completed_at,
        last_modified_at: r.last_modified_at, revision_count: r.revision_count || 0,
        timing: r.timing || blankTiming(),
      };
    }),
  };
}
function download(obj, fname) {
  const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b); a.download = fname;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function stamp() {
  const d = new Date(), p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}
async function exportFinal() {
  const p = buildExport(), msg = $('menuMsg'), c = counts();
  const outstanding = c.pending + c.prog + c.skip;
  if (outstanding > 0) {
    msg.textContent = `Not finished: ${c.done} of ${p.assignment_size} completed` +
      (c.skip ? `, ${c.skip} skipped still require review` : '') +
      (c.prog ? `, ${c.prog} in progress` : '') +
      (c.pending ? `, ${c.pending} not started` : '') +
      '. Technical-issue samples are exported as they are; everything else must be completed.';
    if (c.skip) { S.filter = 'skip'; renderDash(); }
    return;
  }
  p.payload_sha256 = await sha256Hex(JSON.stringify(p.annotations));
  download(p, `explanation_quality_annotations_${p.annotator_id}_${stamp()}.json`);
  $('doneHash').textContent = 'SHA-256: ' + p.payload_sha256;
  msg.textContent = 'Final file downloaded. Please email it back.';
}

/* ---------------- boot ---------------- */
async function login() {
  const u = $('user').value.trim().toLowerCase(), p = $('pass').value, err = $('loginErr');
  err.classList.add('hidden');
  if (!u || !p) { err.textContent = 'Enter your username and passcode.'; err.classList.remove('hidden'); return; }
  // Two independent index files: the real assignment and the separate pilot-mode index.
  // A pilot account is not part of the real assignment.
  let index = { annotators: {} };
  for (const path of ['data/index.json', 'data/pilot_index.json']) {
    try {
      const j = await (await fetch(path, { cache: 'no-store' })).json();
      Object.assign(index.annotators, j.annotators || {});
    } catch { /* one index missing is fine -- e.g. before the candidate assignment exists */ }
  }
  if (!index.annotators[u]) { err.textContent = 'Unknown username or passcode.'; err.classList.remove('hidden'); return; }
  let bundle;
  try {
    const enc = await (await fetch(index.annotators[u].bundle, { cache: 'no-store' })).json();
    bundle = await decryptBundle(enc, p);
  } catch { err.textContent = 'Unknown username or passcode.'; err.classList.remove('hidden'); return; }
  if (bundle.annotator_id !== u) { err.textContent = 'Assignment mismatch.'; err.classList.remove('hidden'); return; }
  await start(bundle);
}
async function start(bundle) {
  S = { bundle, ann: {}, idx: 0, db: null, filter: 'all', editing: true, curTab: 'A', timingSeg: null };
  try { S.db = await openDB(dbName(bundle)); } catch { S.db = null; }
  if (S.db) (await idbAll(S.db)).forEach((r) => { S.ann[r.sample_id] = r; });
  else {
    const pre = dbName(bundle) + ':';
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(pre) && !k.endsWith(':idx')) {
        try { const r = JSON.parse(localStorage.getItem(k)); S.ann[r.sample_id] = r; } catch {}
      }
    }
  }
  const savedIdx = Number.parseInt(localStorage.getItem(dbName(bundle) + ':idx'), 10);
  if (Number.isInteger(savedIdx) && savedIdx >= 0 && savedIdx < items().length) S.idx = savedIdx;
  $('login').classList.add('hidden'); $('app').classList.remove('hidden');
  $('whoName').textContent = bundle.annotator_name;
  chip('ok', 'Saved');
  try { await loadTutorial(); } catch {}
  renderDash();
}

function wire() {
  $('loginBtn').addEventListener('click', login);
  $('pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });
  $('menuBtn').addEventListener('click', () => $('menu').classList.toggle('hidden'));
  $('logoutBtn').addEventListener('click', async () => {
    try { await flushTiming('logout'); } catch {}
    location.reload();
  });
  window.addEventListener('beforeunload', () => { try { flushTiming('unload'); } catch {} });
  window.addEventListener('pagehide', () => { try { flushTiming('pagehide'); } catch {} });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) flushTiming('tab_hidden');
    else resumeVisibleTiming();
  });

  $('toDash').addEventListener('click', renderDash);
  $('toDashB').addEventListener('click', renderDash);
  $('tutAgain').addEventListener('click', () => openTutorial(0));
  $('menuTut').addEventListener('click', () => openTutorial(0));
  $('tutPrev').addEventListener('click', () => { TUT.i--; renderTutorial(); });
  $('tutNext').addEventListener('click', () => { TUT.i++; renderTutorial(); });
  $('tutExit').addEventListener('click', exitTutorial);
  $('tutDone').addEventListener('click', exitTutorial);
  $('guideTutLink').addEventListener('click', (e) => { e.preventDefault(); openTutorial(0); });
  $('prevBtn').addEventListener('click', () => openSample(S.idx - 1));
  $('nextBtn').addEventListener('click', () => openSample(S.idx + 1));
  $('prevBtnB').addEventListener('click', () => openSample(S.idx - 1));
  $('nextBtnB').addEventListener('click', () => openSample(S.idx + 1));
  $('completeBtn').addEventListener('click', completeSample);
  $('skipBtn').addEventListener('click', skipForNow);
  $('editBtn').addEventListener('click', () => { S.editing = true; renderSample(); });
  $('continueBtn').addEventListener('click', continueAnnotation);
  $('reviewSkipBtn').addEventListener('click', () => {
    S.filter = 'skip'; syncFilters(); renderDash();
    const i = items().findIndex((it) => statusOf(it) === 'skip');
    if (i >= 0) openSample(i);
  });
  $('jumpBtn').addEventListener('click', jump);
  $('jumpNo').addEventListener('keydown', (e) => { if (e.key === 'Enter') jump(); });
  $('filters').addEventListener('click', (e) => {
    const b = e.target.closest('[data-f]'); if (!b) return;
    S.filter = b.dataset.f; syncFilters(); renderDash();
  });

  $('techBtn').addEventListener('click', () => {
    const host = $('techOpts'); host.textContent = '';
    const r = rec();
    TECH_REASONS.forEach(([v, lab]) => host.append(optButton(lab, r.technical_issue === v,
      () => { r.technical_issue = v; $('techBtn').click(); })));
    $('techNote').value = r.technical_note || '';
    $('techBox').classList.remove('hidden');
    $('techBox').scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  $('techCancel').addEventListener('click', () => {
    rec().technical_issue = null; $('techBox').classList.add('hidden');
  });
  $('techNote').addEventListener('input', (e) => { rec().technical_note = e.target.value; });
  $('techSave').addEventListener('click', () => {
    const r = rec(); if (!r.technical_issue) return;
    persist(cur().sample_id); renderDash();
  });

  $('backupBtn').addEventListener('click', () => {
    const p = buildExport(); p.export_kind = 'partial_backup';
    download(p, `explanation_quality_backup_${p.annotator_id}_${stamp()}.json`);
    $('menuMsg').textContent = 'Backup downloaded.';
  });
  $('importBtn').addEventListener('click', () => $('importFile').click());
  $('importFile').addEventListener('change', importBackup);
  $('finalBtn').addEventListener('click', exportFinal);
  $('doneExport').addEventListener('click', exportFinal);
}
function syncFilters() {
  [...$('filters').children].forEach((b) =>
    b.setAttribute('aria-pressed', String(b.dataset.f === S.filter)));
}
function jump() {
  const v = parseInt($('jumpNo').value, 10);
  if (!Number.isFinite(v) || v < 1 || v > items().length) { $('jumpNo').focus(); return; }
  openSample(v - 1);
}
async function importBackup(e) {
  const f = e.target.files[0]; if (!f) return;
  const msg = $('menuMsg');
  try {
    const d = JSON.parse(await f.text());
    if (d.annotator_id !== S.bundle.annotator_id) throw new Error('different annotator');
    if (d.assignment_hash !== S.bundle.assignment_hash) throw new Error('different assignment');
    const known = new Set(items().map((i) => i.sample_id));
    if (d.annotations.some((a) => !known.has(a.sample_id))) throw new Error('unknown sample ids');
    let restored = 0, skipped = 0;
    for (const a of d.annotations) {
      const it = items().find((i) => i.sample_id === a.sample_id);
      const inc = fromExport(a, it), ex = S.ann[a.sample_id];
      if (ex && ex.last_modified_at && inc.last_modified_at &&
          ex.last_modified_at > inc.last_modified_at) { skipped++; continue; }
      if (ex && ex.status === 'completed' && inc.status !== 'completed') { skipped++; continue; }
      if (ex && ex.task_a_locked) {
        inc.task_a_locked = true;
        inc.task_a = JSON.parse(JSON.stringify(ex.task_a));
      }
      S.ann[a.sample_id] = inc; await persist(a.sample_id); restored++;
    }
    renderDash();
    msg.textContent = `Imported ${restored} sample(s); kept newer local data for ${skipped}.`;
  } catch (ex) { msg.textContent = 'Import rejected: ' + ex.message; }
  e.target.value = '';
}
function fromExport(a, it) {
  const r = blank(it);
  r.technical_issue = a.technical_issue ?? null;
  r.technical_note = a.technical_note || '';
  r.skipped_for_now = !!a.skipped_for_now;
  r.task_a_locked = !!a.task_a_locked;
  r.status = a.status === 'done' ? 'completed' : (a.status || 'pending');
  if (a.status === 'skip') { r.status = 'skipped_for_now'; r.skipped_for_now = true; }
  r.first_started_at = a.first_started_at ?? null;
  r.first_completed_at = a.first_completed_at ?? null;
  r.last_modified_at = a.last_modified_at ?? null;
  r.revision_count = a.revision_count || 0;
  if (a.timing) {
    const empty = blankTiming();
    r.timing = { ...empty, ...a.timing,
                 card_ms: { ...empty.card_ms, ...(a.timing.card_ms || {}) },
                 segments: Array.isArray(a.timing.segments) ? a.timing.segments : [] };
  }
  (a.task_a || []).forEach((t) => {
    if (r.task_a[t.label]) r.task_a[t.label] = {
      diagnostic_correctness: t.diagnostic_correctness ?? null,
      visual_grounding: t.visual_grounding ?? null, clarity: t.clarity ?? null,
      diagnostic_usefulness: t.diagnostic_usefulness ?? null,
      unsupported_flag: t.unsupported_flag ?? null };
  });
  (a.task_b || []).forEach((t) => {
    if (r.task_b[t.label]) {
      const byId = new Map((t.claims || []).map((c) => [c.part_id, c]));
      r.task_b[t.label] = r.task_b[t.label].map((e) => {
        const src = byId.get(e.part_id);
        return src ? { ...e, localization_accuracy: src.localization_accuracy ?? null,
                       sufficiency: src.sufficiency ?? null } : e;
      });
    }
  });
  return r;
}
document.addEventListener('DOMContentLoaded', wire);
