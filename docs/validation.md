# Validation record

These are observed development checks on ARM64 macOS with Apple Clang 21.0.0, Python 3.12, Capstone 5.0.6 and Z3 4.15.3. Separate result classes matter.

| Check | Observed result | Limit |
|---|---|---|
| Six compiled forward kernels versus recovered native C and instruction model | 60,036 concrete cases agreed | Identified public/owned fixtures and boundary/random inputs |
| Six reconstructed forward native artifacts versus original model | Output inequality UNSAT in all six stated domains | Implemented instruction semantics; luma uses RGB 0–255 |
| 27 owned instruction fixtures | 17,712 CPU comparisons agreed | Specific tested instruction forms |
| Final product's own shared-expression C exports | 3,046 CPU comparisons agreed; six rebuilt model checks UNSAT | Distinct final C emitter; same identified forward fixtures |
| Independent flag/condition review | 1,792 boundary evaluations agreed | Actual compiled fixture plus independently computed expectations |
| Source language / C emitter | 4,600 generated C values matched an independent oracle under Clang UBSan | Test programs, not arbitrary user programs |
| Added BFXIL field semantics | 1,745 CPU and model comparisons agreed | Five field shapes with boundaries and random inputs |
| Three derived inverse programs | 12,060 native roundtrip assertions passed | xxHash avalanche, Murmur fmix32 and one owned permutation; 2,010 inputs in two directions each |
| Inverse chain binding and each primitive in both directions | UNSAT | Compositional proof under the selected machine model |
| Whole inverse nonlinear compositions and rebuilt inverse model comparison | UNKNOWN at bounded solver deadlines | Not rewritten as an exhaustive solver proof |
| Unfamiliar reviewed functions | General bit-linear and nonlinear recovery; edits produced counterexamples | Two independently authored functions |
| HTTP integration | Recovery, comparison, counterexample, evaluation, inverse query, inverse program, four-input export and relocation rejection passed | Loopback process/API boundary |

The counts overlap in mechanisms and must not be added into a universal coverage claim. Recompile checks support the specific artifacts; none proves the compiler, calling convention, solver or lifter universally correct.

Independent review found and corrected actual errors: shifted immediates, wide carry lowering, unresolved relocation placeholders and width overlap, aggregate parsing budgets, Boolean numeric fields, one-bit reversal, unbounded shared-expression expansion, C header name collisions and workspace edit restoration. The malformed input regressions fail before a result is presented as equivalent.

The workbench was also operated against the compiled example: a deliberately unsigned clamp edit produced original `0x00000000` versus edited `0x000000ff`; a derived avalanche inverse produced original input `0x471f246e` for output `0xdeadbeef`, whose original model trace returned that output. Workspace and package acceptance evidence is retained in the release receipt.

Run `python -m unittest discover -s tests -v`. A host without ARM64 macOS reports native fixture tests as skipped; data-only artifact/model tests still run. CI uses Linux Python 3.11/3.14 and ARM64 macOS Python 3.12. Hosted results and release byte verification are recorded when actually completed, rather than inferred from this local record.

## Version0.2 word-width checks

Local full suite:59 tests passed. The 64-bit addition has separate checks, not an aggregated universal coverage number:

- Builder:24 owned ARM64 instruction fixtures,11,544 native/model assertions, including mixed W/X writes, flags, shifts and high bitfields.
- Expression/C:8,588 native64 numerical comparisons under UBSan against independent arithmetic functions.
- Browser:5,54864-bit numerical comparisons and97232-bit comparisons using the actual BigInt evaluator; high-word hex/decimal packets and hidden-branch bounds checked.
- Root final product exports:1,590 original/model/recompiled-C cases across six bundled transforms and530 native inverse roundtrip assertions. A word with its lowbit above2^53 survived the exact JSON boundary.
- Fresh reviewer:6,405 CPU/model cases across21 independently authored functions;33 baseline32 model comparisons UNSAT;352 compiled inverse/native assertions. Original32 fixture digest unchanged.

Exact inverse chain binding and each local two-sided primitive proof are UNSAT. Whole nonlinear64 composition and rebuilt inverse comparisons remain UNKNOWN at bounded deadlines. A compiled reversible `wide_permute` has a shape outside the chain extractor and correctly receives no reusable inverse claim. The pure SplitMix64 adapter is supported; the original stateful function's memory accesses remain unsupported.

Hosted CI, downloaded-release bytes and actual workspace/UI checks are recorded in the final release receipt when completed. Native check counts overlap and are not summed.

## Bounded-memory transition extension (0.4.0)

The unchanged original PCG C basic `pcg32_random_r` was pinned to
`bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3` and compiled locally using
Apple Clang 21.0.0, `-arch arm64 -O2`. The packaged object SHA256 is
`ace691f7e16518d363ed0582d7a6ab9ee54c2818014b955b2ee886bf31bc556f`.
The [provenance manifest](../src/native_recovery/resources/examples/memory-provenance.json)
binds the exact source, header, license and compiler route.

Before native execution, 37 state/increment pairs were frozen: boundary
patterns, the upstream initializer and all 32 high-bit rotation selectors with
a fixed low-bit pattern. Two native calls per pair, 74 total, matched the
modeled return and both post-state words. The next return changed in 36 of 37
cases. These are finite controlled observations, not a universal CPU proof,
randomness assessment or independently published binary recovery task.

Recovered return and both state expressions verified jointly in the model.
An original edit that removes the state store is return-equivalent but has a
post-state counterexample. The library is not reported as defective. The
[complete state lesson](state-transitions.md) reproduces data-model recovery,
editing and export without executing the artifact. Older native measurements
remain historical; this extension did not rerun those closed proof cases.
