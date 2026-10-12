"""Bind every operation to an explicit byte span and declared input domain."""

from hashlib import sha256
from . import recovery_core as core
from .expression import parse_expression, format_expression, emit_c


def run_operation(request, code, address, name):
    """Preserve word values and source addresses across JavaScript JSON."""
    from .words import normalize_request, encode_exact

    return encode_exact(_run_operation(normalize_request(request), code, address, name))


def _run_operation(request, code, address, name):
    model = core.lift_function(
        code,
        address,
        name,
        request["arity"],
        request.get("domain"),
        word_bits=request["word_bits"],
        metadata={
            "artifact_sha256": request["artifact"],
            "sha256": request["artifact"],
            "function_sha256": sha256(code).hexdigest(),
        },
    )
    public = {
        "artifact_sha256": request["artifact"],
        "function_sha256": sha256(code).hexdigest(),
        "symbol": name,
        "instructions": model.instructions,
        "assumptions": model.assumptions(),
    }
    operation = request["operation"]
    if operation == "derive_inverse":
        from .inversion import derive_inverse

        inverse = derive_inverse(model)
        result = {"kind": operation, "model": public, "inverse_program": inverse}
        if inverse.get("status") == "verified_inverse_model":
            result["expression"] = format_expression(
                inverse["ast"], word_bits=model.word_bits
            )
            result["source"] = emit_c(
                inverse["ast"],
                function_name="rewynth_inverse",
                argument_count=1,
                word_bits=model.word_bits,
            )
        return result
    if operation == "recover":
        recovery = core.synthesize(model, timeout_ms=3000, max_rounds=16)
        result = {"kind": operation, "model": public, "reconstruction": recovery}
        if recovery.get("ast") is not None:
            result["expression"] = format_expression(
                recovery["ast"], word_bits=model.word_bits
            )
            result["source"] = emit_c(
                recovery["ast"], argument_count=model.arity, word_bits=model.word_bits
            )
        return result
    if operation == "verify":
        source = request.get("expression")
        if not isinstance(source, str):
            raise ValueError("An editable expression is required.")
        candidate = parse_expression(source, word_bits=model.word_bits)
        proof = core.verify_ast(model, candidate, timeout_ms=5000)
        return {
            "kind": operation,
            "model": public,
            "verification": proof,
            "expression": format_expression(candidate, word_bits=model.word_bits),
            "source": emit_c(
                candidate, argument_count=model.arity, word_bits=model.word_bits
            ),
        }
    if operation == "inverse":
        target = request.get("target")
        if type(target) is not int or not 0 <= target <= ((1 << model.word_bits) - 1):
            raise ValueError(
                f"Target must be an unsigned {model.word_bits}-bit bit pattern."
            )
        return {
            "kind": operation,
            "model": public,
            "query": core.inverse_query(model, target, timeout_ms=5000),
        }
    if operation == "evaluate":
        values = request.get("inputs")
        if (
            not isinstance(values, list)
            or len(values) != model.arity
            or any(
                type(v) is not int or not 0 <= v <= ((1 << model.word_bits) - 1)
                for v in values
            )
        ):
            raise ValueError(
                f"Supply one unsigned {model.word_bits}-bit input pattern per argument."
            )
        for value, domain in zip(values, model.domain):
            if domain is None:
                continue
            interpreted = (
                core.signed(value, model.word_bits) if domain.get("signed") else value
            )
            if not domain["min"] <= interpreted <= domain["max"]:
                raise ValueError("Input lies outside the declared domain.")
        return {
            "kind": operation,
            "model": public,
            "witness": {
                f"inputs_u{model.word_bits}": values,
                f"inputs_i{model.word_bits}": [
                    core.signed(v, model.word_bits) for v in values
                ],
                f"output_u{model.word_bits}": model.evaluate(values),
                "trace": model.trace(values),
            },
        }
    raise ValueError("Unknown operation.")
