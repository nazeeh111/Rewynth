# Word width and state rewind

The selected model declares `word_bits` as exactly 32 or 64; omitted means 32. This is an argument/result declaration, not automatic calling-convention inference. Instructions have their own operand width. In a 64-bit model, reading `wN` extracts the lower 32 bits, and writing it zero-extends the value into `xN`. Arithmetic flags use the instruction's width; W shifts mask to 31 and X shifts to 63. Unsupported operand forms still fail closed.

## Exact wire values

For 64-bit HTTP requests, `inputs`, `target` and non-null domain min/max fields are **decimal or hexadecimal strings**. JSON numbers are rejected even when a specific small value would be representable. The server validates ordered domains and exact values before starting a worker. `word_bits` and argument count remain small JSON integers. Internal Python ASTs and computations use arbitrary-precision integers constrained to the selected word.

Output values outside JavaScript's safe integer range are hexadecimal strings. Witness fields use `inputs_u64`, `inputs_i64`, `output_u64` and `value_u64` in 64-bit mode. The 32-bit fields and numeric behavior remain unchanged. AST constants can therefore arrive as exact hex strings; the browser's bounded BigInt evaluator checks every branch before computing an inverse locally. No source is passed to `eval`.

```json
{"operation":"evaluate","artifact":"<artifact SHA-256>","symbol":"_splitmix64_step","arity":1,"word_bits":64,"inputs":["0x123456789abcdef0"],"domain":[null]}
```

Workspace versions 2 and 3 store word size, exact textual queries, original bytes and edits. Version 1 is explicitly 32-bit. Reopening never treats old proof evidence as a fresh comparison. Changing word size invalidates the comparison, inverse program and trace.

## The real fixture boundary

The selected `splitmix64_step(before_state)` is a marked pure adapter of Vigna's 2015 public-domain implementation. Global state becomes an explicit argument; write-back is outside the analyzed function. Its arithmetic, constants and increment are unchanged. The original stateful source is kept separately for controlled oracle tests and is not accepted as a memory-free function.

Prior state zero produces full output `0xe220a8397b1dcdaf`. A derived inverse recovers zero. With a known call number, subtracting preceding increments recovers the designated initial state; an unknown call number identifies a trajectory position. This is not recovery from truncated output, ordinary Raylib random numbers, another generator or cryptographic output.

Proofs apply to the implemented selected-word instruction model. Exact chain binding and both directions of each supported primitive are required for compositional acceptance. Whole nonlinear composition checks can remain UNKNOWN. Native comparisons exercise only identified licensed/owned fixtures and generated C, never an uploaded artifact.

Source and binary hashes, immutable upstream identity and full notices are in `resources/examples/wide-provenance.json` and packaged third-party notices. Do not reuse a fixture digest after recompilation changes its bytes.

Version 3 also stores an optional bounded-memory declaration. [State-transition contracts](state-transitions.md) define logical input order, full post-state comparison and pure C exports. Versions 1 and 2 remain readable as register-only workspaces.
