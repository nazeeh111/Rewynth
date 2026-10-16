"""Safe editable, simultaneous return-and-memory transitions.

All declared post-state words are observable, even if the function never writes
them. This module never evaluates user source as Python or loads target code.
"""

import json
import z3

from . import recovery_core as core
from .expression import parse_expression, format_expression, emit_c


def input_count(arity, memory=None, word_bits=64):
    """Validate the opt-in declaration at each public request boundary."""
    if type(arity) is not int or not 1 <= arity <= 4:
        raise ValueError("Select one to four machine argument registers.")
    if memory is None:
        return arity
    if word_bits != 64:
        raise ValueError("Declared memory requires 64-bit register mode.")
    if (
        not isinstance(memory, dict)
        or set(memory) != {"argument", "words"}
        or type(memory["argument"]) is not int
        or not 0 <= memory["argument"] < arity
        or type(memory["words"]) is not int
        or not 1 <= memory["words"] <= 3
        or arity - 1 + memory["words"] > 4
    ):
        raise ValueError(
            "Memory requires one pointer argument, 1–3 words, and at most four logical inputs."
        )
    return arity - 1 + memory["words"]


def parse_transition(source, model):
    try:
        within_limit = isinstance(source, str) and len(source.encode("utf-8")) <= 65536
    except UnicodeError:
        within_limit = False
    if not within_limit:
        raise ValueError("Transition text must be at most 64 KiB.")
    # Reject duplicate keys instead of accepting an ambiguous editable document.
    def unique(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("Duplicate transition key.")
            output[key] = value
        return output

    try:
        document = json.loads(source, object_pairs_hook=unique)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Transition must be a JSON object with return and memory expressions.") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"return", "memory"}
        or not isinstance(document["return"], str)
        or not isinstance(document["memory"], list)
        or len(document["memory"]) != len(model.post_memory)
        or any(not isinstance(value, str) for value in document["memory"])
    ):
        raise ValueError("Supply return and exactly one expression per declared memory word.")
    asts = [parse_expression(value, word_bits=64) for value in [document["return"], *document["memory"]]]
    # This also rejects nonexistent logical inputs and boolean-valued results.
    for ast in asts:
        value = core.ast_expr(ast, model.inputs, word_bits=64)
        if not z3.is_bv(value) or value.size() != 64:
            raise ValueError("Every transition output must be a 64-bit word.")
    return asts


def format_transition(asts):
    texts = [format_expression(ast, word_bits=64) for ast in asts]
    source = json.dumps({"return": texts[0], "memory": texts[1:]}, indent=2)
    if len(source.encode("utf-8")) > 65536:
        raise core.Unsupported("Editable transition exceeds 64 KiB.")
    return source


def verify_transition(model, asts, timeout_ms=5000):
    if len(asts) != 1 + len(model.post_memory):
        raise ValueError("Transition output count differs from the declared state.")
    candidates = [core.ast_expr(ast, model.inputs, word_bits=64) for ast in asts]
    if any(not z3.is_bv(value) or value.size() != 64 for value in candidates):
        raise ValueError("Every transition output must be a 64-bit word.")
    originals = [model.expr, *model.post_memory]
    solver = core._solver(timeout_ms)
    solver.add(*model.constraints(), z3.Or(*[a != b for a, b in zip(originals, candidates)]))
    status = solver.check()
    result = {"status": str(status), "assumptions": model.assumptions(), "observations": ["return", *[f"memory[{i}]" for i in range(len(model.post_memory))]]}
    if status == z3.sat:
        assignment = solver.model()
        values = [assignment.eval(x, model_completion=True).as_long() for x in model.inputs]
        substitutions = [(x, core.bv(value, 64)) for x, value in zip(model.inputs, values)]
        candidate = [z3.simplify(z3.substitute(value, *substitutions)).as_long() for value in candidates]
        original = model.evaluate_transition(values)
        observed = [original["return"], *original["memory"]]
        result["counterexample"] = {
            "inputs_u64": values,
            "inputs_i64": [core.signed(value, 64) for value in values],
            "original_output_u64": original["return"],
            "candidate_output_u64": candidate[0],
            "original_memory_u64": original["memory"],
            "candidate_memory_u64": candidate[1:],
            "differences": [name for name, a, b in zip(result["observations"], observed, candidate) if a != b],
            "trace": model.trace(values),
        }
    elif status == z3.unknown:
        result["reason"] = solver.reason_unknown()
    return result


def recover_transition(model):
    asts = [core.expression_to_ast(value, model.inputs, word_bits=64) for value in [model.expr, *model.post_memory]]
    verification = verify_transition(model, asts)
    reconstruction = {
        "status": "verified_model" if verification["status"] == "unsat" else verification["status"],
        "grammar": "bounded_state_transition",
        "verification": verification,
    }
    if verification["status"] != "unsat":
        return {"reconstruction": reconstruction}
    return {"reconstruction": reconstruction, "expression": format_transition(asts), "source": emit_transition_c(asts, model.arity)}


def emit_transition_c(asts, arity):
    # Each established scalar emitter owns its local temporaries. Static helper
    # names are fixed, bounded and distinct. All expressions see original inputs.
    helpers = ["static " + emit_c(ast, function_name=f"rewynth_observation_{i}", argument_count=arity, word_bits=64).split("\n\n", 1)[1] for i, ast in enumerate(asts)]
    signature = ", ".join(f"uint64_t x{i}" for i in range(arity))
    arguments = ", ".join(f"x{i}" for i in range(arity))
    fields = [f"    output.result = rewynth_observation_0({arguments});"]
    fields.extend(f"    output.memory[{i}] = rewynth_observation_{i+1}({arguments});" for i in range(len(asts)-1))
    return (
        "/* Pure transition: logical inputs are original scalars then initial memory words.\n"
        "   All declared post-state words and architectural X0 are returned.\n"
        "   This is reconstructed model source, not the original pointer ABI. */\n"
        "#include <stdint.h>\n#include <stdbool.h>\n\n"
        + "\n".join(helpers)
        + f"\ntypedef struct {{ uint64_t result; uint64_t memory[{len(asts)-1}]; }} rewynth_state;\n"
        + f"rewynth_state rewynth_transition({signature}) {{\n    rewynth_state output;\n"
        + "\n".join(fields) + "\n    return output;\n}\n"
    )
