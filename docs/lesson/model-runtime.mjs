// Run the compiled pure transition exports with exact, unsigned 64-bit words.
export const MAX_WORD = (1n << 64n) - 1n;

export function parseWord(text) {
  if (typeof text !== 'string' || !/^(?:0x[0-9a-f]+|[0-9]+)$/i.test(text.trim())) {
    throw new Error('Use an unsigned decimal or 0x hexadecimal integer.');
  }
  const value = BigInt(text.trim());
  if (value > MAX_WORD) throw new Error('The largest allowed value is 0xffffffffffffffff.');
  return value;
}

export function hex(value, width = 16) {
  return `0x${value.toString(16).padStart(width, '0')}`;
}

export function instantiateModel(bytes) {
  const module = new WebAssembly.Module(bytes);
  if (WebAssembly.Module.imports(module).length) throw new Error('The lesson model must be self-contained.');
  const instance = new WebAssembly.Instance(module);
  for (const name of ['lesson_call', 'lesson_result', 'lesson_state', 'lesson_increment']) {
    if (typeof instance.exports[name] !== 'function') throw new Error(`Missing model export: ${name}`);
  }
  return instance;
}

export function transition(instance, state, increment) {
  for (const value of [state, increment]) {
    if (typeof value !== 'bigint' || value < 0n || value > MAX_WORD) throw new Error('Inputs must be unsigned 64-bit words.');
  }
  instance.exports.lesson_call(state, increment);
  return {
    result: BigInt.asUintN(64, instance.exports.lesson_result()),
    state: BigInt.asUintN(64, instance.exports.lesson_state()),
    increment: BigInt.asUintN(64, instance.exports.lesson_increment()),
  };
}

export async function fetchModels() {
  const response = await fetch(new URL('model/manifest.json', import.meta.url));
  if (!response.ok) throw new Error('The model manifest could not be loaded. Reload the page to try again.');
  const manifest = await response.json();
  if (manifest.format !== 'rewynth-browser-state-lesson-v1') throw new Error('This model format is unsupported.');
  const models = await Promise.all(['original', 'edited'].map(async name => {
    const file = `${name}.wasm`;
    const response = await fetch(new URL(`model/${file}`, import.meta.url));
    if (!response.ok) throw new Error(`The ${name} model could not be loaded. Reload the page to try again.`);
    const bytes = await response.arrayBuffer();
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), value => value.toString(16).padStart(2, '0')).join('');
    if (hash !== manifest.assets?.[file]?.sha256) throw new Error('The model files do not match their manifest. Reload the page to try again.');
    return instantiateModel(bytes);
  }));
  return { manifest, original: models[0], edited: models[1] };
}
