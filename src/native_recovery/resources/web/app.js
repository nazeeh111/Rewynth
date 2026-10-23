import {evaluate as evaluateProgram} from '/bitvector.js';
const $ = (id) => document.getElementById(id);
let token, artifact, artifactData, artifactName, result, recoveredExpression, generatedSource;
let generation = 0, activeJob, db, persistTimer;
let lastEvidence;
let inverseProgram, stateComparison, activeContinuation;
const message = (text) => { $('notice').textContent = text; };
const formatAddress = (value) => typeof value === 'string' ? value : hex(value);
const width = () => Number($('word-bits').value);
const register = () => width() === 64 ? 'x' : 'w';
const memoryMode = () => $('memory-enabled').checked;
function memoryDeclaration() {
  if (!memoryMode()) return undefined;
  const argument = Number($('memory-argument').value), words = Number($('memory-words').value), arity = Number($('arity').value);
  if (width() !== 64 || !Number.isInteger(argument) || argument < 0 || argument >= arity || ![1,2,3].includes(words) || arity - 1 + words > 4) throw new Error('Declare one 64-bit pointer and at most four logical inputs.');
  return {argument, words};
}
function inputMapping() {
  const arity = Number($('arity').value), memory = memoryDeclaration();
  if (!memory) return Array.from({length: arity}, (_,i) => register() + i);
  return [...Array.from({length: arity}, (_,i) => i).filter(i => i !== memory.argument).map(i => 'x' + i + ' scalar'), ...Array.from({length: memory.words}, (_,i) => 'memory[' + i + '] / bytes ' + (i*8) + '–' + (i*8+7))];
}
function memoryControls() {
  const arity = Number($('arity').value), previous = Number($('memory-argument').value) || 0;
  if (width() !== 64) $('memory-enabled').checked = false;
  $('memory-enabled').disabled = width() !== 64;
  $('memory-argument').replaceChildren();
  for (let i = 0; i < arity; i++) { const option = document.createElement('option'); option.value = String(i); option.textContent = 'x' + i + ' pointer'; $('memory-argument').append(option); }
  $('memory-argument').value = String(Math.min(previous, arity-1));
  const maximum = Math.min(3, 5-arity);
  for (const option of $('memory-words').options) option.disabled = Number(option.value) > maximum;
  $('memory-words').value = String(Math.min(Number($('memory-words').value) || 1, maximum));
  $('memory-settings').hidden = !memoryMode();
  $('memory-scope').textContent = memoryMode() ? 'One synthetic pointer, ' + $('memory-words').value + ' consecutive little-endian uint64 words. Inputs list scalars first, then initial memory. Every post-state word is compared. Fixed in-bounds accesses only; no native execution.' : 'Register-only model. Enable bounded memory in 64-bit mode for one explicit pointer argument.';
}
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
  const memory = memoryDeclaration();
  const sampleTransition = memory ? JSON.stringify({return:'x0', memory:Array.from({length:memory.words}, (_,i) => 'x' + (Number($('arity').value)-1+i))}) : '';
  $('expression-label').textContent = memoryMode() ? 'Editable transition JSON' : 'Editable ' + width() + '-bit expression';
  $('expression-help').textContent = (memory ? 'JSON with exactly "return" and "memory": ' + sampleTransition + '. Use one expression per declared word. All outputs use the same initial inputs. ' : '') + 'x0, x1, x2, x3 · + − * & | ^ << >> · ifelse(), lt(), ult(), asr(). Arithmetic wraps at ' + width() + ' bits; shift counts are masked to 0–' + (width()-1) + '.';
  $('target-label').textContent = 'Desired ' + register() + '0 result';
  $('run-backward').textContent = 'Run backward from desired ' + register() + '0';
  $('inverse-help').textContent = memoryMode() ? 'Inverse queries and backward programs are unavailable for joint return and memory transitions.' : 'One input, all ' + width() + ' bits. Derive a reusable inverse from a supported reversible chain, with explicit composition checks.';
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
function settings() { const memory = memoryDeclaration(); return {symbol: $('symbol').value, arity: Number($('arity').value), word_bits: width(), domain: domains(), ...(memory ? {memory} : {})}; }
function workspace() {
  if (!artifact) return null;
  return {schema: 'rewynth.workspace', version: 3, artifact: {name: artifactName, sha256: artifact.sha256, data: artifactData}, settings: settings(), expression: $('expression').value, queries: {inputs: inputMapping().map((_,i) => $('arg-' + i).value), target: $('target').value}};
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
  const mapping = inputMapping();
  $('domains').replaceChildren(); $('inputs').replaceChildren();
  for (let i = 0; i < mapping.length; i++) {
    const row = document.createElement('div'), label = document.createElement('label');
    label.textContent = 'x' + i + ' / ' + mapping[i]; row.append(label);
    const bounds = document.createElement('div'); bounds.className = 'bounds';
    const low = document.createElement('input'), high = document.createElement('input');
    low.dataset.min = ''; high.dataset.max = ''; low.setAttribute('aria-label', 'x' + i + ' minimum'); high.setAttribute('aria-label', 'x' + i + ' maximum');
    const d = savedDomains?.[i]; low.value = d?.min ?? range(false)[0].toString(); high.value = d?.max ?? range(false)[1].toString();
    bounds.append(low, high); row.append(bounds);
    const sl = document.createElement('label'), check = document.createElement('input'); sl.className = 'signed'; check.type = 'checkbox'; check.checked = d?.signed ?? false; sl.append(check, ' Signed interpretation'); row.append(sl);
    check.addEventListener('change', () => { const bounds = range(check.checked); low.value = bounds[0].toString(); high.value = bounds[1].toString(); invalidate(); });
    low.addEventListener('change', invalidate); high.addEventListener('change', invalidate); $('domains').append(row);
    const il = document.createElement('label'), input = document.createElement('input'); il.textContent = 'x' + i + ' / ' + mapping[i]; input.id = 'arg-' + i; input.value = '0'; input.inputMode = 'numeric'; il.htmlFor = input.id; $('inputs').append(il, input);
  }
}
async function cancel() {
  generation++;
  if (activeContinuation) {
    if (stateComparison === activeContinuation.witness) $('next-' + activeContinuation.side).textContent = 'Cancelled · no conclusion';
    activeContinuation = null;
  }
  const job = activeJob; activeJob = null;
  if (job) try { await post('/api/cancel/' + job, {}); } catch {}
  working(false);
}
function working(active) {
  $('cancel').hidden = !active;
  for (const id of ['continue-original','continue-edit','recover','verify','inverse','evaluate','derive_inverse','open','example','example-wide','example-branches','example-memory','reopen','symbol','arity','word-bits','memory-enabled','memory-argument','memory-words']) $(id).disabled = active || (!artifact && !['open','example','example-wide','example-branches','example-memory','reopen','arity','word-bits','memory-enabled','memory-argument','memory-words'].includes(id));
  if (width() !== 64) $('memory-enabled').disabled = true;
  if (memoryMode()) { $('inverse').disabled = true; $('derive_inverse').disabled = true; }
  for (const input of $('domains').querySelectorAll('input')) input.disabled = active;
}
function clearStateComparison() { stateComparison = null; activeContinuation = null; $('state-comparison').hidden = true; }
function invalidate() {
  clearStateComparison();
  cancel(); result = null; generatedSource = null; recoveredExpression = null; lastEvidence = null;
  inverseProgram = null; $('inverse-panel').hidden = true;
  const hasDraft = Boolean(artifact && $('expression').value.trim());
  $('recovered').hidden = !hasDraft; $('empty').hidden = hasDraft; $('trace-panel').hidden = true; $('witness').textContent = ''; $('method').textContent = 'Settings changed · unverified';
  $('proof').className = 'proof unknown'; $('proof').textContent = 'Settings changed. Compare this draft against the selected function and domain before relying on it.'; $('c-source').textContent = 'Verify this draft to generate its portable C.'; $('assembly').replaceChildren(); $('assumptions').textContent = 'Recompute to inspect current assumptions.'; $('reset-expression').disabled = true;
  $('verify').disabled = !hasDraft; $('inverse').disabled = !artifact || memoryMode(); $('evaluate').disabled = !artifact;
  scheduleSave();
}
async function openBytes(data, name, restore, defaults={}) {
  await cancel();
  if (artifact && db) try { await store('previous', workspace()); } catch { message('Recovery copy could not be saved. Download the current workspace first.'); return; }
  const entered = await post('/api/artifacts', {data});
  if (restore && entered.sha256 !== restore.artifact.sha256) throw new Error('Workspace artifact digest does not match its saved identity.');
  if (restore && !entered.functions.some((f) => f.name === restore.settings.symbol && f.supported_size)) throw new Error('Saved function is missing or exceeds the supported byte budget. Original workspace was not replaced.');
  artifact = entered; artifactData = data; artifactName = name.slice(0, 256);
  $('expression').value = restore?.expression ?? '';
  const identity = $('identity'); identity.replaceChildren();
  const title = document.createElement('strong'); title.textContent = artifactName; identity.append(title, document.createTextNode(entered.format + ' · ' + entered.size.toLocaleString() + ' bytes'), document.createElement('br'), document.createTextNode(entered.sha256));
  $('symbol').replaceChildren();
  for (const f of artifact.functions) { const option = document.createElement('option'); option.value = f.name; option.textContent = f.name + ' · ' + f.size + ' B'; option.disabled = !f.supported_size; $('symbol').append(option); }
  if (restore) { $('symbol').value = restore.settings.symbol; $('arity').value = restore.settings.arity; $('word-bits').value = restore.settings.word_bits ?? 32; if (!$('symbol').value) throw new Error('Saved function is missing from the artifact.'); }
  else { $('arity').value = String(defaults.arity ?? 1); if (defaults.word_bits) $('word-bits').value = String(defaults.word_bits); if (defaults.symbol) $('symbol').value = defaults.symbol; }
  const memory = restore?.settings.memory ?? defaults.memory;
  $('memory-enabled').checked = Boolean(memory);
  memoryControls();
  if (memory) { $('memory-argument').value = String(memory.argument); $('memory-words').value = String(memory.words); }
  memoryControls(); widthLabels(); inputFields(restore?.settings.domain); invalidate(); working(false);
  if (restore?.queries) { restore.queries.inputs.forEach((v,i) => { $('arg-' + i).value = v; }); $('target').value = restore.queries.target; }
  if (restore && restore.expression.trim()) {
    $('expression').value = restore.expression; $('recovered').hidden = false; $('empty').hidden = true;
    $('method').textContent = 'Saved edit · unverified'; $('proof').className = 'proof unknown'; $('proof').textContent = 'Saved expression restored. Run a new comparison; saved evidence is not a fresh proof.';
    $('c-source').textContent = 'Verify this saved expression to generate its portable C.';
    $('assembly').replaceChildren(); $('assumptions').textContent = 'Recompute the model to inspect current instruction and input assumptions.';
    $('reset-expression').disabled = true; $('verify').disabled = false; $('inverse').disabled = memoryMode(); $('evaluate').disabled = false;
  }
  message('Artifact read as data. Select the function, arguments, optional memory and input domain, then recover.');
  await persist();
}
function validateWorkspace(value) {
  if (!value || value.schema !== 'rewynth.workspace' || ![1,2,3].includes(value.version) || !value.artifact || typeof value.artifact.name !== 'string' || value.artifact.name.length > 256 || !/^[0-9a-f]{64}$/.test(value.artifact.sha256) || typeof value.artifact.data !== 'string' || !value.artifact.data.length || value.artifact.data.length > 44739244 || !value.settings || ![1,2,3,4].includes(value.settings.arity) || typeof value.settings.symbol !== 'string' || !value.settings.symbol.length || value.settings.symbol.length > 4096 || !Array.isArray(value.settings.domain) || typeof value.expression !== 'string' || value.expression.length > 65536) throw new Error('Invalid or unsupported workspace. Original bytes were not replaced.');
  const bits = value.version === 1 ? 32 : value.settings.word_bits;
  if (![32,64].includes(bits)) throw new Error('Invalid saved word size.');
  if (value.version === 1 && value.settings.word_bits !== undefined && value.settings.word_bits !== 32) throw new Error('Version 1 workspaces contain 32-bit words only.');
  const memory = value.settings.memory;
  let count = value.settings.arity;
  if (Object.hasOwn(value.settings, 'memory')) {
    if (value.version !== 3 || bits !== 64 || !memory || Array.isArray(memory) || Object.keys(memory).sort().join(',') !== 'argument,words' || !Number.isInteger(memory.argument) || memory.argument < 0 || memory.argument >= value.settings.arity || ![1,2,3].includes(memory.words) || value.settings.arity - 1 + memory.words > 4) throw new Error('Invalid saved memory declaration. Original bytes were not replaced.');
    count = value.settings.arity - 1 + memory.words;
  }
  if (value.settings.domain.length !== count) throw new Error('Saved domains do not match the logical inputs.');
  for (const d of value.settings.domain) {
    if (d === null) continue;
    if (!d || Array.isArray(d) || Object.keys(d).sort().join(',') !== 'max,min,signed' || typeof d.signed !== 'boolean' || (bits === 64 && (typeof d.min !== 'string' || typeof d.max !== 'string')) || (bits === 32 && (typeof d.min !== 'number' || typeof d.max !== 'number'))) throw new Error('Invalid saved input domain.');
    const lo = exact(d.min), hi = exact(d.max), [lower,upper] = range(d.signed,bits);
    if (lo > hi || lo < lower || hi > upper) throw new Error('Invalid saved input domain.');
  }
  if (Object.hasOwn(value, 'queries') && (!value.queries || !Array.isArray(value.queries.inputs) || value.queries.inputs.length !== count || value.queries.inputs.some(v => typeof v !== 'string' || v.length > 80) || typeof value.queries.target !== 'string' || value.queries.target.length > 80)) throw new Error('Invalid saved query controls.');
  return value;
}
async function loadWorkspace(value) {
  validateWorkspace(value);
  await openBytes(value.artifact.data, value.artifact.name, value);
}
function postMemory(witness, prefix='memory_u') {
  const values = wordField(witness, prefix);
  return Array.isArray(values) ? values.map((value,i) => 'memory[' + i + '] = ' + hex(value)).join(', ') : '';
}
function trace(witness, title) {
  if (!witness) return;
  $('trace-panel').hidden = false;
  $('trace-caption').textContent = title + ' · inputs ' + wordField(witness,'inputs_u').map(hex).join(', ') + ' · output ' + hex(wordField(witness,'output_u') ?? wordField(witness,'original_output_u')) + (memoryMode() ? ' · post-state ' + (postMemory(witness) || postMemory(witness,'original_memory_u')) : '');
  $('trace').replaceChildren();
  for (const row of witness.trace || []) {
    const tr = document.createElement('tr');
    const value = row.kind === 'branch' ? exact(row.next_address) : exact(wordField(row,'value_u'));
    for (const text of [formatAddress(row.address), row.instruction, row.destination, value.toString(), row.kind === 'branch' ? formatAddress(row.next_address) : hex(value), row.condition_taken === undefined ? '—' : String(row.condition_taken)]) { const td = document.createElement('td'); td.textContent = text; tr.append(td); }
    $('trace').append(tr);
  }
  wordField(witness,'inputs_u').forEach((n,i) => { if ($('arg-' + i)) $('arg-' + i).value = n; });
}
function showStateComparison(witness) {
  clearStateComparison();
  if (!memoryMode()) return;
  stateComparison = witness;
  const words = Number($('memory-words').value), scalars = Number($('arity').value) - 1;
  const initial = wordField(witness, 'inputs_u').slice(scalars);
  const original = wordField(witness, 'original_memory_u'), edited = wordField(witness, 'candidate_memory_u');
  $('state-words').replaceChildren();
  for (let i = 0; i < words; i++) {
    const row = document.createElement('tr');
    if (exact(original[i]) !== exact(edited[i])) row.className = 'changed-word';
    for (const text of ['memory[' + i + ']', hex(initial[i]), hex(original[i]), hex(edited[i])]) {
      const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
    }
    $('state-words').append(row);
  }
  $('next-original').textContent = 'Not traced'; $('next-edit').textContent = 'Not traced';
  $('state-comparison').hidden = false;
}
async function continueState(side) {
  const witness = stateComparison;
  if (!witness || !memoryMode()) throw new Error('Find a fresh state counterexample first.');
  const invocation = {witness, side};
  activeContinuation = invocation;
  const isCurrent = () => activeContinuation === invocation && stateComparison === witness;
  const scalars = wordField(witness, 'inputs_u').slice(0, Number($('arity').value) - 1);
  const inputs = [...scalars, ...wordField(witness, side === 'original' ? 'original_memory_u' : 'candidate_memory_u')];
  inputs.forEach((value, i) => { $('arg-' + i).value = value; });
  $('next-' + side).textContent = 'Tracing…';
  try {
    const value = await run('evaluate');
    if (!isCurrent()) return;
    $('next-' + side).textContent = value ? hex(wordField(value.witness, 'output_u')) : 'Cancelled · no conclusion';
    if (value) {
      trace(value.witness, 'Next call from ' + (side === 'original' ? 'original' : 'edited') + ' post-state');
      message('Original model traced from the ' + side + ' post-state. Compare the two next returns below the state table.');
    }
  } catch (error) {
    if (!isCurrent()) return;
    $('next-' + side).textContent = 'Not established: ' + error.message;
    throw error;
  } finally {
    if (isCurrent()) {
      if (document.activeElement === document.body) $('continue-' + side).focus?.();
      activeContinuation = null;
    }
  }
}
function proof(verification) {
  clearStateComparison();
  const p = $('proof'); p.className = 'proof';
  $('trace-panel').hidden = true; $('witness').textContent = '';
  if (verification?.status === 'unsat') p.textContent = 'No counterexample exists for ' + (memoryMode() ? 'the return and every declared post-state word' : 'the return') + ' within the declared domain in the implemented ARM64 model. This does not verify the lifter or calling convention against every CPU execution.';
  else if (verification?.status === 'sat') { p.classList.add('fail'); const w = verification.counterexample; p.textContent = memoryMode() ? 'Counterexample found. Changed: ' + (w.differences || []).join(', ') + '.\nOriginal return ' + hex(wordField(w,'original_output_u')) + '; edit return ' + hex(wordField(w,'candidate_output_u')) + '.\nOriginal post-state: ' + postMemory(w,'original_memory_u') + '.\nEdit post-state: ' + postMemory(w,'candidate_memory_u') + '.' : 'Counterexample found. Original ' + hex(wordField(w,'original_output_u')) + ' differs from edit ' + hex(wordField(w,'candidate_output_u')) + '.'; trace(w, 'Contradicting input'); showStateComparison(w); }
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
    proof(r.verification); $('verify').disabled = false; $('inverse').disabled = memoryMode(); $('evaluate').disabled = false;
    message(memoryMode() ? 'Transition recovered. Edit return and post-memory together, then compare every output.' : 'Source recovered from these instruction bytes. Edit the expression, challenge it, or solve backward from a result.');
  } else if (value.kind === 'verify') { $('method').textContent = memoryMode() ? 'Joint state comparison' : 'Edit comparison'; generatedSource = value.source; $('c-source').textContent = value.source; proof(value.verification); message('Edit compared against the original model with the same declared domain.'); }
  else if (value.kind === 'inverse') { const q = value.query; $('witness').textContent = q.status === 'sat' ? 'Input found: ' + wordField(q.witness,'inputs_u').map(hex).join(', ') : q.status === 'unsat' ? 'No input in the declared domain produces ' + hex(wordField(q,'target_u')) + '.' : 'Unknown: ' + q.reason; trace(q.witness, 'Inverse query witness'); message('Output constraint checked in the declared model and domain: ' + q.status + '.'); }
  else if (value.kind === 'evaluate') { $('witness').textContent = register() + '0 = ' + hex(wordField(value.witness,'output_u')) + ' / ' + exact(wordField(value.witness,'output_u')).toString() + (memoryMode() ? '\nPost-state: ' + postMemory(value.witness) : ''); trace(value.witness, 'Original model execution'); message('Original instruction model evaluated with exact ' + width() + '-bit values.'); }
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
  if (memoryMode() && ['inverse','derive_inverse'].includes(operation)) throw new Error('Inverse operations are unavailable for memory transitions.');
  const request = {artifact: artifact.sha256, ...settings(), operation};
  if (operation === 'verify') request.expression = $('expression').value;
  if (operation === 'inverse') request.target = number($('target').value);
  if (operation === 'evaluate') request.inputs = inputMapping().map((_,i) => number($('arg-' + i).value));
  const thisGeneration = ++generation; working(true); message('Analyzing the selected byte span…');
  try {
    const started = await post('/api/jobs', request);
    if (thisGeneration !== generation) { await post('/api/cancel/' + started.job, {}); return; }
    activeJob = started.job;
    for (let i = 0; i < 45 && generation === thisGeneration; i++) {
      const response = await fetch('/api/jobs/' + activeJob), state = await response.json();
      if (state.state === 'done') { if (generation === thisGeneration) { render(state.result); return state.result; } return; }
      if (state.state !== 'running') throw new Error(state.error || 'Analysis cancelled.');
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (generation === thisGeneration) throw new Error('Analysis did not return within its deadline.');
  } finally { if (generation === thisGeneration) { activeJob = null; working(false); if (!$('recovered').hidden) { $('verify').disabled = false; $('inverse').disabled = memoryMode(); $('evaluate').disabled = false; } } }
}
function action(id, fn) { $(id).addEventListener('click', async () => { try { await fn(); } catch (error) { message(error.message); } }); }
action('open', () => $('artifact-file').click()); action('reopen', () => $('workspace-file').click());
async function openExample(path, name, defaults) {
  const response = await fetch(path); if (!response.ok) throw new Error('Example artifact unavailable.');
  await openBytes(base64(new Uint8Array(await response.arrayBuffer())), name, undefined, defaults);
}
action('example', async () => { await openExample('/example', 'Image, hash and bitfield kernels · clang ARM64', {word_bits:32, symbol:'_kernel_clamp'}); message('Real compiled kernels loaded. Clamp is selected with one argument. Luma requires three arguments and RGB bounds 0–255. Hash and reverse use one, mixed arithmetic two, bitfield four.'); });
action('example-wide', async () => { await openExample('/example-wide', '64-bit state and bit transforms · clang ARM64', {word_bits:64, symbol:'_splitmix64_step'}); message('64-bit compiled transforms loaded. The pure SplitMix64 step maps a prior state to one full output. Derive its inverse to recover that prior state.'); });
action('example-branches', async () => { await openExample('/example-branches', 'Conditional integer kernels · clang ARM64', {word_bits:32, symbol:'_tone_curve32'}); message('Branching kernels loaded. Tone curve uses one 32-bit input: try 256, 1024 and 5000 to trace its different returns. Morton uses two 32-bit inputs; window tag uses three 64-bit inputs; record hash uses four 64-bit inputs.'); });
action('example-memory', async () => { await openExample('/example-memory', 'PCG32 state transition · original compiled ARM64', {word_bits:64, arity:1, memory:{argument:0, words:2}, symbol:'_pcg32_random_r'}); $('arg-0').value = '0x853c49e6748fea9b'; $('arg-1').value = '0xda3e39cb94b95bdb'; scheduleSave(); message('PCG32 loaded as data. x0 and x1 are initial state and increment. Recover return plus both post-state words; no artifact is executed natively.'); });
$('artifact-file').addEventListener('change', async (event) => { const file = event.target.files[0]; try { if (!file) return; if (file.size > 33554432) throw new Error('Artifact exceeds 32 MiB.'); await openBytes(base64(new Uint8Array(await file.arrayBuffer())),file.name); } catch (e) { message(e.message); } finally { event.target.value = ''; } });
$('workspace-file').addEventListener('change', async (event) => { const file = event.target.files[0]; try { if (!file) return; if (file.size > 45*1024*1024) throw new Error('Workspace exceeds 45 MiB.'); await loadWorkspace(JSON.parse(await file.text())); } catch (e) { message(e.message); } finally { event.target.value = ''; } });
$('word-bits').addEventListener('change', () => { memoryControls(); widthLabels(); inputFields(); invalidate(); });
$('symbol').addEventListener('change', invalidate); $('arity').addEventListener('change', () => { memoryControls(); widthLabels(); inputFields(); invalidate(); });
for (const id of ['memory-enabled','memory-argument','memory-words']) $(id).addEventListener('change', () => { memoryControls(); widthLabels(); inputFields(); invalidate(); });
$('expression').addEventListener('input', () => { clearStateComparison(); $('trace-panel').hidden = true; cancel(); generatedSource = null; lastEvidence = null; $('proof').className = 'proof unknown'; $('proof').textContent = 'Expression changed. The previous comparison does not apply to this edit.'; $('c-source').textContent = 'Verify the current expression to generate its portable C.'; scheduleSave(); });
action('recover', () => run('recover')); action('verify', () => run('verify')); action('inverse', () => run('inverse')); action('evaluate', () => run('evaluate')); action('cancel', async () => { await cancel(); message('Analysis cancelled. No new conclusion.'); });
action('continue-original', () => continueState('original'));
action('continue-edit', () => continueState('edit'));
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
action('export-c', async () => { if (!generatedSource) await run('verify'); if (!generatedSource) throw new Error('Current expression did not generate C.'); download('recovered.c', '/* Artifact SHA256: ' + artifact.sha256 + '\n   Model scope: ' + (memoryMode() ? 'pure transition struct: architectural return and every declared uint64 memory word; not a binary ABI replacement' : 'pure ' + width() + '-bit ARM64 register function') + ', declared domain only.\n   This export is reconstructed source, not a native equivalence certificate. */\n' + generatedSource, 'text/plain'); });
action('export-evidence', () => { if (!lastEvidence) throw new Error('Run a new query to produce current evidence.'); download('evidence.json', JSON.stringify(lastEvidence, null, 2)); });
try {
  token = (await (await fetch('/api/bootstrap')).json()).token;
  memoryControls(); widthLabels(); inputFields(); $('verify').disabled = true;
  const request = indexedDB.open('rewynth', 1); request.onupgradeneeded = () => request.result.createObjectStore('workspace');
  db = await new Promise((resolve,reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
  const previous = await read('current');
  if (previous) { $('restore-dialog').showModal(); action('restore', async () => { $('restore-dialog').close(); await loadWorkspace(previous); }); action('start-fresh', () => $('restore-dialog').close()); }
} catch (error) { message('Local recovery storage unavailable. Manual workspace downloads remain available. ' + error.message); }
