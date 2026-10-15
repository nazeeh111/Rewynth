# Recover and challenge conditional control flow

Rewynth recovers supported integer functions containing direct acyclic branches. A control-flow graph records which instruction can execute next; acyclic means it contains no directed loop. The model propagates each path's guard, register values and arithmetic flags, merges shared states, and combines all reachable return values. It does not select the first return or discard branch conditions.

Supported forms are `b`, `b.<condition>`, `cbz`, `cbnz`, `tbz` and `tbnz`, with aligned direct targets inside the selected function. Numerically backward edges are permitted when the graph remains acyclic. Ordinary compiler tail merging can put a shared epilogue before one of its predecessors. Actual directed cycles remain unsupported even when a particular loop would terminate.

The existing limits remain: 4 KiB per selected function, 128 reachable instructions, 256 edges, a 256-node/depth-24 editable source program, and a 20-second product process deadline. A lifted function can exceed the separate editable-source limit; that returns an explicit limit result rather than a verified recovery. Solver unknowns remain unknown. Registers and flags used after a merge must have definitions on every relevant incoming path. Memory, calls, indirect control flow, out-of-function targets and unsupported instructions remain refused. Artifact bytes are analyzed as data, never loaded for native execution.

## A complete tone-curve experiment

The shipped `_tone_curve32` has one unsigned 32-bit argument. Inputs 0 through 4095 represent 12-bit luminance samples; larger values saturate to 4095. The shadow segment uses fixed-point arithmetic, the middle is unchanged, and the highlight segment has a quadratic shoulder. This is an original controlled example, not a perceptual image-quality claim.

In the workbench choose **Load conditional branch example**, then **Recover source**. Keep one argument and 32-bit words. Trace 511, 512, 3072 and 4096: the outputs are 510, 512, 3073 and 4095. Inspect the `branch` and `return` trace events and compare the executed paths. Only one return appears in each concrete trace. Restoring the recovered expression and verifying it checks the original modeled behavior. Replacing the expression with `x0` produces a solver counterexample. **Export portable C** exports the current editable expression, so restore recovery first when exporting the original behavior.

## Run the complete lesson

From a checkout of this repository, use the Python environment where Rewynth
0.3 is installed:

```sh
.venv/bin/python examples/conditional_lab.py --output branch-lab
```

The [lesson script](../examples/conditional_lab.py) writes a new directory and
refuses to overwrite an existing one. No compiler, browser, native ARM64 host
or network is needed after installation. The fixture is read as data. On a
failed or undecided operation it retains partial evidence, exits with an error,
and leaves no completion report. Use another directory name for a fresh run.

Open `branch-lab/REPORT.md`. It records three different questions:

| Comparison with the original instruction model | Input domain | Expected solver result |
|---|---|---|
| Recovered source | All unsigned 32-bit patterns | UNSAT |
| Deliberate identity edit `x0` | All unsigned 32-bit patterns | SAT, with an actual differing input |
| The same identity edit | Unsigned 512 through 3071 inclusive | UNSAT |

SAT means a contradicting input exists. UNSAT means none exists under the
implemented instruction model and the stated bounds. The middle segment is
identity, so narrowing the input domain changes the question. It does not make
the edit equivalent over the full word range. UNKNOWN would stop the lesson;
it is never reported as UNSAT. These are model comparisons, not a formal CPU
or lifter proof.

The report includes the actual counterexample and its concrete model replay,
boundary values, hashes binding the artifact and function, and the filename
of every result. `identity-full-domain.json` contains the actual executed trace;
`identity-middle-domain.json` retains the explicit unsigned bounds. Additional
`trace-*.json` files each show one executed return. The report is published
atomically without overwriting another file, after all expected results pass.
`SHA256.json` covers the evidence files saved
before the report; it does not cover itself or the report.

`original.c` exports the recovered full-domain behavior. `identity.c` exports
the deliberately incorrect identity version. Both contain a function named
`recovered`, so compile them separately. They are standalone defined-width C
requiring only standard integer/Boolean headers and no solver at runtime.
The restricted comparison does not add an input guard to `identity.c`.
The script adds no dependencies beyond the installed Rewynth package.

## More actual compiled examples

All six functions are in one immutable ARM64 Mach-O artifact, `branch-kernels.dylib`, with original `branch-kernels.c` and [provenance](../src/native_recovery/resources/examples/branch-provenance.json). The source was compiled using Apple Clang 21.0.0 at `-O2`; separate `-O1` and `-Os` experiments are different compiler settings of this same source, not independent external inputs. Across those settings 22,326 original native/Python-reference comparisons passed before integration. Current product tests also compare four branching families with their recovered C. These finite tests support the stated fixtures, not every ARM64 program or compiler.

| Function | Arguments | Word bits | Behavior |
|---|---:|---:|---|
| `_tone_curve32` | 1 | 32 | Piecewise luminance curve with high-input saturation |
| `_guarded_morton32` | 2 | 32 | Interleaves two 16-bit coordinates; saturates invalid coordinates to all ones |
| `_window_tag64` | 3 | 64 | Noncryptographic tag for a value inside an inclusive unsigned window |
| `_record_hash64` | 4 | 64 | Noncryptographic record mixing with optional domain separation |
| `_guarded_seed64` | 2 | 64 | Reserved-zero probe seed, compiled to conditional selects |
| `_adaptive_gain32` | 3 | 32 | Unsigned piecewise gain, compiled to conditional selects |

For example:

```sh
rewynth evaluate --example-branches --function _guarded_morton32 --arguments 2 --inputs 1 2
rewynth evaluate --example-branches --function _window_tag64 --arguments 3 --word-bits 64 --inputs 18 17 32
rewynth recover --example-branches --function _record_hash64 --arguments 4 --word-bits 64
```

The Morton result is 9. The window-tag result is `0x910a2dec89025cc1`; values outside the window map to zero. Morton saturation equals one valid coordinate's result, so it is not an unambiguous error code. Hash-like examples make no cryptographic, uniqueness or statistical-quality claim. Deriving a reusable inverse is a separate restricted operation; lossy branch functions do not automatically receive a two-sided inverse.

The original image kernels, xxHash excerpt and public-domain SplitMix adapter keep their prior sources and notices. These new original fixtures use the project's MIT license and contain no copied third-party excerpts.

## Validation for version 0.3

The local suite ran 71 tests successfully, with one socket test skipped by the execution sandbox. That loopback API test passed separately with native socket permission. The product test compares all four branching families against original owned CPU execution, generated C and separate Python references on 4,808 input vectors. Native tests skip explicitly on other architectures; uploaded artifacts remain data only.

A fresh semantic review exercised 105 owned assembly functions with 11,865 native/model and trace comparisons, including signed/unsigned flags, 32/64-bit compare/test branches, merged flags and shared returns. It found a reachable-decoding gap and a source-translation regression; both were repaired and rechecked. A 121-instruction, 180-edge graph representing 2^60 paths lifted in 0.022 seconds on the local ARM64 Mac without enumerating paths. Its editable source exceeded the separate source budget and was correctly refused. That timing is one local structural experiment, not a throughput guarantee.

The separately installed wheel was operated through the actual browser: recovery, executed branch traces, an incorrect edit counterexample, C download, evidence download, and workspace save/reopen with proof recomputation. The browser-downloaded original C compiled and matched the owned original CPU function plus an independent reference on 4,598 inputs. These checks establish the measured examples and supported contract, not a formally verified ARM64 lifter or external adoption.
