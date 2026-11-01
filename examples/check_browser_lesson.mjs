// Compare both Wasm exports with fresh, controlled PCG C observations.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { parseWord, instantiateModel, transition, MAX_WORD } from '../docs/lesson/model-runtime.mjs';

const directory = resolve(process.argv[3] ?? fileURLToPath(new URL('../docs/lesson/model/', import.meta.url)));
const manifest = JSON.parse(readFileSync(resolve(directory, 'manifest.json')));
assert.equal(manifest.format, 'rewynth-browser-state-lesson-v1');
for (const [name, record] of Object.entries(manifest.assets)) {
  assert.match(name, /^[a-zA-Z0-9.-]+$/);
  const data = readFileSync(resolve(directory, name));
  assert.equal(data.length, record.bytes, name);
  assert.equal(createHash('sha256').update(data).digest('hex'), record.sha256, name);
}
assert.equal(parseWord('9007199254740993'), 9007199254740993n);
assert.equal(parseWord('0xffffffffffffffff'), MAX_WORD);
for (const invalid of ['-1', '+1', '1e3', '1.5', '', '0x', '18446744073709551616', 'alert(1)', 1]) {
  assert.throws(() => parseWord(invalid));
}
const original = instantiateModel(readFileSync(resolve(directory, 'original.wasm')));
const edited = instantiateModel(readFileSync(resolve(directory, 'edited.wasm')));
assert.throws(() => transition(original, -1n, 0n));
assert.throws(() => transition(original, MAX_WORD + 1n, 0n));
assert.throws(() => transition(original, 1, 0n));
const records = JSON.parse(readFileSync(process.argv[2]));
let count = 0;
for (const record of records) {
  let left = record.inputs.map(parseWord), right = [...left];
  for (const expected of record.calls) {
    const a = transition(original, ...left), b = transition(edited, ...right);
    assert.deepEqual([a.result, a.state, a.increment], expected.original.map(parseWord));
    assert.deepEqual([b.result, b.state, b.increment], expected.edited.map(parseWord));
    left = [a.state, a.increment];
    right = [b.state, b.increment];
    count += 2;
  }
}
console.log(JSON.stringify({ status: 'matched', cases: records.length, wasm_transitions: count, scope: 'Finite controls against freshly compiled PCG source, not universal CPU equivalence.' }));
