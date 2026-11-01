// Advance the two exported models; the local app owns fresh recovery and proofs.
import { fetchModels, parseWord, hex, transition } from './model-runtime.mjs';

const $ = id => document.getElementById(id);
let models, initial, left, right, calls = 0;
const limit = 16;

function showError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function paint(prefix, value) {
  $(`${prefix}-return`).textContent = hex(value.result, 8);
  $(`${prefix}-state`).textContent = hex(value.state);
  $(`${prefix}-increment`).textContent = hex(value.increment);
}

function advance() {
  if (!models || calls >= limit) return;
  const a = transition(models.original, ...left);
  const b = transition(models.edited, ...right);
  calls += 1;
  left = [a.state, a.increment];
  right = [b.state, b.increment];
  paint('original', a);
  paint('edited', b);
  const stateDiffers = a.state !== b.state || a.increment !== b.increment;
  const returnDiffers = a.result !== b.result;
  document.querySelector('.edited .state-row').classList.toggle('changed', a.state !== b.state);
  document.querySelectorAll('.returned').forEach(row => row.classList.toggle('changed', returnDiffers));
  $('call-count').textContent = `Call ${calls}`;
  const message = returnDiffers ? 'The returns differ now, too. The lost update has reached the next result.'
    : stateDiffers ? 'The returns match. The state does not. A return-only test would miss this edit.'
      : 'Both returns and state match for these inputs so far. This does not establish equality for other inputs.';
  $('observation').textContent = message + (calls === limit ? ' Reset the example to start again.' : '');
  $('observation').dataset.kind = returnDiffers ? 'return' : stateDiffers ? 'state' : 'match';
  const row = document.createElement('tr');
  for (const [index, text] of [String(calls), hex(a.result, 8), hex(b.result, 8), stateDiffers ? 'Different' : 'Same'].entries()) {
    const cell = document.createElement('td');
    cell.textContent = text;
    if ((index === 2 && returnDiffers) || (index === 3 && stateDiffers)) cell.className = 'different';
    row.append(cell);
  }
  $('history').append(row);
  $('next').disabled = calls >= limit;
}

function start(words) {
  initial = [...words];
  left = [...words]; right = [...words]; calls = 0;
  $('history').replaceChildren();
  $('starting-inputs').textContent = `Starting words: state ${hex(initial[0])} · increment ${hex(initial[1])}`;
  showError($('input-error'), '');
  for (const id of ['state-input', 'increment-input']) $(id).removeAttribute('aria-invalid');
  advance();
}

$('next').addEventListener('click', () => {
  try { advance(); } catch { showError($('load-error'), 'The model could not complete this call. Reload the page to start again.'); }
});
$('reset').addEventListener('click', () => {
  $('state-input').value = models.manifest.default_inputs[0];
  $('increment-input').value = models.manifest.default_inputs[1];
  start(models.manifest.default_inputs.map(parseWord));
});
$('inputs').addEventListener('submit', event => {
  event.preventDefault();
  if (!models) return;
  const words = [];
  for (const [id, label] of [['state-input', 'Initial state'], ['increment-input', 'Increment']]) {
    $(id).removeAttribute('aria-invalid');
    try { words.push(parseWord($(id).value)); }
    catch (error) {
      $(id).setAttribute('aria-invalid', 'true');
      showError($('input-error'), `${label}: ${error.message} The current comparison is preserved.`);
      $(id).focus();
      return;
    }
  }
  start(words);
});

try {
  models = await fetchModels();
  start(models.manifest.default_inputs.map(parseWord));
  for (const id of ['next', 'reset', 'apply']) $(id).disabled = false;
} catch (error) {
  $('call-count').textContent = 'Models unavailable';
  $('observation').textContent = 'No comparison has been run. The C exports and recorded evidence remain available below.';
  showError($('load-error'), error.message || 'The model files could not be loaded. Reload the page to try again.');
} finally {
  document.querySelector('.experiment').setAttribute('aria-busy', 'false');
}
