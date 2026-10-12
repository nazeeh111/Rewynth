"""Independent expression bounds and compiled-C semantics tests."""

import itertools
import json
import pathlib
import random
import shutil
import subprocess
import tempfile
import unittest

from native_recovery.expression import (
    ExpressionError,
    MAX_DEPTH,
    MAX_NODES,
    emit_c,
    format_expression,
    parse_expression,
)

MASK = 0xFFFFFFFF


def oracle(node, args):
    op = node["op"]
    if op == "const":
        return node["value"]
    if op == "input":
        return args[node["index"]] & MASK
    if op == "ite":
        return oracle(
            node["then"] if oracle(node["condition"], args) else node["else"], args
        )
    if op == "reverse":
        value = oracle(node["arg"], args)
        width = node["width"]
        return int(format(value & ((1 << width) - 1), f"0{width}b")[::-1], 2)
    a, b = oracle(node["a"], args), oracle(node["b"], args)
    signed = lambda x: x if x < 0x80000000 else x - 0x100000000
    if op == "add":
        result = a + b
    elif op == "sub":
        result = a - b
    elif op == "mul":
        result = a * b
    elif op == "and":
        result = a & b
    elif op == "or":
        result = a | b
    elif op == "xor":
        result = a ^ b
    elif op == "lshr":
        result = a >> (b & 31)
    elif op == "shl":
        result = a << (b & 31)
    elif op == "ashr":
        result = signed(a) >> (b & 31)
    elif op == "slt":
        return signed(a) < signed(b)
    elif op == "sgt":
        return signed(a) > signed(b)
    elif op == "ult":
        return a < b
    elif op == "ugt":
        return a > b
    elif op == "eq":
        return a == b
    else:
        raise AssertionError(op)
    return result & MASK


class ExpressionTests(unittest.TestCase):
    def test_exact_core_shape_and_precedence(self):
        self.assertEqual(
            parse_expression("x0 + x1 * 7"),
            {
                "op": "add",
                "a": {"op": "input", "index": 0},
                "b": {
                    "op": "mul",
                    "a": {"op": "input", "index": 1},
                    "b": {"op": "const", "value": 7},
                },
            },
        )
        self.assertEqual(parse_expression("x2 >> 32")["op"], "lshr")
        self.assertEqual(parse_expression("asr(x0, x1)")["op"], "ashr")

    def test_negative_constants_and_unary_wrap(self):
        self.assertEqual(parse_expression("-1"), {"op": "const", "value": MASK})
        self.assertEqual(parse_expression("-4294967295"), {"op": "const", "value": 1})
        self.assertEqual(
            parse_expression("-x0"),
            {
                "op": "sub",
                "a": {"op": "const", "value": 0},
                "b": {"op": "input", "index": 0},
            },
        )
        self.assertEqual(oracle(parse_expression("-x0"), [1, 0, 0]), MASK)
        for text in [
            "4294967296",
            "-4294967296",
            "0x100000000",
            "1.0",
            "True",
            "False",
            "None",
        ]:
            with self.subTest(text=text), self.assertRaises(ExpressionError):
                parse_expression(text)

    def test_round_trip_all_supported_operations(self):
        expressions = [
            "x0",
            "0xffffffff",
            "(x0 + x1) * (x2 - 4)",
            "x0 & x1 | x2 ^ 0x80000000",
            "x0 >> x1",
            "x0 << x1",
            "asr(x0,x1)",
            "lt(x0,x1)",
            "gt(x0,x1)",
            "ult(x0,x1)",
            "ugt(x0,x1)",
            "eq(x0,x1)",
            "ifelse(lt(x0,0), -x0, x0)",
            "ifelse(x0, x1, x2)",
            "reverse(x0,16)",
            "reverse(x2,32)",
        ]
        for text in expressions:
            with self.subTest(text=text):
                tree = parse_expression(text)
                self.assertEqual(parse_expression(format_expression(tree)), tree)

    def test_integer_condition_is_explicitly_normalized_to_nonzero(self):
        node = parse_expression("ifelse(x0,1,2)")
        self.assertEqual(
            node["condition"],
            {
                "op": "ugt",
                "a": {"op": "input", "index": 0},
                "b": {"op": "const", "value": 0},
            },
        )
        self.assertEqual(oracle(node, [0, 0, 0]), 2)
        self.assertEqual(oracle(node, [MASK, 0, 0]), 1)

    def test_unknown_and_executable_python_syntax_rejected(self):
        cases = [
            '__import__("os").system("touch should-not-exist")',
            'open("secret")',
            "x0.real",
            "x0[0]",
            "(lambda: 1)()",
            "[x0 for x0 in [1]]",
            'eval("x0")',
            "(x0 := 1)",
            "x0 ** 2",
            "x0 / 2",
            "x0 // 2",
            "x0 % 2",
            "x0 or x1",
            "asr(x0, shift=1)",
            "ifelse(*x0)",
            "os.system(x0)",
            "x4",
            "x00",
            "x0; x1",
            '{"op":"input"}',
            '"x0"',
            "[x0]",
            "reverse(x0,x1)",
            "reverse(x0,0)",
            "reverse(x0,33)",
            "unknown(x0)",
            "asr(x0)",
            "lt(lt(x0,x1),x2)",
            "lt(x0,x1) + 1",
            "ifelse(eq(x0,0),lt(x1,0),0)",
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ExpressionError):
                parse_expression(text)

    def test_text_depth_and_node_budgets(self):
        for text in [" ", "x0" + " " * 65536, "0x" + "f" * 16384, "\ud800"]:
            with self.subTest(text=repr(text[:30])), self.assertRaises(ExpressionError):
                parse_expression(text)
        text = "x0"
        for _ in range(MAX_DEPTH):
            text = f"({text} + 1)"
        with self.assertRaisesRegex(ExpressionError, "depth"):
            parse_expression(text)

        def balanced(depth):
            return (
                "x0"
                if depth == 0
                else f"({balanced(depth - 1)} + {balanced(depth - 1)})"
            )

        with self.assertRaisesRegex(ExpressionError, "nodes"):
            parse_expression(balanced(8))
        # A dense but in-budget intrinsic tree formats and reparses faithfully.
        tree = {"op": "input", "index": 0}
        for _ in range(20):
            tree = {"op": "reverse", "arg": tree, "width": 16}
        self.assertEqual(parse_expression(format_expression(tree)), tree)

    def test_untrusted_json_shape_types_and_codegen_identifiers(self):
        bad = [
            {"op": "input", "index": True},
            {"op": "input", "index": 4},
            {"op": "const", "value": -1},
            {"op": "const", "value": True},
            {"op": "input", "index": 0, "code": "system"},
            {"op": "evil"},
            {"op": []},
            {"op": {}},
            {"op": None},
            {"op": "reverse", "arg": {"op": "input", "index": 0}, "width": 99},
            {
                "op": "ite",
                "condition": {"op": "input", "index": 0},
                "then": {"op": "const", "value": 0},
                "else": {"op": "const", "value": 1},
            },
        ]
        cycle = {"op": "reverse", "width": 1}
        cycle["arg"] = cycle
        bad.append(cycle)
        for tree in bad:
            with (
                self.subTest(tree=repr(tree)[:100]),
                self.assertRaises(ExpressionError),
            ):
                format_expression(tree)
        tree = parse_expression("x0+1")
        for name in [
            "bad-name",
            'main(){system("x");}',
            "if",
            "_reserved",
            "x" * 65,
            "",
            "uint32_t",
            "UINT32_C",
            "bool",
            "uint_fast32_t",
            "INTMAX_C",
            "true",
        ]:
            with self.subTest(name=name), self.assertRaises(ExpressionError):
                emit_c(tree, name)
        with self.assertRaises(ExpressionError):
            emit_c(parse_expression("x2"), argument_count=2)
        with self.assertRaises(ExpressionError):
            emit_c(tree, argument_count=True)
        self.assertIn("(void)", emit_c(parse_expression("1"), argument_count=0))

    def test_prior_only_bindings_and_four_input_roundtrip(self):
        source = "t0 = x0 + x3\nt7 = lt(t0, x1)\nt31 = ifelse(t7, t0, x2)\nt31 ^ t0"
        node = parse_expression(source)
        self.assertEqual(parse_expression(format_expression(node)), node)
        self.assertEqual(oracle(node, [3, 10, 7, 2]), 0)
        self.assertIn("uint32_t x3", emit_c(node, argument_count=4))
        self.assertEqual(parse_expression("t0 = 1; t0"), {"op": "const", "value": 1})
        # Exactly 32 definitions, including harmless prior-only aliases, is valid.
        aliases = (
            "t0 = x3\n" + "\n".join(f"t{i} = t{i - 1}" for i in range(1, 32)) + "\nt31"
        )
        self.assertEqual(parse_expression(aliases), {"op": "input", "index": 3})

    def test_binding_reassignment_and_malicious_statements_rejected(self):
        invalid = [
            "x0 = 1\nx0",
            "x3 = 1\nx3",
            "other = 1\nother",
            "t32 = 1\nt32",
            "t01 = 1\nt01",
            "t0 = t0 + 1\nt0",
            "t0 = t1\nt1 = 1\nt0",
            "t0 = 1\nt0 = 2\nt0",
            "t0 += 1\nt0",
            "t0: int = 1\nt0",
            "t0 = t1 = 1\nt0",
            "t0, t1 = 1, 2\nt0",
            "t0 = 1",
            "t0.attr = 1\nx0",
            "t0[0] = 1\nx0",
            "del x0\nx0",
            "import os\nx0",
            "for t0 in range(1): pass\nx0",
            "return x0",
            "t0 = open('secret')\nt0",
            "t0 = __import__('os')\nx0",
            "t0 = (x0 := 2)\nt0",
            "t0 = 1\nprint(t0)\nt0",
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ExpressionError):
                parse_expression(text)
        too_many = "\n".join(f"t{i % 32} = 1" for i in range(33)) + "\nx0"
        with self.assertRaisesRegex(ExpressionError, "bindings"):
            parse_expression(too_many)

    def test_binding_expansion_retains_node_and_depth_limits(self):
        text = (
            "t0 = x0 + 1\n"
            + "\n".join(f"t{i} = t{i - 1} + t{i - 1}" for i in range(1, 8))
            + "\nt7"
        )
        with self.assertRaisesRegex(ExpressionError, "nodes"):
            parse_expression(text)
        text = (
            "t0 = x0 + 1\n"
            + "\n".join(f"t{i} = t{i - 1} + 1" for i in range(1, 24))
            + "\nt23"
        )
        with self.assertRaisesRegex(ExpressionError, "depth"):
            parse_expression(text)

    def test_structural_sharing_compacts_formatter_and_c(self):
        # Parse creates shared references; JSON round-trip deliberately destroys
        # Python object identity so compaction must use structural equality.
        source = "t0 = x0 + x3\nt1 = ((t0 << 17) | (t0 >> 15)) * 0x27d4eb2f\nt2 = t1 ^ (t1 >> 15)\nt3 = t2 * 0x85ebca77\nt4 = t3 ^ (t3 >> 13)\nt5 = t4 * 0xc2b2ae3d\nt5 ^ (t5 >> 16)"
        node = json.loads(json.dumps(parse_expression(source)))
        compact = format_expression(node)
        self.assertEqual(parse_expression(compact), node)
        self.assertEqual(len(compact.splitlines()), 5)
        self.assertEqual(compact, format_expression(json.loads(json.dumps(node))))
        c_source = emit_c(node, argument_count=4)
        self.assertEqual(c_source.count("uint32_t nr_"), 13)
        self.assertEqual(c_source.count("x0 + x3"), 1)
        self.assertLess(len(compact), 250)

    def test_maximum_binding_formatter_roundtrip(self):
        pairs = []
        for i in range(32):
            value = {
                "op": "add",
                "a": {"op": "input", "index": 0},
                "b": {"op": "const", "value": i},
            }
            pairs.append({"op": "add", "a": value, "b": json.loads(json.dumps(value))})
        while len(pairs) > 1:
            pairs = [
                {"op": "add", "a": pairs[i], "b": pairs[i + 1]}
                for i in range(0, len(pairs), 2)
            ]
        compact = format_expression(pairs[0])
        self.assertEqual(len(compact.splitlines()), 33)
        self.assertEqual(parse_expression(compact), pairs[0])

    def test_compiled_c_matches_independent_oracle_without_undefined_behavior(self):
        clang = shutil.which("clang")
        if not clang:
            self.skipTest("clang unavailable")
        expressions = [
            "x0+x1",
            "x0-x1",
            "x0*x1",
            "x0&x1",
            "x0|x1",
            "x0^x1",
            "x0 >> x1",
            "x0 << x1",
            "asr(x0,x1)",
            "ifelse(lt(x0,x1),x0,x1)",
            "ifelse(gt(x0,x1),x0,x1)",
            "ifelse(ult(x0,x1),x0,x1)",
            "ifelse(ugt(x0,x1),x0,x1)",
            "ifelse(eq(x0,x1),x2,-1)",
            "reverse(x0,1)",
            "reverse(x0,16)",
            "reverse(x0,32)",
            "asr(reverse(x0,32), x1+32) ^ (x2 * -1)",
            "ifelse(x0, (x1<<x2)+x0, asr(x2, x1))",
            "t0 = x0 + x3\nt1 = asr(t0, x1)\nt1 ^ t0",
            "t0 = lt(x0,x3)\nt1 = ifelse(t0,x0,x3)\nifelse(t0,t1+5,t1-5)",
            "t0 = reverse(x3,32)\n(t0 >> x1) | (t0 << (32-x1))",
            "t0 = x0+x3\nt1 = ((t0 << 17)|(t0 >> 15))*0x27d4eb2f\nt2 = t1^(t1 >> 15)\nt3 = t2*0x85ebca77\nt4 = t3^(t3 >> 13)\nt5 = t4*0xc2b2ae3d\nt5^(t5 >> 16)",
        ]
        edge = [0, 1, 31, 32, 33, 63, 255, 0x7FFFFFFF, 0x80000000, MASK]
        cases = [
            (a, b, 0x55555555, MASK ^ a) for a, b in itertools.product(edge, repeat=2)
        ]
        rng = random.Random(221)
        cases += [tuple(rng.randrange(1 << 32) for _ in range(4)) for _ in range(100)]
        trees = [parse_expression(text) for text in expressions]
        source = "\n".join(
            emit_c(tree, f"recovered_{i}", argument_count=4)
            for i, tree in enumerate(trees)
        )
        source += "\n#include <stdio.h>\n#include <inttypes.h>\nint main(void) {\n"
        for tree_id, tree in enumerate(trees):
            for args in cases:
                literals = ", ".join(f"UINT32_C(0x{value:08x})" for value in args)
                source += (
                    f'printf("%" PRIu32 "\\n", recovered_{tree_id}({literals}));\n'
                )
        source += "return 0;\n}\n"
        with tempfile.TemporaryDirectory(prefix="native-expression-") as directory:
            c_path = pathlib.Path(directory) / "check.c"
            exe = pathlib.Path(directory) / "check"
            c_path.write_text(source)
            compiled = subprocess.run(
                [
                    clang,
                    "-std=c99",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wno-unused-parameter",
                    "-fsanitize=undefined",
                    "-fno-sanitize-recover=all",
                    str(c_path),
                    "-o",
                    str(exe),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
        actual = [int(line) for line in run.stdout.splitlines()]
        expected = [int(oracle(tree, args)) for tree in trees for args in cases]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 4600)


if __name__ == "__main__":
    unittest.main()
