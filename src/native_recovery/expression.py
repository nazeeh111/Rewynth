"""A bounded, editable expression language for 32-bit recovered functions.

Python's parser is used only to obtain syntax nodes. No expression is evaluated,
imported, or executed. The resulting JSON tree uses the recovery core's schema.
Arithmetic wraps modulo 2**32; shift counts are masked to five bits. ``lt`` and
``gt`` are signed comparisons, ``ult`` and ``ugt`` unsigned. ``asr`` sign-fills.
``reverse(value, width)`` reverses the lowest width bits into the same low range.
Programs may define prior-only t0..t31 bindings before their final expression.
Bindings are aliases, and the expanded expression retains the node/depth limits.
"""

from __future__ import annotations

import ast
import re

MAX_SOURCE_BYTES = 64 * 1024
MAX_NODES = 256
MAX_DEPTH = 24
MAX_BINDINGS = 32
MASK = 0xFFFFFFFF


class ExpressionError(ValueError):
    """Invalid, unsupported, or over-budget editable expression."""


_BINARY = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.BitAnd: "and",
    ast.BitOr: "or",
    ast.BitXor: "xor",
    ast.RShift: "lshr",
    ast.LShift: "shl",
}
_OPERATOR = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "and": "&",
    "or": "|",
    "xor": "^",
    "lshr": ">>",
    "shl": "<<",
}
_CALLS = {
    "asr": "ashr",
    "lt": "slt",
    "gt": "sgt",
    "ult": "ult",
    "ugt": "ugt",
    "eq": "eq",
}
_COMPARISONS = {"slt", "sgt", "ult", "ugt", "eq"}
_ARITHMETIC = set(_OPERATOR) | {"ashr"}
_C_RESERVED = set(
    "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while _Alignas _Alignof _Atomic _Bool _Complex _Generic _Imaginary _Noreturn _Static_assert _Thread_local".split()
)
# Names introduced by the generated translation unit's public standard headers.
_C_RESERVED.update(
    "bool true false intptr_t uintptr_t intmax_t uintmax_t INTPTR_MIN INTPTR_MAX UINTPTR_MAX INTMAX_MIN INTMAX_MAX UINTMAX_MAX PTRDIFF_MIN PTRDIFF_MAX SIG_ATOMIC_MIN SIG_ATOMIC_MAX SIZE_MAX WCHAR_MIN WCHAR_MAX WINT_MIN WINT_MAX INTMAX_C UINTMAX_C".split()
)
for _width in (8, 16, 32, 64):
    for _family in ("", "least", "fast"):
        _middle = f"_{_family}" if _family else ""
        _C_RESERVED.update((f"int{_middle}{_width}_t", f"uint{_middle}{_width}_t"))
        _upper = f"_{_family.upper()}" if _family else ""
        _C_RESERVED.update(
            (
                f"INT{_upper}{_width}_MIN",
                f"INT{_upper}{_width}_MAX",
                f"UINT{_upper}{_width}_MAX",
            )
        )
    _C_RESERVED.update((f"INT{_width}_C", f"UINT{_width}_C"))


def _error(message: str) -> None:
    raise ExpressionError(message)


def _check_ast(node: dict) -> str:
    """Validate complete shape and types, including untrusted JSON AST inputs."""
    count = 0

    def visit(current, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES:
            _error(f"expression exceeds {MAX_NODES} nodes")
        if depth > MAX_DEPTH:
            _error(f"expression exceeds depth {MAX_DEPTH}")
        if not isinstance(current, dict):
            _error("expression nodes must be objects")
        op = current.get("op")
        if type(op) is not str:
            _error("expression operation must be a string")
        if op == "input":
            if (
                set(current) != {"op", "index"}
                or type(current["index"]) is not int
                or not 0 <= current["index"] <= 3
            ):
                _error("input must name x0, x1, x2, or x3")
            return "u32"
        if op == "const":
            if (
                set(current) != {"op", "value"}
                or type(current["value"]) is not int
                or not 0 <= current["value"] <= MASK
            ):
                _error("constants must fit unsigned 32-bit integers")
            return "u32"
        if op in _ARITHMETIC | _COMPARISONS:
            if set(current) != {"op", "a", "b"}:
                _error(f"{op} requires exactly two operands")
            if (
                visit(current["a"], depth + 1) != "u32"
                or visit(current["b"], depth + 1) != "u32"
            ):
                _error(f"{op} requires integer operands")
            return "bool" if op in _COMPARISONS else "u32"
        if op == "ite":
            if set(current) != {"op", "condition", "then", "else"}:
                _error("ifelse requires condition, then, and else operands")
            if visit(current["condition"], depth + 1) != "bool":
                _error("conditional AST requires a Boolean comparison")
            if (
                visit(current["then"], depth + 1) != "u32"
                or visit(current["else"], depth + 1) != "u32"
            ):
                _error("ifelse branches must be integers")
            return "u32"
        if op == "reverse":
            if (
                set(current) != {"op", "arg", "width"}
                or type(current["width"]) is not int
                or not 1 <= current["width"] <= 32
            ):
                _error("reverse width must be an integer from 1 to 32")
            if visit(current["arg"], depth + 1) != "u32":
                _error("reverse requires an integer operand")
            return "u32"
        _error(f"unknown expression operation: {op!r}")

    return visit(node, 1)


def parse_expression(text: str) -> dict:
    """Translate a safe expression or binding program into the bounded core AST."""
    if not isinstance(text, str):
        _error("expression source must be text")
    try:
        byte_count = len(text.encode("utf-8"))
    except UnicodeError:
        _error("expression source must be valid UTF-8 text")
    if byte_count > MAX_SOURCE_BYTES:
        _error(f"expression source exceeds {MAX_SOURCE_BYTES} bytes")
    if not text.strip():
        _error("expression source is empty")
    try:
        parsed = ast.parse(text.strip(), mode="exec")
    except (SyntaxError, RecursionError, ValueError) as exc:
        _error(f"invalid expression syntax: {str(exc).splitlines()[0]}")
    # Bound syntax before recursive translation. Context/operator marker nodes
    # do not carry expressions; syntax expression nodes and core nodes are bound.
    syntax_count = 0
    for current in ast.walk(parsed):
        if isinstance(current, ast.expr):
            syntax_count += 1
            if syntax_count > MAX_NODES * 4:
                _error(f"expression exceeds the bounded syntax budget")

    bindings = {}

    def convert(node, depth=1):
        if depth > MAX_DEPTH:
            _error(f"expression exceeds depth {MAX_DEPTH}")
        if isinstance(node, ast.Constant):
            if type(node.value) is not int or not 0 <= node.value <= MASK:
                _error("constants must fit unsigned 32-bit integers")
            return {"op": "const", "value": node.value}, "u32"
        if isinstance(node, ast.Name):
            if node.id in bindings:
                return bindings[node.id]
            if node.id not in ("x0", "x1", "x2", "x3"):
                _error(f"unknown input name: {node.id}")
            return {"op": "input", "index": int(node.id[1])}, "u32"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            child, kind = convert(node.operand, depth + 1)
            if kind != "u32":
                _error("unary signs require an integer operand")
            if isinstance(node.op, ast.UAdd):
                return child, kind
            if child["op"] == "const":
                return {"op": "const", "value": (-child["value"]) & MASK}, kind
            return {"op": "sub", "a": {"op": "const", "value": 0}, "b": child}, kind
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            a, ak = convert(node.left, depth + 1)
            b, bk = convert(node.right, depth + 1)
            if ak != "u32" or bk != "u32":
                _error("arithmetic and bit operations require integer operands")
            return {"op": _BINARY[type(node.op)], "a": a, "b": b}, "u32"
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                _error(
                    "only named allowed functions with positional operands are supported"
                )
            name = node.func.id
            if name in _CALLS:
                if len(node.args) != 2:
                    _error(f"{name} requires exactly two operands")
                a, ak = convert(node.args[0], depth + 1)
                b, bk = convert(node.args[1], depth + 1)
                if ak != "u32" or bk != "u32":
                    _error(f"{name} requires integer operands")
                op = _CALLS[name]
                return {
                    "op": op,
                    "a": a,
                    "b": b,
                }, "bool" if op in _COMPARISONS else "u32"
            if name == "ifelse":
                if len(node.args) != 3:
                    _error("ifelse requires exactly three operands")
                condition, ck = convert(node.args[0], depth + 1)
                yes, yk = convert(node.args[1], depth + 1)
                no, nk = convert(node.args[2], depth + 1)
                if yk != "u32" or nk != "u32":
                    _error("ifelse branches must be integers")
                if ck == "u32":
                    condition = {
                        "op": "ugt",
                        "a": condition,
                        "b": {"op": "const", "value": 0},
                    }
                return {
                    "op": "ite",
                    "condition": condition,
                    "then": yes,
                    "else": no,
                }, "u32"
            if name == "reverse":
                if len(node.args) != 2:
                    _error("reverse requires exactly two operands")
                arg, kind = convert(node.args[0], depth + 1)
                width = node.args[1]
                if (
                    kind != "u32"
                    or not isinstance(width, ast.Constant)
                    or type(width.value) is not int
                    or not 1 <= width.value <= 32
                ):
                    _error("reverse width must be a literal integer from 1 to 32")
                return {"op": "reverse", "arg": arg, "width": width.value}, "u32"
            _error(f"unknown function: {name}")
        _error(f"unsupported syntax: {type(node).__name__}")

    if not parsed.body or not isinstance(parsed.body[-1], ast.Expr):
        _error("expression program must end with a result expression")
    if len(parsed.body) - 1 > MAX_BINDINGS:
        _error(f"expression exceeds {MAX_BINDINGS} named bindings")
    for statement in parsed.body[:-1]:
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
        ):
            _error("only simple prior-only t0..t31 assignments may precede the result")
        name = statement.targets[0].id
        if not re.fullmatch(r"t(?:[0-9]|[12][0-9]|3[01])", name):
            _error("binding names must be t0..t31; inputs cannot be overwritten")
        if name in bindings:
            _error(f"binding {name} cannot be reassigned")
        value, kind = convert(statement.value)
        _check_ast(value)
        bindings[name] = (value, kind)
    result, _ = convert(parsed.body[-1].value)
    _check_ast(result)
    return result


def _children(node):
    op = node["op"]
    if op in _ARITHMETIC | _COMPARISONS:
        return (node["a"], node["b"])
    if op == "ite":
        return (node["condition"], node["then"], node["else"])
    if op == "reverse":
        return (node["arg"],)
    return ()


def _structural_key(node):
    op = node["op"]
    if op == "input":
        return (op, node["index"])
    if op == "const":
        return (op, node["value"])
    children = tuple(_structural_key(child) for child in _children(node))
    return (op, node["width"], *children) if op == "reverse" else (op, *children)


def format_expression(node: dict) -> str:
    """Return compact safe source with deterministic prior-only named bindings.

    Repeated nonleaf subtrees are structurally shared, independent of Python
    object identity. At most 32 useful bindings are emitted in dependency order.
    The expanded result still obeys the original AST node and depth budgets.
    """
    _check_ast(node)
    counts, records, sizes, order = {}, {}, {}, []

    def inspect(current):
        child_keys = [inspect(child) for child in _children(current)]
        op = current["op"]
        if op == "input":
            key = (op, current["index"])
        elif op == "const":
            key = (op, current["value"])
        else:
            key = (
                (op, current["width"], *child_keys)
                if op == "reverse"
                else (op, *child_keys)
            )
        counts[key] = counts.get(key, 0) + 1
        if key not in records:
            records[key] = current
            sizes[key] = 1 + sum(sizes[child] for child in child_keys)
            order.append(key)
        return key

    root_key = inspect(node)
    # Count references in the structural DAG, not the expanded tree. Once a
    # parent is shared, its children must not receive redundant bindings merely
    # because that parent's full subtree appeared many times in the input tree.
    counts = {root_key: 1}
    for current in records.values():
        for child in _children(current):
            key = _structural_key(child)
            counts[key] = counts.get(key, 0) + 1
    candidates = [
        key for key in order if counts.get(key, 0) > 1 and _children(records[key])
    ]
    # Preserve the highest estimated source savings if a pathological expression
    # offers more repeated nodes than the language's binding budget.
    position = {key: index for index, key in enumerate(order)}
    candidates.sort(
        key=lambda key: (-(counts[key] - 1) * (sizes[key] - 1), position[key])
    )
    selected = set(candidates[:MAX_BINDINGS])
    names, definitions = {}, []

    def render(current):
        key = _structural_key(current)
        if key in names:
            return names[key]
        op = current["op"]
        if op == "input":
            return f"x{current['index']}"
        if op == "const":
            value = current["value"]
            return str(value) if value <= 0xFFFF else f"0x{value:08x}"
        if op in _OPERATOR:
            return f"({render(current['a'])} {_OPERATOR[op]} {render(current['b'])})"
        if op == "ashr":
            return f"asr({render(current['a'])}, {render(current['b'])})"
        if op in _COMPARISONS:
            name = {"slt": "lt", "sgt": "gt"}.get(op, op)
            return f"{name}({render(current['a'])}, {render(current['b'])})"
        if op == "ite":
            return f"ifelse({render(current['condition'])}, {render(current['then'])}, {render(current['else'])})"
        if op == "reverse":
            return f"reverse({render(current['arg'])}, {current['width']})"
        raise AssertionError(op)

    for key in order:
        if key in selected:
            definition = render(records[key])
            name = f"t{len(names)}"
            definitions.append(f"{name} = {definition}")
            names[key] = name
    result = "\n".join([*definitions, render(node)])
    if len(result.encode("utf-8")) > MAX_SOURCE_BYTES:
        _error("formatted expression exceeds the source budget")
    return result


def emit_c(
    node: dict, function_name: str = "recovered", argument_count: int = 3
) -> str:
    """Emit standalone defined C99 uint32_t code, without arbitrary code insertion.

    Each distinct nonleaf node gets one temporary to bound source expansion. No division,
    signed overflow, implementation-defined unsigned-to-signed cast, or shift
    outside 0..31 is emitted. Comparison temporaries use bool; results use u32.
    """
    _check_ast(node)
    if (
        not isinstance(function_name, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", function_name)
        or function_name in _C_RESERVED
    ):
        _error("function name must be a safe nonreserved C identifier")
    if type(argument_count) is not int or not 0 <= argument_count <= 4:
        _error("argument count must be an integer from 0 to 4")
    lines = ["#include <stdint.h>", "#include <stdbool.h>", ""]
    body = []
    count = 0
    generated = {}

    def generate(current):
        nonlocal count
        key = _structural_key(current)
        if key in generated:
            return generated[key]
        op = current["op"]
        if op == "input":
            if current["index"] >= argument_count:
                _error(
                    "expression references an input absent from the function signature"
                )
            return f"x{current['index']}"
        if op == "const":
            return f"UINT32_C(0x{current['value']:08x})"
        if op == "ite":
            condition = generate(current["condition"])
            yes, no = generate(current["then"]), generate(current["else"])
            expression = f"{condition} ? {yes} : {no}"
        elif op == "reverse":
            value = generate(current["arg"])
            name = f"nr_{count}"
            count += 1
            loop = f"nr_i{count}"
            body.append(f"    uint32_t {name} = UINT32_C(0);")
            body.append(
                f"    for (uint32_t {loop} = 0; {loop} < UINT32_C({current['width']}); ++{loop}) {{"
            )
            body.append(
                f"        {name} = (uint32_t)(({name} << 1) | (({value} >> {loop}) & UINT32_C(1)));"
            )
            body.append("    }")
            generated[key] = name
            return name
        else:
            a, b = generate(current["a"]), generate(current["b"])
            if op in ("add", "sub", "and", "or", "xor"):
                expression = f"{a} {_OPERATOR[op]} {b}"
            elif op == "mul":
                expression = f"(uint64_t){a} * (uint64_t){b}"
            elif op in ("lshr", "shl"):
                expression = f"{a} {_OPERATOR[op]} ({b} & UINT32_C(31))"
            elif op == "ashr":
                shift = f"({b} & UINT32_C(31))"
                expression = f"({a} >> {shift}) | ((UINT32_C(0) - ({a} >> 31)) & ~(UINT32_MAX >> {shift}))"
            elif op in ("slt", "sgt"):
                symbol = "<" if op == "slt" else ">"
                expression = f"({a} ^ UINT32_C(0x80000000)) {symbol} ({b} ^ UINT32_C(0x80000000))"
            elif op in ("ult", "ugt", "eq"):
                expression = f"{a} { {'ult': '<', 'ugt': '>', 'eq': '=='}[op] } {b}"
            else:
                raise AssertionError(op)
        name = f"nr_{count}"
        count += 1
        ctype = "bool" if op in _COMPARISONS else "uint32_t"
        cast = "" if ctype == "bool" else "(uint32_t)"
        body.append(f"    {ctype} {name} = {cast}({expression});")
        generated[key] = name
        return name

    output = generate(node)
    signature = ", ".join(f"uint32_t x{i}" for i in range(argument_count)) or "void"
    lines.append(f"uint32_t {function_name}({signature}) {{")
    lines.extend(body)
    lines.append(f"    return (uint32_t)({output});")
    lines.append("}")
    return "\n".join(lines) + "\n"
