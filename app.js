/* VisExMEM Human Annotation — static, no backend, no external dependencies.
 *
 * Data flow: encrypted bundle -> Web Crypto decrypt (PBKDF2 + AES-GCM) -> IndexedDB.
 * Nothing is sent anywhere; there is no analytics and no network call after load.
 *
 * Protocol order is enforced, not merely suggested: the image element is not given a
 * src until Phase A is confirmed, so caption-only decomposition cannot be contaminated
 * by seeing the image, and the holistic 1-7 score is taken before any per-part rating.
 */
'use strict';

const APP_VERSION = '1.0.0';
const DEC_LABELS = [
  ['reasonable', 'Reasonable'],
  ['needs_split', 'Needs split'],
  ['needs_merge', 'Needs merge'],
  ['redundant', 'Redundant'],
  ['not_entailed', 'Not entailed by the text'],
];
const TECH_REASONS = [
  ['image_failed', 'Image failed to load'],
  ['image_corrupt', 'Image unreadable / corrupt'],
  ['duplicate', 'Duplicate sample'],
  ['malformed_text', 'Malformed text'],
  ['app_problem', 'App problem'],
];
const $ = (id) => document.getElementById(id);

let S = null;   // {bundle, ann:{}, idx, db}

/* ---------------- crypto ---------------- */
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function decryptBundle(enc, password) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password),
    'PBKDF2', false, ['deriveKey']);
  const aes = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(enc.salt), iterations: enc.iterations, hash: 'SHA-256' },
    key, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(enc.iv) }, aes,
    b64(enc.ciphertext));
  return JSON.parse(new TextDecoder().decode(pt));
}

async function sha256Hex(str) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/* ---------------- storage (IndexedDB, localStorage fallback) ---------------- */
function dbName(b) { return `visexmem_${b.annotator_id}_${b.assignment_hash.slice(0, 12)}_${b.schema_version}`; }

function openDB(name) {
  return new Promise((res, rej) => {
    const r = indexedDB.open(name, 1);
    r.onupgradeneeded = () => r.result.createObjectStore('ann', { keyPath: 'sample_id' });
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
function idbPut(db, rec) {
  return new Promise((res, rej) => {
    const t = db.transaction('ann', 'readwrite');
    t.objectStore('ann').put(rec);
    t.oncomplete = res; t.onerror = () => rej(t.error);
  });
}
function idbAll(db) {
  return new Promise((res, rej) => {
    const t = db.transaction('ann', 'readonly').objectStore('ann').getAll();
    t.onsuccess = () => res(t.result || []); t.onerror = () => rej(t.error);
  });
}

function chip(state, text) {
  const c = $('saveChip');
  c.className = 'save-chip ' + (state || '');
  c.textContent = text;
}

async function persist(sid) {
  const rec = S.ann[sid];
  if (!rec) return;
  rec.updated_at = new Date().toISOString();
  chip('busy', 'Saving…');
  try {
    if (S.db) await idbPut(S.db, rec);
    else localStorage.setItem(dbName(S.bundle) + ':' + sid, JSON.stringify(rec));
    chip('ok', 'Saved');
  } catch (e) {
    chip('err', 'Error saving');
    console.error(e);
  }
}

/* ---------------- annotation record ---------------- */
function blank(item) {
  return {
    sample_id: item.sample_id, order: item.order,
    decomposition: {}, missing_information: null, decomposition_note: '',
    holistic_alignment_1_to_7: null,
    part_support: {}, technical_issue: null, technical_note: '',
    phaseA_completed_at: null, phaseB_completed_at: null, phaseC_completed_at: null,
    updated_at: null,
  };
}
const cur = () => S.bundle.items[S.idx];
const rec = () => (S.ann[cur().sample_id] ||= blank(cur()));

function isComplete(r, item) {
  if (!r) return false;
  if (r.technical_issue) return true;
  if (!r.phaseA_completed_at || !r.phaseB_completed_at || !r.phaseC_completed_at) return false;
  if (item.parts.some((p) => !r.decomposition[p.part_id])) return false;
  if (r.missing_information == null) return false;
  if (r.holistic_alignment_1_to_7 == null) return false;
  return !item.parts.some((p) => r.part_support[p.part_id] === undefined);
}

function refreshProgress() {
  const done = S.bundle.items.filter((it) => isComplete(S.ann[it.sample_id], it)).length;
  const n = S.bundle.items.length;
  $('progTxt').textContent = `${done} / ${n}`;
  $('progBar').style.width = (100 * done / n).toFixed(1) + '%';
  return done;
}

/* ---------------- rendering ---------------- */
function optButton(label, pressed, onClick, extraClass) {
  const b = document.createElement('button');
  b.className = 'opt' + (extraClass ? ' ' + extraClass : '');
  b.type = 'button'; b.textContent = label;
  b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
  b.addEventListener('click', onClick);
  return b;
}

function show(phase) {
  ['phaseA', 'phaseB', 'phaseC', 'techPanel', 'donePanel'].forEach((p) =>
    $(p).classList.toggle('hidden', p !== phase));
  window.scrollTo({ top: 0, behavior: 'instant' });
}

function renderA() {
  const it = cur(), r = rec();
  $('aText').textContent = it.text;
  const host = $('aParts'); host.textContent = '';
  it.parts.forEach((p) => {
    const d = document.createElement('div'); d.className = 'part';
    const top = document.createElement('div'); top.className = 'part-top';
    const tg = document.createElement('span'); tg.className = 'tag'; tg.textContent = p.part_type;
    const cl = document.createElement('div'); cl.className = 'claim'; cl.textContent = p.atomic_claim;
    top.append(tg, cl); d.append(top);
    const opts = document.createElement('div'); opts.className = 'opts';
    DEC_LABELS.forEach(([v, lab]) => {
      opts.append(optButton(lab, r.decomposition[p.part_id] === v, () => {
        r.decomposition[p.part_id] = v; persist(it.sample_id); renderA();
      }));
    });
    d.append(opts); host.append(d);
  });
  [...$('missOpts').children].forEach((b) =>
    b.setAttribute('aria-pressed', String(r.missing_information === b.dataset.miss)));
  $('missNoteWrap').classList.toggle('hidden', r.missing_information !== 'yes');
  $('missNote').value = r.decomposition_note || '';
  $('errA').classList.add('hidden');
  $('stepA').className = 'step';
  show('phaseA');
}

function loadImage(imgEl, wrapEl, src) {
  imgEl.classList.remove('hidden');
  const old = wrapEl.querySelector('.imgerr'); if (old) old.remove();
  imgEl.onerror = () => {
    imgEl.classList.add('hidden');
    const e = document.createElement('div'); e.className = 'imgerr';
    e.textContent = 'This image could not be loaded. Please use “Report a technical issue”.';
    wrapEl.append(e);
  };
  imgEl.src = src;
}

function renderB() {
  const it = cur(), r = rec();
  $('bText').textContent = it.text;
  loadImage($('imgB'), $('imgWrapB'), it.image);
  const sc = $('holScale'); sc.textContent = '';
  for (let v = 1; v <= 7; v++) {
    sc.append(optButton(String(v), r.holistic_alignment_1_to_7 === v, () => {
      r.holistic_alignment_1_to_7 = v; persist(it.sample_id); renderB();
    }, 'num'));
  }
  $('errB').classList.add('hidden');
  show('phaseB');
}

function renderC() {
  const it = cur(), r = rec();
  $('cText').textContent = it.text;
  loadImage($('imgC'), $('imgWrapC'), it.image);
  const host = $('cParts'); host.textContent = '';
  it.parts.forEach((p) => {
    const d = document.createElement('div'); d.className = 'part';
    const top = document.createElement('div'); top.className = 'part-top';
    const tg = document.createElement('span'); tg.className = 'tag'; tg.textContent = p.part_type;
    const cl = document.createElement('div'); cl.className = 'claim'; cl.textContent = p.atomic_claim;
    top.append(tg, cl); d.append(top);
    const opts = document.createElement('div'); opts.className = 'opts';
    for (let v = 0; v <= 4; v++) {
      opts.append(optButton(String(v), r.part_support[p.part_id] === v, () => {
        r.part_support[p.part_id] = v; persist(it.sample_id); renderC();
      }, 'num'));
    }
    opts.append(optButton('Cannot judge', r.part_support[p.part_id] === 'cannot_judge', () => {
      r.part_support[p.part_id] = 'cannot_judge'; persist(it.sample_id); renderC();
    }, 'cj'));
    d.append(opts); host.append(d);
  });
  $('prevBtn').disabled = S.idx === 0;
  $('errC').classList.add('hidden');
  show('phaseC');
}

function renderTech() {
  const r = rec();
  const host = $('techOpts'); host.textContent = '';
  TECH_REASONS.forEach(([v, lab]) => host.append(optButton(lab, r.technical_issue === v, () => {
    r.technical_issue = v; renderTech();
  })));
  $('techNote').value = r.technical_note || '';
  show('techPanel');
}

function goto(i) {
  S.idx = Math.max(0, Math.min(i, S.bundle.items.length - 1));
  localStorage.setItem(dbName(S.bundle) + ':idx', String(S.idx));
  const r = rec();
  refreshProgress();
  if (r.phaseB_completed_at) renderC();
  else if (r.phaseA_completed_at) renderB();
  else renderA();
}

function nextSample() {
  const all = S.bundle.items.every((it) => isComplete(S.ann[it.sample_id], it));
  if (all) { refreshProgress(); showDone(); return; }
  let i = S.idx;
  for (let k = 1; k <= S.bundle.items.length; k++) {
    const j = (S.idx + k) % S.bundle.items.length;
    if (!isComplete(S.ann[S.bundle.items[j].sample_id], S.bundle.items[j])) { i = j; break; }
  }
  goto(i);
}

function showDone() {
  const n = S.bundle.items.length;
  $('doneCount').textContent = `Completed: ${refreshProgress()} / ${n}`;
  show('donePanel');
}

/* ---------------- export ---------------- */
function buildExport() {
  const items = S.bundle.items;
  return {
    schema_version: S.bundle.schema_version, app_version: APP_VERSION,
    benchmark_manifest_hash: S.bundle.benchmark_manifest_hash,
    assignment_hash: S.bundle.assignment_hash,
    annotator_id: S.bundle.annotator_id, annotator_name: S.bundle.annotator_name,
    annotator_role: S.bundle.annotator_role,
    export_timestamp: new Date().toISOString(),
    assignment_size: items.length,
    completed_count: items.filter((it) => isComplete(S.ann[it.sample_id], it)).length,
    annotations: items.map((it) => {
      const r = S.ann[it.sample_id] || blank(it);
      return {
        sample_id: it.sample_id, order: it.order,
        decomposition: it.parts.map((p) => ({
          part_id: p.part_id, part_index: p.part_index,
          decomposition_label: r.decomposition[p.part_id] ?? null,
          human_atomic_support_0_to_4:
            r.part_support[p.part_id] === 'cannot_judge' ? null
              : (r.part_support[p.part_id] ?? null),
          atomic_cannot_judge: r.part_support[p.part_id] === 'cannot_judge',
        })),
        missing_visual_information: r.missing_information,
        decomposition_note: r.decomposition_note || '',
        human_overall_alignment_1_to_7: r.holistic_alignment_1_to_7,
        technical_issue: r.technical_issue, technical_note: r.technical_note || '',
        phaseA_completed_at: r.phaseA_completed_at,
        phaseB_completed_at: r.phaseB_completed_at,
        phaseC_completed_at: r.phaseC_completed_at,
      };
    }),
  };
}

function download(obj, fname) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = fname;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function stamp() {
  const d = new Date(), p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

async function exportFinal() {
  const payload = buildExport();
  const msg = $('menuMsg');
  if (payload.completed_count < payload.assignment_size) {
    msg.textContent = `Not finished yet — ${payload.completed_count} of ${payload.assignment_size} complete. ` +
      `Use “Download backup” for a partial file, or “Go to first unfinished”.`;
    return;
  }
  payload.payload_sha256 = await sha256Hex(JSON.stringify(payload.annotations));
  download(payload, `visexmem_annotations_${payload.annotator_id}_${stamp()}.json`);
  $('doneHash').textContent = 'SHA-256: ' + payload.payload_sha256;
  msg.textContent = 'Final file downloaded. Please email it back.';
}

/* ---------------- boot ---------------- */
async function login() {
  const u = $('user').value.trim().toLowerCase();
  const p = $('pass').value;
  const err = $('loginErr');
  err.classList.add('hidden');
  if (!u || !p) { err.textContent = 'Enter your username and access code.'; err.classList.remove('hidden'); return; }
  let index;
  try { index = await (await fetch('data/index.json', { cache: 'no-store' })).json(); }
  catch { err.textContent = 'Could not load assignment index.'; err.classList.remove('hidden'); return; }
  if (!index.annotators[u]) { err.textContent = 'Unknown username or access code.'; err.classList.remove('hidden'); return; }
  let bundle;
  try {
    const enc = await (await fetch(index.annotators[u].bundle, { cache: 'no-store' })).json();
    bundle = await decryptBundle(enc, p);
  } catch {
    err.textContent = 'Unknown username or access code.'; err.classList.remove('hidden'); return;
  }
  if (bundle.annotator_id !== u) { err.textContent = 'Assignment mismatch.'; err.classList.remove('hidden'); return; }
  await start(bundle);
}

async function start(bundle) {
  S = { bundle, ann: {}, idx: 0, db: null };
  try { S.db = await openDB(dbName(bundle)); } catch { S.db = null; }
  if (S.db) (await idbAll(S.db)).forEach((r) => { S.ann[r.sample_id] = r; });
  else {
    const pre = dbName(bundle) + ':';
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k.startsWith(pre) && !k.endsWith(':idx')) {
        try { const r = JSON.parse(localStorage.getItem(k)); S.ann[r.sample_id] = r; } catch {}
      }
    }
  }
  sessionStorage.setItem('vx_user', bundle.annotator_id);
  $('login').classList.add('hidden'); $('app').classList.remove('hidden');
  $('whoName').textContent = bundle.annotator_name;
  chip('ok', 'Saved');
  const saved = parseInt(localStorage.getItem(dbName(bundle) + ':idx') || '0', 10);
  refreshProgress();
  if (S.bundle.items.every((it) => isComplete(S.ann[it.sample_id], it))) showDone();
  else goto(Number.isFinite(saved) ? saved : 0);
}

function wire() {
  $('loginBtn').addEventListener('click', login);
  $('pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });

  $('menuBtn').addEventListener('click', () => $('menu').classList.toggle('hidden'));
  $('logoutBtn').addEventListener('click', () => location.reload());

  // Phase A -> B
  $('missOpts').addEventListener('click', (e) => {
    const b = e.target.closest('[data-miss]'); if (!b) return;
    rec().missing_information = b.dataset.miss; persist(cur().sample_id); renderA();
  });
  $('missNote').addEventListener('input', (e) => {
    rec().decomposition_note = e.target.value; persist(cur().sample_id);
  });
  $('confirmA').addEventListener('click', () => {
    const it = cur(), r = rec();
    const miss = it.parts.filter((p) => !r.decomposition[p.part_id]).length;
    if (miss || r.missing_information == null) {
      $('errA').textContent = miss
        ? `Please judge all statements — ${miss} still unanswered.`
        : 'Please answer the missing-information question.';
      $('errA').classList.remove('hidden'); return;
    }
    if (!r.phaseA_completed_at) r.phaseA_completed_at = new Date().toISOString();
    persist(it.sample_id); renderB();
  });

  // Phase B -> C
  $('backB').addEventListener('click', () => renderA());
  $('confirmB').addEventListener('click', () => {
    const r = rec();
    if (r.holistic_alignment_1_to_7 == null) {
      $('errB').textContent = 'Please give an overall 1–7 judgement.';
      $('errB').classList.remove('hidden'); return;
    }
    if (!r.phaseB_completed_at) r.phaseB_completed_at = new Date().toISOString();
    persist(cur().sample_id); renderC();
  });

  // Phase C -> save
  $('prevBtn').addEventListener('click', () => goto(S.idx - 1));
  $('saveNext').addEventListener('click', () => {
    const it = cur(), r = rec();
    const miss = it.parts.filter((p) => r.part_support[p.part_id] === undefined).length;
    if (miss) {
      $('errC').textContent = `Please rate all statements — ${miss} still unanswered.`;
      $('errC').classList.remove('hidden'); return;
    }
    r.phaseC_completed_at = new Date().toISOString();
    persist(it.sample_id); refreshProgress(); nextSample();
  });

  // technical issue
  [['techBtnA'], ['techBtnB'], ['techBtnC']].forEach(([id]) =>
    $(id).addEventListener('click', renderTech));
  $('techCancel').addEventListener('click', () => goto(S.idx));
  $('techNote').addEventListener('input', (e) => { rec().technical_note = e.target.value; });
  $('techSave').addEventListener('click', () => {
    const r = rec();
    if (!r.technical_issue) return;
    persist(cur().sample_id); refreshProgress(); nextSample();
  });

  // backup / import / export
  $('backupBtn').addEventListener('click', () => {
    const p = buildExport(); p.export_kind = 'partial_backup';
    download(p, `visexmem_backup_${p.annotator_id}_${stamp()}.json`);
    $('menuMsg').textContent = 'Backup downloaded.';
  });
  $('importBtn').addEventListener('click', () => $('importFile').click());
  $('importFile').addEventListener('change', async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const msg = $('menuMsg');
    try {
      const d = JSON.parse(await f.text());
      if (d.annotator_id !== S.bundle.annotator_id) throw new Error('different annotator');
      if (d.assignment_hash !== S.bundle.assignment_hash) throw new Error('different assignment');
      if (d.schema_version !== S.bundle.schema_version) throw new Error('different schema version');
      const known = new Set(S.bundle.items.map((i) => i.sample_id));
      if (d.annotations.some((a) => !known.has(a.sample_id))) throw new Error('unknown sample ids');
      let restored = 0, skipped = 0;
      for (const a of d.annotations) {
        const it = S.bundle.items.find((i) => i.sample_id === a.sample_id);
        const existing = S.ann[a.sample_id];
        const incoming = fromExport(a, it);
        // never let an older import clobber newer local work
        if (existing && isComplete(existing, it) && !isComplete(incoming, it)) { skipped++; continue; }
        if (existing && existing.updated_at && incoming.updated_at &&
            existing.updated_at > incoming.updated_at) { skipped++; continue; }
        S.ann[a.sample_id] = incoming; await persist(a.sample_id); restored++;
      }
      refreshProgress();
      msg.textContent = `Imported ${restored} sample(s); kept newer local data for ${skipped}.`;
    } catch (ex) {
      msg.textContent = 'Import rejected: ' + ex.message;
    }
    e.target.value = '';
  });
  $('jumpFirstIncomplete').addEventListener('click', () => {
    const i = S.bundle.items.findIndex((it) => !isComplete(S.ann[it.sample_id], it));
    $('menu').classList.add('hidden');
    if (i < 0) showDone(); else goto(i);
  });
  $('finalBtn').addEventListener('click', exportFinal);
  $('doneExport').addEventListener('click', exportFinal);
}

function fromExport(a, it) {
  const r = blank(it);
  r.missing_information = a.missing_visual_information ?? null;
  r.decomposition_note = a.decomposition_note || '';
  r.holistic_alignment_1_to_7 = a.human_overall_alignment_1_to_7 ?? null;
  r.technical_issue = a.technical_issue ?? null;
  r.technical_note = a.technical_note || '';
  r.phaseA_completed_at = a.phaseA_completed_at ?? null;
  r.phaseB_completed_at = a.phaseB_completed_at ?? null;
  r.phaseC_completed_at = a.phaseC_completed_at ?? null;
  (a.decomposition || []).forEach((p) => {
    if (p.decomposition_label) r.decomposition[p.part_id] = p.decomposition_label;
    if (p.atomic_cannot_judge) r.part_support[p.part_id] = 'cannot_judge';
    else if (p.human_atomic_support_0_to_4 != null)
      r.part_support[p.part_id] = p.human_atomic_support_0_to_4;
  });
  r.updated_at = a.updated_at || null;
  return r;
}

document.addEventListener('DOMContentLoaded', wire);
