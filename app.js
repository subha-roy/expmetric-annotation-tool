/* VisExMEM Human Annotation — static, no backend, no external dependency.
 *
 * Flow: login -> DASHBOARD -> sample. The dashboard is the hub; a sample is never opened
 * automatically on login. Within a sample the image is visible from the start (there is no
 * decomposition-validation step) and the overall 1-7 score unlocks only once every atomic
 * part is rated.
 *
 * Encrypted bundle -> Web Crypto -> IndexedDB. Nothing leaves the browser.
 */
'use strict';

const APP_VERSION = '5.0.0';
// Bundled parts changed (phrase-level decomposition) AND the flow changed, so the cache
// namespace must move with them: stale part-level state can never resurface.
const CONTENT_VERSION = 'decomp-phrase-v2+flow-v5-dualjudgment';

const TECH_REASONS = [
  ['image_failed', 'Image failed to load'],
  ['image_corrupt', 'Image unreadable / corrupt'],
  ['duplicate', 'Duplicate sample'],
  ['malformed_text', 'Malformed text'],
  ['app_problem', 'App problem'],
];
// Two independent judgments per atomic part: quality of the DECOMPOSITION (judged
// against the original text) and SUPPORT from the image. A part keeps its support score
// even when its decomposition is judged poor -- the two questions are not conditional on
// each other, and parts are never rewritten or removed during annotation.
const DECOMP_LABELS = [
  ['reasonable', 'Reasonable'],
  ['needs_split', 'Needs split'],
  ['needs_merge', 'Needs merge'],
  ['redundant', 'Redundant'],
  ['not_entailed', 'Not entailed'],
];
const DECOMP_VALUES = DECOMP_LABELS.map((x) => x[0]);
const validDecomp = (v) => DECOMP_VALUES.includes(v);
const OVERALL_MIN = 1, OVERALL_MAX = 5;
const OVERALL_LABEL = {
  1: 'Not aligned', 2: 'Weakly aligned', 3: 'Partially aligned',
  4: 'Well aligned', 5: 'Fully aligned',
};
const validOverall = (v) =>
  Number.isInteger(v) && v >= OVERALL_MIN && v <= OVERALL_MAX;
const $ = (id) => document.getElementById(id);
let S = null;              // {bundle, ann, idx, db, filter, editing}

/* ---------------- crypto ---------------- */
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decryptBundle(enc, password) {
  const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(password),
    'PBKDF2', false, ['deriveKey']);
  const aes = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(enc.salt), iterations: enc.iterations, hash: 'SHA-256' },
    km, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(enc.iv) }, aes,
    b64(enc.ciphertext));
  return JSON.parse(new TextDecoder().decode(pt));
}
async function sha256Hex(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/* ---------------- storage ---------------- */
function dbName(b) {
  return `visexmem_${b.annotator_id}_${b.assignment_hash.slice(0, 12)}_` +
         `${b.schema_version}_${CONTENT_VERSION}`;
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
function blank(item) {
  return {
    sample_id: item.sample_id, order: item.order,
    decomp_quality: {}, part_support: {}, overall_alignment: null,
    technical_issue: null, technical_note: '',
    skipped_for_now: false, status: 'pending',
    first_started_at: null, first_completed_at: null, last_modified_at: null,
    revision_count: 0,
  };
}
const items = () => S.bundle.items;
const cur = () => items()[S.idx];
const rec = () => (S.ann[cur().sample_id] ||= blank(cur()));

function partDone(r, p) {
  return validDecomp(r.decomp_quality[p.part_id]) &&
         r.part_support[p.part_id] !== undefined;
}
function allRated(it, r) {
  return it.parts.length > 0 && it.parts.every((p) => partDone(r, p));
}
function missingCounts(it, r) {
  return {
    decomp: it.parts.filter((p) => !validDecomp(r.decomp_quality[p.part_id])).length,
    support: it.parts.filter((p) => r.part_support[p.part_id] === undefined).length,
  };
}
function statusOf(it) {
  const r = S.ann[it.sample_id];
  if (!r) return 'pending';
  if (r.technical_issue) return 'tech';
  if (r.status === 'completed') return 'done';
  if (r.skipped_for_now) return 'skip';
  const any = Object.keys(r.part_support).length > 0 ||
              Object.keys(r.decomp_quality || {}).length > 0 ||
              r.overall_alignment != null;
  return any ? 'prog' : 'pending';
}
function counts() {
  const c = { done: 0, prog: 0, skip: 0, tech: 0, pending: 0 };
  items().forEach((it) => { c[statusOf(it)]++; });
  return c;
}

/* ---------------- dashboard ---------------- */
const LABEL = { done: 'completed', prog: 'in progress', skip: 'skipped — needs revisit',
                tech: 'technical issue', pending: 'not started' };
const MARK = { done: '✓', prog: '◐', skip: '↺', tech: '⚑', pending: '' };

function renderDash() {
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
      b.title = `Sample ${i + 1} — ${LABEL[st]}`;
      b.setAttribute('aria-label', `Sample ${i + 1}, ${LABEL[st]}`);
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
function optButton(label, pressed, onClick, extra) {
  const b = document.createElement('button');
  b.className = 'opt' + (extra ? ' ' + extra : ''); b.type = 'button';
  b.textContent = label; b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
  b.addEventListener('click', onClick);
  return b;
}
function loadImage(src) {
  const img = $('img'), frame = $('imgFrame');
  const old = frame.querySelector('.imgerr'); if (old) old.remove();
  img.classList.remove('hidden');
  img.onerror = () => {
    img.classList.add('hidden');
    const e = document.createElement('div'); e.className = 'imgerr';
    e.textContent = 'This image could not be loaded. Please use “Report a technical issue”.';
    frame.append(e);
  };
  img.src = src;
}

function openSample(i) {
  S.idx = Math.max(0, Math.min(i, items().length - 1));
  localStorage.setItem(dbName(S.bundle) + ':idx', String(S.idx));
  const it = cur(), r = rec();
  if (!r.first_started_at) { r.first_started_at = new Date().toISOString(); persist(it.sample_id); }
  S.editing = r.status !== 'completed';
  renderSample();
  $('dash').classList.add('hidden');
  $('donePanel').classList.add('hidden');
  $('sample').classList.remove('hidden');
  window.scrollTo({ top: 0 });
}

function renderSample() {
  const it = cur(), r = rec(), c = counts();
  $('posNow').textContent = String(S.idx + 1);
  $('posAll').textContent = String(items().length);
  $('posDone').textContent = `${c.done} completed`;
  $('capText').textContent = it.text;
  loadImage(it.image);
  $('prevBtn').disabled = S.idx === 0;
  $('nextBtn').disabled = S.idx === items().length - 1;
  const done = r.status === 'completed';
  $('reviewBar').classList.toggle('hidden', !done || S.editing);
  $('completeBtn').textContent = done && S.editing ? 'Save revision' : 'Save & complete';
  $('techBox').classList.add('hidden');
  $('errS').classList.add('hidden');
  renderParts();
  renderOverall();
}

/* Ratings repaint in place: selecting a score must not scroll or jump the panel. */
function renderParts() {
  const it = cur(), r = rec();
  const host = $('parts'); host.textContent = '';
  it.parts.forEach((p) => {
    const d = document.createElement('div');
    d.className = 'part' + (partDone(r, p) ? ' answered' : '');
    const top = document.createElement('div'); top.className = 'part-top';
    const tg = document.createElement('span'); tg.className = 'tag'; tg.textContent = p.part_type;
    const cl = document.createElement('div'); cl.className = 'claim'; cl.textContent = p.atomic_claim;
    top.append(tg, cl); d.append(top);

    // row 1 -- decomposition quality, judged against the ORIGINAL TEXT
    const r1 = document.createElement('div'); r1.className = 'jrow';
    const l1 = document.createElement('span'); l1.className = 'jlab'; l1.textContent = 'Decomposition';
    l1.title = 'Is this a good atomic unit of the original text?';
    const o1 = document.createElement('div'); o1.className = 'opts';
    DECOMP_LABELS.forEach(([v, lab]) => {
      o1.append(optButton(lab, r.decomp_quality[p.part_id] === v, () => {
        r.decomp_quality[p.part_id] = v; persist(it.sample_id); repaint();
      }, 'dq'));
    });
    r1.append(l1, o1); d.append(r1);

    // row 2 -- image support, judged against the IMAGE
    const r2 = document.createElement('div'); r2.className = 'jrow';
    const l2 = document.createElement('span'); l2.className = 'jlab'; l2.textContent = 'Image support';
    l2.title = 'How strongly does the image support this statement?';
    const o2 = document.createElement('div'); o2.className = 'opts';
    const set = (v) => { r.part_support[p.part_id] = v; persist(it.sample_id); repaint(); };
    for (let v = 0; v <= 4; v++) {
      o2.append(optButton(String(v), r.part_support[p.part_id] === v, () => set(v), 'num'));
    }
    o2.append(optButton('Cannot judge', r.part_support[p.part_id] === 'cannot_judge',
      () => set('cannot_judge'), 'cj'));
    r2.append(l2, o2); d.append(r2);

    host.append(d);
  });
}

function repaint() {
  const it = cur(), r = rec();
  [...$('parts').children].forEach((card, i) => {
    const p = it.parts[i];
    card.classList.toggle('answered', partDone(r, p));
    const rows = card.querySelectorAll('.jrow');
    rows[0].querySelectorAll('.opt').forEach((b, k) => {
      b.setAttribute('aria-pressed', String(r.decomp_quality[p.part_id] === DECOMP_VALUES[k]));
    });
    rows[1].querySelectorAll('.opt').forEach((b, k) => {
      const v = k <= 4 ? k : 'cannot_judge';
      b.setAttribute('aria-pressed', String(r.part_support[p.part_id] === v));
    });
  });
  renderOverall();
}

function renderOverall() {
  const it = cur(), r = rec(), ready = allRated(it, r);
  $('overall').classList.toggle('locked', !ready);
  $('ovLock').classList.toggle('hidden', ready);
  $('ovBody').classList.toggle('hidden', !ready);
  const lab = $('ovChosen');
  lab.textContent = validOverall(r.overall_alignment)
    ? `${r.overall_alignment} — ${OVERALL_LABEL[r.overall_alignment]}` : '';
  if (!ready) return;
  const sc = $('ovScale'); sc.textContent = '';
  // FINAL overall scale is 1-5. Anything outside that is not offered and is rejected on
  // the way in, so a stale 1-7 value can never enter a record.
  for (let v = OVERALL_MIN; v <= OVERALL_MAX; v++) {
    sc.append(optButton(String(v), r.overall_alignment === v, () => {
      r.overall_alignment = validOverall(v) ? v : null;
      persist(cur().sample_id); renderOverall();
    }, 'num'));
  }
}

/* ---------------- actions ---------------- */
function completeSample() {
  const it = cur(), r = rec();
  const m = missingCounts(it, r);
  if (m.decomp || m.support) {
    const bits = [];
    if (m.decomp) bits.push(`${m.decomp} without a decomposition judgement`);
    if (m.support) bits.push(`${m.support} without an image-support score`);
    $('errS').textContent = `Every statement needs both judgements — ${bits.join(' and ')}.`;
    $('errS').classList.remove('hidden');
    const bad = it.parts.findIndex((p) => !partDone(r, p));
    if (bad >= 0) $('parts').children[bad].scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  if (r.overall_alignment == null) {
    $('errS').textContent = 'Please give the overall 1–7 judgement at the bottom.';
    $('errS').classList.remove('hidden');
    $('overall').scrollIntoView({ behavior: 'smooth', block: 'center' }); return;
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
  renderDash();
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
  $('doneCount').textContent =
    `Completed: ${c.done} / ${items().length}` +
    (c.skip ? ` · ${c.skip} skipped still require review` : '') +
    (c.tech ? ` · ${c.tech} technical issue(s)` : '');
  $('dash').classList.add('hidden'); $('sample').classList.add('hidden');
  $('donePanel').classList.remove('hidden');
}

/* ---------------- export ---------------- */
function buildExport() {
  const c = counts();
  return {
    schema_version: S.bundle.schema_version, app_version: APP_VERSION,
    content_version: CONTENT_VERSION,
    benchmark_manifest_hash: S.bundle.benchmark_manifest_hash,
    assignment_hash: S.bundle.assignment_hash,
    annotator_id: S.bundle.annotator_id, annotator_name: S.bundle.annotator_name,
    annotator_role: S.bundle.annotator_role,
    export_timestamp: new Date().toISOString(),
    assignment_size: items().length,
    completed_count: c.done, skipped_count: c.skip, technical_count: c.tech,
    in_progress_count: c.prog,
    annotations: items().map((it, i) => {
      const r = S.ann[it.sample_id] || blank(it);
      return {
        sample_id: it.sample_id, assignment_index: i + 1, status: statusOf(it),
        parts: it.parts.map((p) => ({
          part_id: p.part_id, part_index: p.part_index,
          text: p.atomic_claim, type: p.part_type,
          decomp_quality: validDecomp(r.decomp_quality[p.part_id])
            ? r.decomp_quality[p.part_id] : null,
          support_score: r.part_support[p.part_id] === 'cannot_judge' ? null
            : (r.part_support[p.part_id] ?? null),
          support_cannot_judge: r.part_support[p.part_id] === 'cannot_judge',
        })),
        human_overall_alignment_1_to_5:
          validOverall(r.overall_alignment) ? r.overall_alignment : null,
        technical_issue: r.technical_issue, technical_note: r.technical_note || '',
        skipped_for_now: !!r.skipped_for_now,
        first_started_at: r.first_started_at, first_completed_at: r.first_completed_at,
        last_modified_at: r.last_modified_at, revision_count: r.revision_count || 0,
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
    msg.textContent =
      `Not finished: ${c.done} of ${p.assignment_size} completed` +
      (c.skip ? `, ${c.skip} skipped still require review` : '') +
      (c.prog ? `, ${c.prog} in progress` : '') +
      (c.pending ? `, ${c.pending} not started` : '') +
      '. Technical-issue samples are exported as they are; everything else must be completed.';
    if (c.skip) { S.filter = 'skip'; renderDash(); }
    return;
  }
  p.payload_sha256 = await sha256Hex(JSON.stringify(p.annotations));
  download(p, `visexmem_annotations_${p.annotator_id}_${stamp()}.json`);
  $('doneHash').textContent = 'SHA-256: ' + p.payload_sha256;
  msg.textContent = 'Final file downloaded. Please email it back.';
}

/* ---------------- boot ---------------- */
async function login() {
  const u = $('user').value.trim().toLowerCase(), p = $('pass').value, err = $('loginErr');
  err.classList.add('hidden');
  if (!u || !p) { err.textContent = 'Enter your username and passcode.'; err.classList.remove('hidden'); return; }
  let index;
  try { index = await (await fetch('data/index.json', { cache: 'no-store' })).json(); }
  catch { err.textContent = 'Could not load the assignment index.'; err.classList.remove('hidden'); return; }
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
  S = { bundle, ann: {}, idx: 0, db: null, filter: 'all', editing: true };
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
  $('login').classList.add('hidden'); $('app').classList.remove('hidden');
  $('whoName').textContent = bundle.annotator_name;
  chip('ok', 'Saved');
  renderDash();                       // always land on the dashboard, never a sample
}

function wire() {
  $('loginBtn').addEventListener('click', login);
  $('pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });
  $('menuBtn').addEventListener('click', () => $('menu').classList.toggle('hidden'));
  $('logoutBtn').addEventListener('click', () => location.reload());

  $('toDash').addEventListener('click', renderDash);
  $('prevBtn').addEventListener('click', () => openSample(S.idx - 1));
  $('nextBtn').addEventListener('click', () => openSample(S.idx + 1));
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

  // technical issue
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

  // backup / import / export
  $('backupBtn').addEventListener('click', () => {
    const p = buildExport(); p.export_kind = 'partial_backup';
    download(p, `visexmem_backup_${p.annotator_id}_${stamp()}.json`);
    $('menuMsg').textContent = 'Backup downloaded.';
  });
  $('importBtn').addEventListener('click', () => $('importFile').click());
  $('importFile').addEventListener('change', importBackup);
  $('finalBtn').addEventListener('click', exportFinal);
  $('doneExport').addEventListener('click', exportFinal);

  // keyboard: 0-4 and c rate the FOCUSED part only, never a blind global action
  document.addEventListener('keydown', (e) => {
    if (/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '')) return;
    if ($('sample').classList.contains('hidden')) return;
    const card = document.activeElement?.closest?.('.part');
    if (!card) return;
    const k = e.key.toLowerCase();
    const idx = '01234'.indexOf(k);
    if (idx >= 0 || k === 'c') {
      e.preventDefault();
      const support = card.querySelectorAll('.jrow')[1].querySelectorAll('.opt');
      (idx >= 0 ? support[idx] : support[5]).click();
    }
  });
}
function syncFilters() {
  [...$('filters').children].forEach((b) =>
    b.setAttribute('aria-pressed', String(b.dataset.f === S.filter)));
}
function jump() {
  const v = parseInt($('jumpNo').value, 10);
  if (!Number.isFinite(v) || v < 1 || v > items().length) {
    $('jumpNo').focus(); return;
  }
  openSample(v - 1);
}
async function importBackup(e) {
  const f = e.target.files[0]; if (!f) return;
  const msg = $('menuMsg');
  try {
    const d = JSON.parse(await f.text());
    if (d.annotator_id !== S.bundle.annotator_id) throw new Error('different annotator');
    if (d.assignment_hash !== S.bundle.assignment_hash) throw new Error('different assignment');
    if (d.schema_version !== S.bundle.schema_version) throw new Error('different schema version');
    const known = new Set(items().map((i) => i.sample_id));
    if (d.annotations.some((a) => !known.has(a.sample_id))) throw new Error('unknown sample ids');
    let restored = 0, skipped = 0;
    for (const a of d.annotations) {
      const it = items().find((i) => i.sample_id === a.sample_id);
      const inc = fromExport(a, it), ex = S.ann[a.sample_id];
      if (ex && ex.last_modified_at && inc.last_modified_at &&
          ex.last_modified_at > inc.last_modified_at) { skipped++; continue; }
      if (ex && ex.status === 'completed' && inc.status !== 'completed') { skipped++; continue; }
      S.ann[a.sample_id] = inc; await persist(a.sample_id); restored++;
    }
    renderDash();
    msg.textContent = `Imported ${restored} sample(s); kept newer local data for ${skipped}.`;
  } catch (ex) { msg.textContent = 'Import rejected: ' + ex.message; }
  e.target.value = '';
}
function fromExport(a, it) {
  const r = blank(it);
  const _ov = a.human_overall_alignment_1_to_5 ?? a.overall_alignment ?? null;
  r.overall_alignment = validOverall(_ov) ? _ov : null;
  r.technical_issue = a.technical_issue ?? null;
  r.technical_note = a.technical_note || '';
  r.skipped_for_now = !!a.skipped_for_now;
  r.status = a.status === 'done' ? 'completed' : (a.status || 'pending');
  if (a.status === 'skip') { r.status = 'skipped_for_now'; r.skipped_for_now = true; }
  r.first_started_at = a.first_started_at ?? null;
  r.first_completed_at = a.first_completed_at ?? null;
  r.last_modified_at = a.last_modified_at ?? null;
  r.revision_count = a.revision_count || 0;
  // accepts the v5 `parts` shape and the earlier `part_support` shape
  (a.parts || a.part_support || []).forEach((p) => {
    if (validDecomp(p.decomp_quality)) r.decomp_quality[p.part_id] = p.decomp_quality;
    const cj = p.support_cannot_judge ?? p.atomic_cannot_judge;
    const sc = p.support_score ?? p.human_atomic_support_0_to_4;
    if (cj) r.part_support[p.part_id] = 'cannot_judge';
    else if (sc != null) r.part_support[p.part_id] = sc;
  });
  return r;
}
document.addEventListener('DOMContentLoaded', wire);
