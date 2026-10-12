# Architecture

All production commands share `engine.run_operation`. The web interface and CLI choose explicit artifact bytes, function bounds, argument registers and domains; neither adapter adds native execution authority.

```
Thin ARM64 artifact
   → bounded Mach-O / ELF reader
   → explicit function bytes and SHA256
   → Capstone instruction decoding
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
