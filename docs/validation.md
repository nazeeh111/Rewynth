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
