import {evaluate as evaluateProgram} from '/bitvector.js';
const $ = (id) => document.getElementById(id);
let token, artifact, artifactData, artifactName, result, recoveredExpression, generatedSource;
let generation = 0, activeJob, db, persistTimer;
let lastEvidence;
let inverseProgram;
const message = (text) => { $('notice').textContent = text; };
const formatAddress = (value) => typeof value === 'string' ? value : hex(value);
const width = () => Number($('word-bits').value);
const register = () => width() === 64 ? 'x' : 'w';
function exact(value) {
  if (typeof value === 'bigint') return value;
  if (typeof value === 'number' && Number.isSafeInteger(value)) return BigInt(value);
  const text = String(value).trim();
  if (text.length > 80 || !/^-?(?:0x[0-9a-f]+|[0-9]+)$/i.test(text)) throw new Error('Use an exact decimal or hexadecimal integer.');
  return text.startsWith('-') ? -BigInt(text.slice(1)) : BigInt(text);
}
const hex = (value) => '0x' + exact(value).toString(16).padStart(width()/4, '0');
const wordField = (object, prefix) => object[prefix + width()];
function number(text) {
  const n = exact(text), bits = BigInt(width()), modulo = 1n << bits;
  if (n < -(1n << (bits-1n)) || n >= modulo) throw new Error('Integer is outside the selected ' + width() + '-bit range.');
  const value = n < 0n ? n + modulo : n;
  return width() === 64 ? value.toString() : Number(value);
}
function range(signed, bits=width()) {
  const n = BigInt(bits);
  return signed ? [-(1n << (n-1n)), (1n << (n-1n))-1n] : [0n, (1n << n)-1n];
}
function widthLabels() {
  $('expression-label').textContent = 'Editable ' + width() + '-bit expression';
  $('expression-help').textContent = 'x0, x1, x2, x3 · + − * & | ^ << >> · ifelse(), lt(), ult(), asr(). Arithmetic wraps at ' + width() + ' bits; shift counts are masked to 0–' + (width()-1) + '.';
  $('target-label').textContent = 'Desired ' + register() + '0 result';
  $('run-backward').textContent = 'Run backward from desired ' + register() + '0';
  $('inverse-help').textContent = 'One input, all ' + width() + ' bits. Derive a reusable inverse from a supported reversible chain, with explicit composition checks.';
  for (const option of $('arity').options) option.textContent = option.value + ' · ' + Array.from({length:Number(option.value)}, (_,i) => register()+i).join(', ');
}
function base64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 16384) s += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(s);
}
async function post(path, value) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Workbench-Token': token}, body: JSON.stringify(value)});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed.');
  return body;
}
function download(name, data, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([data], {type}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function domains() {
  return Array.from($('domains').children).map((row) => {
    const signed = row.querySelector('input[type=checkbox]').checked;
    const lo = exact(row.querySelector('[data-min]').value), hi = exact(row.querySelector('[data-max]').value);
    const [lower,upper] = range(signed);
    if (lo < lower || hi > upper || lo > hi) throw new Error('Domain bounds must be ordered integers in the selected signed or unsigned range.');
    return lo === lower && hi === upper ? null : {min: width() === 64 ? lo.toString() : Number(lo), max: width() === 64 ? hi.toString() : Number(hi), signed};
  });
}
function settings() { return {symbol: $('symbol').value, arity: Number($('arity').value), word_bits: width(), domain: domains()}; }
function workspace() {
  if (!artifact) return null;
  return {schema: 'rewynth.workspace', version: 2, artifact: {name: artifactName, sha256: artifact.sha256, data: artifactData}, settings: settings(), expression: $('expression').value, queries: {inputs: Array.from({length: Number($('arity').value)}, (_,i) => $('arg-' + i).value.slice(0,24)), target: $('target').value.slice(0,24)}};
}
function store(key, value) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('workspace', 'readwrite'); tx.objectStore('workspace').put(value, key);
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
  });
}
function read(key) {
  return new Promise((resolve, reject) => {
    const request = db.transaction('workspace').objectStore('workspace').get(key);
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
}
async function persist() {
  if (!db || !artifact) return;
  try { await store('current', workspace()); $('saved-status').textContent = 'Saved in this browser. Download a workspace for a portable copy.'; }
  catch { $('saved-status').textContent = 'Browser save failed. Download a workspace to preserve your work.'; }
}
function scheduleSave() { clearTimeout(persistTimer); persistTimer = setTimeout(persist, 350); }
function inputFields(savedDomains) {
  const arity = Number($('arity').value);
  $('domains').replaceChildren(); $('inputs').replaceChildren();
  for (let i = 0; i < arity; i++) {
    const row = document.createElement('div'), label = document.createElement('label');
    label.textContent = 'x' + i + ' / ' + register() + i; row.append(label);
    const bounds = document.createElement('div'); bounds.className = 'bounds';
    const low = document.createElement('input'), high = document.createElement('input');
    low.dataset.min = ''; high.dataset.max = ''; low.setAttribute('aria-label', 'x' + i + ' minimum'); high.setAttribute('aria-label', 'x' + i + ' maximum');
    const d = savedDomains?.[i]; low.value = d?.min ?? range(false)[0].toString(); high.value = d?.max ?? range(false)[1].toString();
    bounds.append(low, high); row.append(bounds);
    const sl = document.createElement('label'), check = document.createElement('input'); sl.className = 'signed'; check.type = 'checkbox'; check.checked = d?.signed ?? false; sl.append(check, ' Signed interpretation'); row.append(sl);
    check.addEventListener('change', () => { const bounds = range(check.checked); low.value = bounds[0].toString(); high.value = bounds[1].toString(); invalidate(); });
    low.addEventListener('change', invalidate); high.addEventListener('change', invalidate); $('domains').append(row);
    const il = document.createElement('label'), input = document.createElement('input'); il.textContent = 'x' + i; input.id = 'arg-' + i; input.value = '0'; input.inputMode = 'numeric'; il.htmlFor = input.id; $('inputs').append(il, input);
  }
}
async function cancel() {
  generation++;
  const job = activeJob; activeJob = null;
  if (job) try { await post('/api/cancel/' + job, {}); } catch {}
  working(false);
}
function working(active) {
  $('cancel').hidden = !active;
  for (const id of ['recover','verify','inverse','evaluate','derive_inverse','open','example','example-wide','reopen','symbol','arity','word-bits']) $(id).disabled = active || (!artifact && !['open','example','example-wide','reopen','arity','word-bits'].includes(id));
  for (const input of $('domains').querySelectorAll('input')) input.disabled = active;
}
function invalidate() {
  cancel(); result = null; generatedSource = null; recoveredExpression = null; lastEvidence = null;
  inverseProgram = null; $('inverse-panel').hidden = true;
  const hasDraft = Boolean(artifact && $('expression').value.trim());
  $('recovered').hidden = !hasDraft; $('empty').hidden = hasDraft; $('trace-panel').hidden = true; $('witness').textContent = ''; $('method').textContent = 'Settings changed · unverified';
  $('proof').className = 'proof unknown'; $('proof').textContent = 'Settings changed. Compare this draft against the selected function and domain before relying on it.'; $('c-source').textContent = 'Verify this draft to generate its portable C.'; $('assembly').replaceChildren(); $('assumptions').textContent = 'Recompute to inspect current assumptions.'; $('reset-expression').disabled = true;
  $('verify').disabled = !hasDraft; $('inverse').disabled = !artifact; $('evaluate').disabled = !artifact;
  scheduleSave();
}
async function openBytes(data, name, restore) {
  await cancel();
  if (artifact && db) try { await store('previous', workspace()); } catch { message('Recovery copy could not be saved. Download the current workspace first.'); return; }
  const entered = await post('/api/artifacts', {data});
  if (restore && entered.sha256 !== restore.artifact.sha256) throw new Error('Workspace artifact digest does not match its saved identity.');
  if (restore && !entered.functions.some((f) => f.name === restore.settings.symbol && f.supported_size)) throw new Error('Saved function is missing or exceeds the supported byte budget. Original workspace was not replaced.');
  artifact = entered; artifactData = data; artifactName = name.slice(0, 256);
  if (!restore) $('expression').value = '';
  const identity = $('identity'); identity.replaceChildren();
  const title = document.createElement('strong'); title.textContent = artifactName; identity.append(title, document.createTextNode(entered.format + ' · ' + entered.size.toLocaleString() + ' bytes'), document.createElement('br'), document.createTextNode(entered.sha256));
  $('symbol').replaceChildren();
  for (const f of artifact.functions) { const option = document.createElement('option'); option.value = f.name; option.textContent = f.name + ' · ' + f.size + ' B'; option.disabled = !f.supported_size; $('symbol').append(option); }
  if (restore) { $('symbol').value = restore.settings.symbol; $('arity').value = restore.settings.arity; $('word-bits').value = restore.settings.word_bits ?? 32; if (!$('symbol').value) throw new Error('Saved function is missing from the artifact.'); }
  else { $('arity').value = '1'; }
  widthLabels(); inputFields(restore?.settings.domain); invalidate(); working(false);
  if (restore?.queries) { restore.queries.inputs.forEach((v,i) => { $('arg-' + i).value = v; }); $('target').value = restore.queries.target; }
  if (restore && restore.expression.trim()) {
    $('expression').value = restore.expression; $('recovered').hidden = false; $('empty').hidden = true;
    $('method').textContent = 'Saved edit · unverified'; $('proof').className = 'proof unknown'; $('proof').textContent = 'Saved expression restored. Run a new comparison; saved evidence is not a fresh proof.';
    $('c-source').textContent = 'Verify this saved expression to generate its portable C.';
    $('assembly').replaceChildren(); $('assumptions').textContent = 'Recompute the model to inspect current instruction and input assumptions.';
    $('reset-expression').disabled = true; $('verify').disabled = false; $('inverse').disabled = false; $('evaluate').disabled = false;
  }
  message('Artifact read as data. Select the function, argument count and relevant input domain, then recover.');
  await persist();
}
async function loadWorkspace(value) {
  if (!value || value.schema !== 'rewynth.workspace' || ![1,2].includes(value.version) || !value.artifact || typeof value.artifact.name !== 'string' || !/^[0-9a-f]{64}$/.test(value.artifact.sha256) || typeof value.artifact.data !== 'string' || value.artifact.data.length > 44739244 || !value.settings || ![1,2,3,4].includes(value.settings.arity) || typeof value.settings.symbol !== 'string' || !Array.isArray(value.settings.domain) || value.settings.domain.length !== value.settings.arity || typeof value.expression !== 'string' || value.expression.length > 65536) throw new Error('Invalid or unsupported workspace. Original bytes were not replaced.');
  const bits = value.version === 1 ? 32 : value.settings.word_bits;
  if (![32,64].includes(bits)) throw new Error('Invalid saved word size.');
  if (value.version === 1 && value.settings.word_bits !== undefined && value.settings.word_bits !== 32) throw new Error('Version 1 workspaces contain 32-bit words only.');
  for (const d of value.settings.domain) {
    if (d === null) continue;
    if (!d || typeof d.signed !== 'boolean' || (bits === 64 && (typeof d.min !== 'string' || typeof d.max !== 'string'))) throw new Error('Invalid saved input domain.');
    const lo = exact(d.min), hi = exact(d.max), [lower,upper] = range(d.signed,bits);
    if (lo > hi || lo < lower || hi > upper) throw new Error('Invalid saved input domain.');
  }
  if (value.queries && (!Array.isArray(value.queries.inputs) || value.queries.inputs.length !== value.settings.arity || value.queries.inputs.some(v => typeof v !== 'string' || v.length > 24) || typeof value.queries.target !== 'string' || value.queries.target.length > 24)) throw new Error('Invalid saved query controls.');
  await openBytes(value.artifact.data, value.artifact.name, value);
}
function trace(witness, title) {
  if (!witness) return;
  $('trace-panel').hidden = false;
  $('trace-caption').textContent = title + ' · inputs ' + wordField(witness,'inputs_u').map(hex).join(', ') + ' · output ' + hex(wordField(witness,'output_u') ?? wordField(witness,'original_output_u'));
  $('trace').replaceChildren();
  for (const row of witness.trace || []) {
    const tr = document.createElement('tr');
    for (const value of [formatAddress(row.address), row.instruction, row.destination, exact(wordField(row,'value_u')).toString(), hex(wordField(row,'value_u')), row.condition_taken === undefined ? '—' : String(row.condition_taken)]) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
    $('trace').append(tr);
  }
  wordField(witness,'inputs_u').forEach((n,i) => { if ($('arg-' + i)) $('arg-' + i).value = n; });
}
function proof(verification) {
  const p = $('proof'); p.className = 'proof';
  if (verification?.status === 'unsat') p.textContent = 'No counterexample exists within the declared domain in the implemented ARM64 model. This does not verify the lifter or calling convention against every CPU execution.';
  else if (verification?.status === 'sat') { p.classList.add('fail'); const w = verification.counterexample; p.textContent = 'Counterexample found. Original ' + hex(wordField(w,'original_output_u')) + ' differs from edit ' + hex(wordField(w,'candidate_output_u')) + '.'; trace(w, 'Contradicting input'); }
  else { p.classList.add('unknown'); p.textContent = 'No equivalence conclusion: ' + (verification?.reason || 'Unsupported or incomplete synthesis.'); }
}
function render(value) {
  result = value; lastEvidence = {schema: 'rewynth.evidence', version: 1, artifact_sha256: artifact.sha256, settings: settings(), produced_at: new Date().toISOString(), result: value};
  $('assembly').replaceChildren();
  for (const row of value.model.instructions) { const tr = document.createElement('tr'); for (const v of [formatAddress(row.address),row.assembly,row.bytes_hex]) { const td = document.createElement('td'); td.textContent = v; tr.append(td); } $('assembly').append(tr); }
  $('assumptions').textContent = JSON.stringify({assumptions: value.model.assumptions, synthesis: value.reconstruction}, null, 2);
  if (value.kind === 'recover') {
    const r = value.reconstruction;
    if (!value.expression) { message('Recovery did not produce editable source: ' + (r.reason || r.status)); return; }
    recoveredExpression = value.expression; generatedSource = value.source; $('reset-expression').disabled = false;
    $('expression').value = value.expression; $('recovered').hidden = false; $('empty').hidden = true;
    $('method').textContent = r.grammar || 'Lifted semantics'; $('c-source').textContent = value.source;
    $('assembly').replaceChildren();
    for (const row of value.model.instructions) { const tr = document.createElement('tr'); for (const v of [formatAddress(row.address),row.assembly,row.bytes_hex]) { const td = document.createElement('td'); td.textContent = v; tr.append(td); } $('assembly').append(tr); }
    $('assumptions').textContent = JSON.stringify({assumptions: value.model.assumptions, synthesis: r}, null, 2);
    proof(r.verification); $('verify').disabled = false; $('inverse').disabled = false; $('evaluate').disabled = false;
    message('Source recovered from these instruction bytes. Edit the expression, challenge it, or solve backward from a result.');
  } else if (value.kind === 'verify') { generatedSource = value.source; $('c-source').textContent = value.source; proof(value.verification); message('Edit compared against the original model with the same declared domain.'); }
  else if (value.kind === 'inverse') { const q = value.query; $('witness').textContent = q.status === 'sat' ? 'Input found: ' + wordField(q.witness,'inputs_u').map(hex).join(', ') : q.status === 'unsat' ? 'No input in the declared domain produces ' + hex(wordField(q,'target_u')) + '.' : 'Unknown: ' + q.reason; trace(q.witness, 'Inverse query witness'); message('Output constraint checked in the declared model and domain: ' + q.status + '.'); }
  else if (value.kind === 'evaluate') { $('witness').textContent = register() + '0 = ' + hex(wordField(value.witness,'output_u')) + ' / ' + exact(wordField(value.witness,'output_u')).toString(); trace(value.witness, 'Original model execution'); message('Original instruction model evaluated with exact ' + width() + '-bit values.'); }
  else if (value.kind === 'derive_inverse') {
    const inverse = value.inverse_program;
    if (!value.source || inverse.status !== 'verified_inverse_model') { message('No inverse program claimed: ' + (inverse.reason || inverse.status)); return; }
    inverseProgram = value; $('inverse-panel').hidden = false;
    $('inverse-expression').textContent = value.expression; $('inverse-c').textContent = value.source;
    const globals = inverse.proofs.global_compositions;
    $('inverse-proof').textContent = 'Reusable inverse under the machine model: exact chain binding and both directions of all ' + inverse.chain.length + ' primitive steps checked. Whole-expression checks: forward-after-inverse ' + globals.forward_after_inverse.status + ', inverse-after-forward ' + globals.inverse_after_forward.status + '. The source computes backward without a new solver query.';
    $('inverse-evidence').textContent = JSON.stringify(inverse, null, 2);
    message('Backward program recovered. x0 in this program is the desired original output; its result is the original input.');
    $('inverse-target').value = $('target').value; $('inverse-panel').scrollIntoView({block:'start',behavior:'smooth'});
  }
  scheduleSave();
}
async function run(operation) {
  const request = {artifact: artifact.sha256, ...settings(), operation};
  if (operation === 'verify') request.expression = $('expression').value;
  if (operation === 'inverse') request.target = number($('target').value);
  if (operation === 'evaluate') request.inputs = Array.from({length: request.arity}, (_,i) => number($('arg-' + i).value));
  const thisGeneration = ++generation; working(true); message('Analyzing the selected byte span…');
  try {
    const started = await post('/api/jobs', request);
    if (thisGeneration !== generation) { await post('/api/cancel/' + started.job, {}); return; }
    activeJob = started.job;
    for (let i = 0; i < 45 && generation === thisGeneration; i++) {
      const response = await fetch('/api/jobs/' + activeJob), state = await response.json();
      if (state.state === 'done') { if (generation === thisGeneration) render(state.result); return; }
      if (state.state !== 'running') throw new Error(state.error || 'Analysis cancelled.');
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (generation === thisGeneration) throw new Error('Analysis did not return within its deadline.');
  } finally { if (generation === thisGeneration) { activeJob = null; working(false); if (!$('recovered').hidden) { $('verify').disabled = false; $('inverse').disabled = false; $('evaluate').disabled = false; } } }
}
function action(id, fn) { $(id).addEventListener('click', async () => { try { await fn(); } catch (error) { message(error.message); } }); }
action('open', () => $('artifact-file').click()); action('reopen', () => $('workspace-file').click());
action('example', async () => { $('word-bits').value = '32'; const response = await fetch('/example'); if (!response.ok) throw new Error('Example artifact unavailable.'); await openBytes(base64(new Uint8Array(await response.arrayBuffer())), 'Image, hash and bitfield kernels · clang ARM64'); $('symbol').value = '_kernel_clamp'; invalidate(); message('Real compiled kernels loaded. Clamp is selected with one argument. Luma requires three arguments and RGB bounds 0–255. Hash and reverse use one, mixed arithmetic two, bitfield four.'); });
action('example-wide', async () => { const response = await fetch('/example-wide'); if (!response.ok) throw new Error('Wide example artifact unavailable.'); $('word-bits').value = '64'; await openBytes(base64(new Uint8Array(await response.arrayBuffer())), '64-bit state and bit transforms · clang ARM64'); $('symbol').value = '_splitmix64_step'; invalidate(); message('64-bit compiled transforms loaded. The pure SplitMix64 step maps a prior state to one full output. Derive its inverse to recover that prior state.'); });
$('artifact-file').addEventListener('change', async (event) => { const file = event.target.files[0]; try { if (!file) return; if (file.size > 33554432) throw new Error('Artifact exceeds 32 MiB.'); await openBytes(base64(new Uint8Array(await file.arrayBuffer())),file.name); } catch (e) { message(e.message); } finally { event.target.value = ''; } });
$('workspace-file').addEventListener('change', async (event) => { const file = event.target.files[0]; try { if (!file) return; if (file.size > 45*1024*1024) throw new Error('Workspace exceeds 45 MiB.'); await loadWorkspace(JSON.parse(await file.text())); } catch (e) { message(e.message); } finally { event.target.value = ''; } });
$('word-bits').addEventListener('change', () => { widthLabels(); inputFields(); invalidate(); });
$('symbol').addEventListener('change', invalidate); $('arity').addEventListener('change', () => { inputFields(); invalidate(); });
$('expression').addEventListener('input', () => { cancel(); generatedSource = null; lastEvidence = null; $('proof').className = 'proof unknown'; $('proof').textContent = 'Expression changed. The previous comparison does not apply to this edit.'; $('c-source').textContent = 'Verify the current expression to generate its portable C.'; scheduleSave(); });
action('recover', () => run('recover')); action('verify', () => run('verify')); action('inverse', () => run('inverse')); action('evaluate', () => run('evaluate')); action('cancel', async () => { await cancel(); message('Analysis cancelled. No new conclusion.'); });
action('derive_inverse', () => run('derive_inverse'));
action('export-inverse', () => { if (!inverseProgram) throw new Error('Derive a new inverse first.'); download('rewynth-inverse.c', '/* Artifact SHA256: ' + artifact.sha256 + '\n   Reusable inverse in the declared ARM64 instruction model.\n   Proof basis: exact chain binding and local two-sided composition. */\n' + inverseProgram.source, 'text/plain'); });
action('export-inverse-evidence', () => { if (!inverseProgram) throw new Error('Derive a new inverse first.'); download('rewynth-inverse-evidence.json', JSON.stringify({schema:'rewynth.inverse-evidence',version:1,artifact_sha256:artifact.sha256,settings:settings(),result:inverseProgram},null,2)); });
action('run-backward', () => { if (!inverseProgram) throw new Error('Derive a new inverse first.'); const desired = number($('inverse-target').value); const input = evaluateProgram(inverseProgram.inverse_program.ast,[desired],width()); $('backward-result').textContent = 'Desired original output ' + hex(desired) + ' → original input ' + hex(input) + '. Computed from the recovered program without a target-specific solver query.'; $('arg-0').value = input; scheduleSave(); });
action('check-backward', () => run('evaluate'));
$('target').addEventListener('input', () => { $('inverse-target').value = $('target').value; scheduleSave(); });
$('inverse-target').addEventListener('input', () => { $('target').value = $('inverse-target').value; scheduleSave(); });
$('inputs').addEventListener('input', scheduleSave);
action('reset-expression', () => { $('expression').value = recoveredExpression || ''; $('expression').dispatchEvent(new Event('input')); });
action('save', () => { const w = workspace(); if (!w) throw new Error('Open an artifact first.'); download('workspace.rewynth', JSON.stringify(w, null, 2)); message('Workspace downloaded with original bytes and editable settings. Proofs are recomputed after reopening.'); });
action('export-c', async () => { if (!generatedSource) await run('verify'); if (!generatedSource) throw new Error('Current expression did not generate C.'); download('recovered.c', '/* Artifact SHA256: ' + artifact.sha256 + '\n   Model scope: pure ' + width() + '-bit ARM64 register function, declared domain only.\n   This export is reconstructed source, not a native equivalence certificate. */\n' + generatedSource, 'text/plain'); });
action('export-evidence', () => { if (!lastEvidence) throw new Error('Run a new query to produce current evidence.'); download('evidence.json', JSON.stringify(lastEvidence, null, 2)); });
try {
  token = (await (await fetch('/api/bootstrap')).json()).token;
  widthLabels(); inputFields(); $('verify').disabled = true;
  const request = indexedDB.open('rewynth', 1); request.onupgradeneeded = () => request.result.createObjectStore('workspace');
  db = await new Promise((resolve,reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  const previous = await read('current');
  if (previous) { $('restore-dialog').showModal(); action('restore', async () => { $('restore-dialog').close(); await loadWorkspace(previous); }); action('start-fresh', () => $('restore-dialog').close()); }
} catch (error) { message('Local recovery storage unavailable. Manual workspace downloads remain available. ' + error.message); }
