# Architecture

All production commands share `engine.run_operation`. The web interface and CLI choose explicit artifact bytes, function bounds, argument registers and domains; neither adapter adds native execution authority.

```
Thin ARM64 artifact
   → bounded Mach-O / ELF reader
   → explicit function bytes and SHA256
   → Capstone instruction decoding
   → bounded acyclic direct control-flow graph
   → owned 32/64-bit register / instruction-width flag semantics
   → Z3 bit-vector expression
      → counterexample-refined source recovery
      → edited-source falsification and witnesses
      → output-constraint queries
      → extracted reversible chain + primitive composition checks
   → bounded typed AST
   → readable shared expressions / defined C / local JS evaluation
```

`artifacts.py` owns file interpretation and relocation rejection. `recovery_core.py` owns instruction semantics, domains, source recovery and solver queries. `inversion.py` extracts chains from the expression structure and retains binding, primitive and global proof statuses separately. `expression.py` owns source parsing, structural sharing and C generation. `bitvector.js` evaluates a newly derived inverse in the interface; it compiles or executes no native code.

`words.py` validates exact input/domain values and encodes large result integers as hexadecimal strings before JSON serialization. The browser uses BigInt arithmetic and preflights the complete typed AST, including unselected branches.

`server.py` owns loopback admission, bounded artifact retention, process lifetime, deadlines and cancellation. Each job rebuilds its model from the selected immutable bytes; a process timeout produces no equivalence conclusion. CLI computations use the same process boundary. Browser workspaces retain bytes, exact settings and edit/query drafts, while restored proofs must be recomputed.

The solver and lifter are trusted parts of the model, not themselves formally verified by these checks. Independent native tests compare identified fixtures and generated C with model results. Those observations support specific tested instruction forms and do not establish correctness of arbitrary imported programs.

`control_flow.py` decodes reachable instructions, validates direct targets and topologically orders the graph. The lifter merges register values and flags under their execution guards instead of enumerating paths. Registers or flags missing on an incoming path remain unavailable. Multiple returns combine into one output expression; concrete traces filter guards and retain the actual branch/write/return order. A backward address edge is allowed when the directed graph remains acyclic. The existing 128-instruction and editable-expression bounds remain in force, with at most 256 graph edges.

## Declared state transitions

The same acyclic lifter can carry one finite little-endian memory region alongside registers and flags. Each incoming path merges all declared words, and each return captures the full post-state. `transitions.py` translates and jointly compares architectural X0 plus every post-state word. Scalar-only proof and inverse APIs refuse these models. Public request normalization and workspace v3 retain the machine-to-logical input mapping. [The full contract](state-transitions.md) records bounds and unsupported addressing.
