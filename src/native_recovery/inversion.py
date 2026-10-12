"""Derive reusable inverse programs from selected reversible uint32 semantics.

This module executes no native code. The extraction is bound to the lifted
function expression, and all proof claims retain the lifter's assumptions.
"""

from __future__ import annotations
import hashlib
import json
import time
import z3
from . import recovery_core as core

_MASK = 0xFFFFFFFF


def _const(value, word_bits=32):
    return core.constant(value,word_bits)


def _input():
    return {"op": "input", "index": 0}


def _binary(op, a, b):
    return {"op": op, "a": a, "b": b}


def _balanced_xor(nodes):
    if len(nodes) == 1:
        return nodes[0]
    middle = len(nodes) // 2
    return _binary("xor", _balanced_xor(nodes[:middle]), _balanced_xor(nodes[middle:]))


def _rotate(value, amount, right, word_bits=32):
    amount %= word_bits
    if not amount:
        return value
    first, second = ("lshr", "shl") if right else ("shl", "lshr")
    return _binary(
        "or",
        _binary(first, value, _const(amount, word_bits)),
        _binary(second, value, _const(word_bits - amount, word_bits)),
    )


def _apply(value, step, inverse=False, word_bits=32):
    C = lambda v: _const(v, word_bits)
    op = step["op"]
    constant = step.get(f"constant_u{word_bits}", 0)
    if op == "add":
        return _binary("sub" if inverse else "add", value, C(constant))
    if op == "sub":
        return _binary("add" if inverse else "sub", value, C(constant))
    if op == "constant_sub":
        return _binary("sub", C(constant), value)
    if op == "xor":
        return _binary("xor", value, C(constant))
    if op == "mul_odd":
        return _binary(
            "mul", value, C(step[f"inverse_constant_u{word_bits}"] if inverse else constant)
        )
    if op == "negate":
        return _binary("sub", C(0), value)
    if op == "rotate_right" or op == "rotate_left":
        return _rotate(value, step["amount"], (op == "rotate_right") != inverse, word_bits)
    if op == f"reverse{word_bits}":
        return {"op": "reverse", "arg": value, "width": word_bits}
    if op == "xor_right" or op == "xor_left":
        amount = step["amount"]
        shift = "lshr" if op == "xor_right" else "shl"
        if not inverse:
            return _binary("xor", value, _binary(shift, value, C(amount)))
        # In GF(2), (I+S)^-1 = I+S+S²+...; S^ceil(32/amount)=0.
        terms = [value]
        for distance in range(amount, word_bits, amount):
            terms.append(_binary(shift, value, C(distance)))
        return _balanced_xor(terms)
    raise core.Unsupported(f"Unsupported inverse primitive {op}")


def _full_domain(model):
    if len(model.domain) != 1:
        return False
    entry = model.domain[0]
    if entry is None:
        return True
    if entry.get("signed", False):
        return entry["min"] == -(1 << (model.word_bits-1)) and entry["max"] == (1 << (model.word_bits-1)) - 1
    return entry["min"] == 0 and entry["max"] == core._mask(model.word_bits)


def _extract_chain(expr, source, max_steps, word_bits=32):
    """Extract a chain from expression structure, never from a function name."""
    variable = source.get_id()
    dependency_cache = {}
    visits = [0]

    def depends(node):
        identifier = node.get_id()
        if identifier in dependency_cache:
            return dependency_cache[identifier]
        visits[0] += 1
        if visits[0] > 4096:
            raise core.Unsupported("Inverse extraction exceeds expression budget")
        result = identifier == variable or any(
            depends(child) for child in node.children()
        )
        dependency_cache[identifier] = result
        return result

    def constant(node):
        if depends(node):
            return None
        value = z3.simplify(node)
        if not z3.is_bv_value(value) or value.size() != word_bits:
            raise core.Unsupported(f"Inverse chain requires uint{word_bits} constants")
        return value.as_long()

    def walk(node, depth=0):
        if depth > max_steps:
            raise core.Unsupported("Inverse chain exceeds step budget")
        if node.get_id() == variable:
            return []
        if not z3.is_bv(node) or node.size() != word_bits:
            raise core.Unsupported(f"Inverse chain requires full-width uint{word_bits} values")
        kind = node.decl().kind()
        children = list(node.children())
        if (
            kind in {z3.Z3_OP_BADD, z3.Z3_OP_BSUB, z3.Z3_OP_BMUL, z3.Z3_OP_BXOR}
            and len(children) == 2
        ):
            a, b = children
            ca, cb = constant(a), constant(b)
            if kind == z3.Z3_OP_BXOR and ca is None and cb is None:
                for value, shifted in [(a, b), (b, a)]:
                    shift_kind = shifted.decl().kind()
                    if (
                        shift_kind not in {z3.Z3_OP_BLSHR, z3.Z3_OP_BSHL}
                        or shifted.num_args() != 2
                    ):
                        continue
                    if shifted.arg(0).get_id() != value.get_id():
                        continue
                    amount = constant(shifted.arg(1))
                    if amount is None or not 1 <= amount < word_bits:
                        raise core.Unsupported(
                            f"Self XOR shift amount must be from 1 to {word_bits-1}"
                        )
                    return walk(value, depth + 1) + [
                        {
                            "op": "xor_right"
                            if shift_kind == z3.Z3_OP_BLSHR
                            else "xor_left",
                            "amount": amount,
                        }
                    ]
            if (ca is None) == (cb is None):
                raise core.Unsupported(
                    "Inverse chain needs one varying operand and one constant"
                )
            value, coefficient = (a, cb) if cb is not None else (b, ca)
            if kind == z3.Z3_OP_BMUL:
                if coefficient % 2 == 0:
                    raise core.Unsupported(
                        f"Even multiplication is not bijective modulo 2^{word_bits}"
                    )
                step = {
                    "op": "mul_odd",
                    f"constant_u{word_bits}": coefficient,
                    f"inverse_constant_u{word_bits}": pow(coefficient, -1, 1 << word_bits),
                }
            else:
                op = {
                    z3.Z3_OP_BADD: "add",
                    z3.Z3_OP_BSUB: "sub" if cb is not None else "constant_sub",
                    z3.Z3_OP_BXOR: "xor",
                }[kind]
                step = {"op": op, f"constant_u{word_bits}": coefficient}
            return walk(value, depth + 1) + [step]
        if (
            kind in {z3.Z3_OP_EXT_ROTATE_RIGHT, z3.Z3_OP_EXT_ROTATE_LEFT}
            and len(children) == 2
        ):
            amount = constant(children[1])
            if amount is None:
                raise core.Unsupported(
                    "Variable rotations are outside inverse-chain scope"
                )
            return walk(children[0], depth + 1) + [
                {
                    "op": "rotate_right"
                    if kind == z3.Z3_OP_EXT_ROTATE_RIGHT
                    else "rotate_left",
                    "amount": amount % word_bits,
                }
            ]
        if kind == z3.Z3_OP_BNEG:
            return walk(children[0], depth + 1) + [{"op": "negate"}]
        if kind == z3.Z3_OP_BNOT:
            return walk(children[0], depth + 1) + [{"op": "xor", f"constant_u{word_bits}": core._mask(word_bits)}]
        # RBIT's symbolic semantics is a concatenation of the source's low bit first.
        if kind == z3.Z3_OP_CONCAT:
            bits, stack = [], [node]
            while stack:
                item = stack.pop()
                if item.decl().kind() == z3.Z3_OP_CONCAT:
                    stack.extend(reversed(list(item.children())))
                else:
                    bits.append(item)
                if len(bits) + len(stack) > word_bits*2:
                    raise core.Unsupported(
                        "Bit reversal extraction exceeds width budget"
                    )
            candidate = (
                bits[0].arg(0)
                if bits and bits[0].decl().kind() == z3.Z3_OP_EXTRACT
                else None
            )
            if (
                len(bits) == word_bits
                and candidate is not None
                and candidate.size() == word_bits
                and all(
                    bit.decl().kind() == z3.Z3_OP_EXTRACT
                    and bit.params() == [index, index]
                    and bit.arg(0).get_id() == candidate.get_id()
                    for index, bit in enumerate(bits)
                )
            ):
                return walk(candidate, depth + 1) + [{"op": f"reverse{word_bits}"}]
        raise core.Unsupported(
            f"Non-chain or unsupported inverse operation: {node.decl().name()}"
        )

    return walk(expr)


def _prove_equal(left, right, timeout_ms):
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    solver.add(left != right)
    result = solver.check()
    proof = {"status": str(result)}
    if result == z3.unknown:
        proof["reason"] = solver.reason_unknown()
    elif result == z3.sat:
        variables = sorted(
            {
                str(node): node
                for expression in [left, right]
                for node in _variables(expression)
            }.items()
        )
        model = solver.model()
        proof["counterexample"] = {
            name: model.eval(value, model_completion=True).as_long()
            for name, value in variables
        }
    return proof


def _variables(expr):
    seen = set()
    stack = [expr]
    while stack:
        value = stack.pop()
        if value.get_id() in seen:
            continue
        seen.add(value.get_id())
        if z3.is_const(value) and value.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            yield value
        stack.extend(value.children())


def derive_inverse(model, timeout_ms=1000, max_steps=32):
    """Return a verified reusable backward AST, or an explicit unsupported result.

    Global nonlinear composition may time out. Successful local two-sided
    primitive proofs plus exact chain binding establish a compositional result;
    global check statuses remain visible and are never rewritten as UNSAT.
    """
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 5000:
        raise ValueError("Inverse proof timeout must be 1–5000 ms")
    if type(max_steps) is not int or not 1 <= max_steps <= 64:
        raise ValueError("Inverse chain limit must be 1–64")
    W=model.word_bits
    core._word_bits(W)
    started = time.monotonic()
    base = {
        "symbol": model.symbol,
        "artifact_sha256": model.metadata.get("sha256"),
        "assumptions": model.assumptions(),
        "scope": f"Reusable two-sided uint{W} inverse under the implemented machine model; not inversion of a complete variable-length hash.",
    }
    if model.arity != 1:
        return {
            **base,
            "status": "unsupported",
            "reason": f"Inverse programs require exactly one uint{W} input",
        }
    if not _full_domain(model):
        return {
            **base,
            "status": "unsupported_domain",
            "reason": f"All-input inverse claim requires the declared domain to contain all 2^{W} input patterns",
        }
    try:
        chain = _extract_chain(model.expr, model.inputs[0], max_steps, W)
        forward = _input()
        for step in chain:
            forward = _apply(forward, step, word_bits=W)
        backward = _input()
        for step in reversed(chain):
            backward = _apply(backward, step, inverse=True, word_bits=W)
        forward_expr = core.ast_expr(forward, model.inputs)
        inverse_expr = core.ast_expr(backward, model.inputs)
        if not z3.is_bv(forward_expr) or not z3.is_bv(inverse_expr):
            raise core.Unsupported(f"Inverse programs must produce uint{W} values")
    except core.Unsupported as error:
        return {
            **base,
            "status": "unsupported",
            "reason": str(error),
            "elapsed_seconds": time.monotonic() - started,
        }
    binding = _prove_equal(model.expr, forward_expr, timeout_ms)
    local = []
    variable = z3.BitVec("inverse_primitive_input", W)
    for index, step in enumerate(chain):
        f = core.ast_expr(_apply(_input(), step, word_bits=W), [variable])
        g = core.ast_expr(_apply(_input(), step, inverse=True, word_bits=W), [variable])
        local.append(
            {
                "step": index,
                "primitive": step,
                "forward_after_inverse": _prove_equal(
                    z3.substitute(f, (variable, g)), variable, timeout_ms
                ),
                "inverse_after_forward": _prove_equal(
                    z3.substitute(g, (variable, f)), variable, timeout_ms
                ),
            }
        )
    source = model.inputs[0]
    global_checks = {
        "forward_after_inverse": _prove_equal(
            z3.substitute(model.expr, (source, inverse_expr)), source, timeout_ms
        ),
        "inverse_after_forward": _prove_equal(
            z3.substitute(inverse_expr, (source, model.expr)), source, timeout_ms
        ),
    }
    required = [binding] + [
        entry[key]
        for entry in local
        for key in ["forward_after_inverse", "inverse_after_forward"]
    ]
    proven = all(proof["status"] == "unsat" for proof in required)
    inconsistent = any(
        proof["status"] == "sat" for proof in required + list(global_checks.values())
    )
    if inconsistent:
        status = "falsified"
    elif proven:
        status = "verified_inverse_model"
    else:
        status = "unknown"
    return {
        **base,
        "status": status,
        "ast": backward,
        "forward_ast": forward,
        "chain": chain,
        "chain_sha256": hashlib.sha256(
            json.dumps(chain, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "proofs": {
            "chain_binding": binding,
            "local_two_sided": local,
            "global_compositions": global_checks,
            "basis": "compositional" if proven else "incomplete",
        },
        "elapsed_seconds": time.monotonic() - started,
    }
