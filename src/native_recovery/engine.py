"""Bind every operation to an explicit byte span and declared input domain."""

from hashlib import sha256
from . import recovery_core as core
from .expression import parse_expression, format_expression, emit_c


def run_operation(request, code, address, name):
    """Keep source addresses exact even in JavaScript's 53-bit number format."""

    def encode(value):
        if isinstance(value, dict):
            return {
                key: hex(item)
                if key == "address" and type(item) is int
                else encode(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    return encode(_run_operation(request, code, address, name))


def _run_operation(request, code, address, name):
    model = core.lift_function(
        code,
        address,
        name,
        request["arity"],
        request.get("domain"),
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
            result["expression"] = format_expression(inverse["ast"])
            result["source"] = emit_c(
                inverse["ast"], function_name="rewynth_inverse", argument_count=1
            )
        return result
    if operation == "recover":
        recovery = core.synthesize(model, timeout_ms=3000, max_rounds=16)
        result = {"kind": operation, "model": public, "reconstruction": recovery}
        if recovery.get("ast") is not None:
            result["expression"] = format_expression(recovery["ast"])
            result["source"] = emit_c(recovery["ast"], argument_count=model.arity)
        return result
    if operation == "verify":
        source = request.get("expression")
        if not isinstance(source, str):
            raise ValueError("An editable expression is required.")
        candidate = parse_expression(source)
        proof = core.verify_ast(model, candidate, timeout_ms=5000)
        return {
            "kind": operation,
            "model": public,
            "verification": proof,
            "expression": format_expression(candidate),
            "source": emit_c(candidate, argument_count=model.arity),
        }
    if operation == "inverse":
        target = request.get("target")
        if type(target) is not int or not 0 <= target <= 0xFFFFFFFF:
            raise ValueError("Target must be an unsigned 32-bit bit pattern.")
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
            or any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in values)
        ):
            raise ValueError("Supply one unsigned 32-bit input pattern per argument.")
        for value, domain in zip(values, model.domain):
            if domain is None:
                continue
            interpreted = core.signed(value) if domain.get("signed") else value
            if not domain["min"] <= interpreted <= domain["max"]:
                raise ValueError("Input lies outside the declared domain.")
        return {
            "kind": operation,
            "model": public,
            "witness": {
                "inputs_u32": values,
                "inputs_i32": [core.signed(v) for v in values],
                "output_u32": model.evaluate(values),
                "trace": model.trace(values),
            },
        }
    raise ValueError("Unknown operation.")
