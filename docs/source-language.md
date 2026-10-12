# Editable source

The language is deliberately small. Python's syntax parser reads it; Python never evaluates or executes it.

Inputs are `x0` through `x3`, representing declared 32-bit register bit patterns. Constants are unsigned decimal or hexadecimal words; unary `-` wraps a valid magnitude modulo 2³².

| Construct | Meaning |
|---|---|
| `+`, `-`, `*` | Arithmetic modulo 2³² |
| `&`, `|`, `^` | Bitwise AND, OR, XOR |
| `<<`, `>>` | Left and logical right shift; count masked to 0–31 |
| `asr(a,b)` | Arithmetic right shift with sign fill |
| `lt(a,b)`, `gt(a,b)` | Signed 32-bit comparison |
| `ult(a,b)`, `ugt(a,b)` | Unsigned comparison |
| `eq(a,b)` | Equal bit patterns |
| `ifelse(condition,yes,no)` | Pure conditional expression |
| `reverse(value,width)` | Reverse the lowest 1–32 bits into the low positions |

Up to 32 prior-only bindings named `t0` through `t31` can precede the final expression:

```
t0 = x0 ^ (x0 >> 15)
t1 = t0 * 0x85ebca77
t2 = t1 ^ (t1 >> 13)
t3 = t2 * 0xc2b2ae3d
t3 ^ (t3 >> 16)
```

Bindings cannot overwrite inputs, be assigned twice or refer forward. Arithmetic operands must be words; comparison results are Boolean. A numeric `ifelse` condition is explicitly interpreted as nonzero. The top-level result must be a word.

Attributes, indexing, strings, imports, arbitrary calls, comprehensions, lambdas, loops and other statements are rejected. Source is bounded to 64 KiB. Expanded ASTs remain limited to 256 nodes and depth 24 even when bindings share subexpressions. Structural sharing reduces display and C duplication; it does not bypass analysis limits.

Generated C uses `uint32_t` temporaries, defined shift counts, sign-bit biased signed comparisons and unsigned sign fill. Multiplication uses `uint64_t` before truncating so integer promotions do not introduce signed overflow. Shared subexpressions are emitted once. The emitted source is independent of Python, Capstone and Z3.
