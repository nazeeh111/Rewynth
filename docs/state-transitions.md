# Preserve the next call, too

A function can return the right value and leave the wrong state for its next
call. Rewynth can recover, edit and compare a small declared ARM64 memory
transition. It checks architectural X0 and every declared post-state word
together. Imported machine code is read as data and never executed.

## Run the complete example

After installing Rewynth, run:

```sh
python examples/state_lab.py --output state-lab
```

The example uses the unchanged `pcg32_random_r` function from Melissa O'Neill's
[PCG C basic library](https://github.com/imneme/pcg-c-basic/tree/bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3).
It writes recovered `transition.json`, portable `transition.c`, an original
`lost-store.json` edit, and `evidence.json`. Use a fresh output directory to
preserve existing results. The edit retains the immediate return but drops
the state update. A joint comparison must report `sat` with `memory[0]`
different; comparing only the return would miss this.

This is a controlled, source-available example compiled locally, not an
independently published binary or an upstream bug. PCG already has advance
and rewind facilities. This workflow demonstrates state-aware recovery and
editing, not random-generator quality or unique seed recovery.

## Workbench

Run `rewynth serve`, open its loopback address and select **Load PCG32 bounded state example**. Recover the transition. The input labels map `x0` to the initial
state word and `x1` to the increment word. To try the lost update, replace
the first entry in `memory` with `"x0"`, keeping the return unchanged. Compare
the edit. The counterexample shows the same returned value and different
post-state. Reset the expression to recover the original transition.

Save a workspace to retain the artifact bytes, pointer declaration, exact
inputs and editable transition. Workspaces use version 3; older register-only
versions 1 and 2 remain readable. Reopened results require a fresh comparison.
Export C to use the recovered pure transition, or export evidence to retain
the model assumptions, artifact identity and witness.

## CLI and logical inputs

```sh
rewynth recover --example-memory --function _pcg32_random_r \
  --arguments 1 --word-bits 64 --memory-argument 0 --memory-words 2

rewynth evaluate --example-memory --function _pcg32_random_r \
  --arguments 1 --word-bits 64 --memory-argument 0 --memory-words 2 \
  --inputs 0x853c49e6748fea9b 0xda3e39cb94b95bdb

rewynth verify --example-memory --function _pcg32_random_r \
  --arguments 1 --word-bits 64 --memory-argument 0 --memory-words 2 \
  --expression state-lab/lost-store.json
```

`--arguments` counts machine argument registers. The memory argument is a
pointer register indexed from zero. Its address is supplied by the model,
not by the input list. Logical inputs are the remaining scalar registers
in register order, followed by the initial 64-bit memory words in address
order. Both `--inputs` and `--domain` use this logical order. At most four
logical inputs are supported. In the PCG example, one pointer register
becomes two logical state inputs. HTTP requests carry 64-bit values as
decimal or hexadecimal strings to preserve every bit.

## Edit and export contract

The editable document has exactly two fields:

```json
{
  "return": "x0 + 1",
  "memory": ["x0 + 1", "x1"]
}
```

This small illustrative transition is not PCG. Each string uses the existing
[safe expression language](source-language.md). Outputs are simultaneous:
all expressions read the original inputs. Every memory word needs an
expression, even if unchanged. The whole document is at most 64 KiB; each
expanded expression retains the 256-node and depth-24 bounds. Duplicate or
unknown fields, missing words, arbitrary code and boolean outputs refuse.

Generated C accepts the logical `uint64_t` inputs and returns a
`rewynth_state` structure with `result` and `memory[]`. It does not dereference
an input pointer or replace the native function ABI. The exported return is
architectural X0, including zero extension when the last result write is W0.
It expresses the implemented model, not a certificate for every CPU.

## Explicit memory boundary

Memory is opt-in and available only in 64-bit register mode. Declare one
pointer and 1–3 consecutive little-endian 64-bit words. The pointer is bound
to the synthetic address `0x100000000`. Equality covers that declared model,
not arbitrary base addresses, alias layouts, stack or global memory.
Only concrete, in-bounds fixed-displacement loads/stores are supported.
Symbolic/indexed addresses, writeback, undeclared accesses, calls, loops and
unsupported instruction forms refuse. The entire declared post-state is
compared, not only bytes that happened to be written. Inverse queries and
inverse programs explicitly refuse memory mode.

`unsat` means no joint difference was found possible under the declared
domain and implemented semantics. `sat` supplies a counterexample. `unknown`
or a refusal supplies no equivalence conclusion. The existing 20-second
owned analysis process and solver budgets remain in force.
