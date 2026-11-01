# Browser state lesson

This static lesson runs Rewynth's recovered PCG32 transition and its deliberate
lost-store edit. Both are actual C exports compiled to WebAssembly. Each click
passes that model's complete post-state into its next call. Decimal and hex
inputs stay exact through unsigned 64-bit `BigInt` values.

The browser does not recover arbitrary code, execute the original ARM64 artifact
or issue fresh solver queries. Use the [local workbench](../../README.md#run-it)
for fresh recovery and solver comparisons; imported artifacts remain analysis
data. The example does not demonstrate an
upstream PCG bug or assess random-generator quality.

## Preview

From the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs
```

Open `http://127.0.0.1:8000/lesson/`. There are no external scripts, fonts,
accounts or model services. A modern browser with WebAssembly, BigInt and Web
Crypto is required; use loopback or HTTPS. Failed model loads leave the controls
disabled and show an error rather than substituted results.

## Reproduce the models

Install Rewynth in a virtual environment as described in the root README. Use
new output directories so existing evidence remains intact:

```sh
.venv/bin/python examples/state_lab.py --output state-lab-new
.venv/bin/python examples/build_browser_lesson.py \
  --evidence state-lab-new --output lesson-model-new \
  --compiler /path/to/llvm/bin/clang
.venv/bin/python examples/check_browser_lesson.py --model lesson-model-new
```

The compiler needs a paired `wasm-ld` and the `wasm32` target, with no C standard
library requirement. The shipped build used the official Emscripten 6.0.13 LLVM
toolchain. The builder includes the emitted C, bridge, exact expression JSON,
solver evidence and licenses. Its manifest records the recovery source commit,
compiler, artifact/function hashes, native-source hashes and asset hashes. A
fresh recovery can produce different solver witnesses or equivalent source;
the manifest binds each build to its own evidence.

The current model assets were generated from recovery source commit
`01fbd2e2f02e510102cad16e87c2d3a9fe2069ed`. This identifies the engine and fixture
used for recovery, not the later commit that adds this interface. Rebuilding does
not overwrite the shipped `model/` directory; inspect and verify a new build
before replacing it.

## Controls and scope

```sh
python3 examples/check_browser_lesson.py
```

Clang and Node are required. The checker freshly compiles the licensed portable
PCG source on the host and compares both shipped Wasm exports with 32 input
pairs over three successive calls: 192 native calls and 192 Wasm transitions.
The edited control explicitly discards the native state write. It also checks
asset hashes, exact input parsing and word bounds. CI runs this check on Linux
and ARM64 macOS. This is a finite controlled comparison, not universal CPU
equivalence. The [saved receipt](verification/native-wasm-controls.json) records
the local macOS run and the exact modules it checked.

The recorded `unsat` result concerns equality within Rewynth's implemented
instruction model and declared two-word memory region/input domain. The `sat`
edit result identifies a differing post-state while the immediate returns
agree. Neither status establishes the correctness of the CPU model itself.

PCG32 is by Melissa O'Neill, licensed under Apache-2.0. The actual source notice,
[PCG license](model/PCG-LICENSE.txt), and Rewynth's consolidated
[license and attribution](model/REWYNTH-LICENSE.txt) are included.
