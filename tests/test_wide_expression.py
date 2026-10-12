"""64-bit word boundaries and native C results against numerical fixtures.

The numerical oracles are direct mathematical functions, not an AST interpreter
or the recovery core, so they test generated native arithmetic independently.
"""

import itertools
import json
import pathlib
import random
import shutil
import subprocess
import tempfile
import unittest

from native_recovery.expression import (
    MAX_DEPTH,
    ExpressionError,
    emit_c,
    format_expression,
    parse_expression,
    validate_ast,
)

MOD = 1 << 64
MASK = MOD - 1
SIGN = 1 << 63


def signed(value):
    return (value + SIGN) % MOD - SIGN


def splitmix64(value):
    z = (value + 0x9E3779B97F4A7C15) % MOD
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) % MOD
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) % MOD
    return z ^ (z >> 31)


def shared_mix(a, b, c, d):
    summed = (a + d) % MOD
    multiplied = (summed * b) % MOD
    return multiplied ^ (multiplied >> (c % 64))


class WideExpressionTests(unittest.TestCase):
    def test_selected_width_bounds_constants_negation_and_reverse(self):
        node = parse_expression("0xffffffffffffffff", word_bits=64)
        self.assertEqual(node, {"op": "const", "value": MASK})
        self.assertEqual(validate_ast(node, word_bits=64), "u64")
        self.assertEqual(parse_expression("-1", word_bits=64), node)
        self.assertEqual(
            parse_expression(f"-{MASK}", word_bits=64), {"op": "const", "value": 1}
        )
        self.assertEqual(parse_expression("-1"), {"op": "const", "value": 0xFFFFFFFF})
        self.assertEqual(validate_ast(parse_expression("x0")), "u32")
        self.assertEqual(
            validate_ast(parse_expression("lt(x0, x1)", word_bits=64), word_bits=64),
            "bool",
        )
        for text in [str(MOD), f"-{MOD}", "0x10000000000000000", "reverse(x0, 65)"]:
            with self.subTest(text=text), self.assertRaises(ExpressionError):
                parse_expression(text, word_bits=64)
        for text in ["0xffffffffffffffff", "reverse(x0, 64)"]:
            with self.subTest(text=text), self.assertRaises(ExpressionError):
                parse_expression(text)
        with self.assertRaises(ExpressionError):
            validate_ast(node)
        with self.assertRaises(ExpressionError):
            format_expression(node)
        with self.assertRaises(ExpressionError):
            emit_c(node)

    def test_word_bits_requires_exact_supported_integer_on_all_apis(self):
        node = {"op": "input", "index": 0}
        for value in [True, False, 0, 1, 31, 33, 63, 65, "64", 64.0, None, [], {}]:
            for api in [
                lambda value=value: validate_ast(node, word_bits=value),
                lambda value=value: parse_expression("x0", word_bits=value),
                lambda value=value: format_expression(node, word_bits=value),
                lambda value=value: emit_c(node, word_bits=value),
            ]:
                with (
                    self.subTest(value=repr(value)),
                    self.assertRaises(ExpressionError),
                ):
                    api()

    def test_wide_bindings_roundtrip_and_structural_sharing(self):
        text = "t0 = x0 + x3\nt1 = t0 * 0x9e3779b97f4a7c15\nifelse(lt(x2, 0), reverse(t1, 64), t1 >> x1)"
        node = json.loads(json.dumps(parse_expression(text, word_bits=64)))
        compact = format_expression(node, word_bits=64)
        self.assertEqual(parse_expression(compact, word_bits=64), node)
        self.assertEqual(
            compact, format_expression(json.loads(json.dumps(node)), word_bits=64)
        )
        c_source = emit_c(node, argument_count=4, word_bits=64)
        self.assertIn(
            "uint64_t recovered(uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3)",
            c_source,
        )
        self.assertEqual(c_source.count("x0 + x3"), 1)
        self.assertEqual(c_source.count("UINT64_C(0x9e3779b97f4a7c15)"), 1)
        self.assertIn("UINT64_C(63)", c_source)
        self.assertIn("UINT64_C(0x8000000000000000)", c_source)
        self.assertLess(len(compact), 250)

    def test_wide_limits_and_untrusted_ast_retain_strict_shape(self):
        invalid = [
            {"op": "const", "value": True},
            {"op": "const", "value": MOD},
            {"op": "const", "value": -1},
            {"op": "input", "index": True},
            {"op": "reverse", "arg": {"op": "input", "index": 0}, "width": True},
            {"op": "reverse", "arg": {"op": "input", "index": 0}, "width": 65},
            {"op": "const", "value": 1, "word_bits": 64},
            {"op": []},
        ]
        for node in invalid:
            with self.subTest(node=node), self.assertRaises(ExpressionError):
                validate_ast(node, word_bits=64)
        source = (
            "t0 = x0 + 1\n"
            + "\n".join(f"t{i} = t{i - 1} + t{i - 1}" for i in range(1, 8))
            + "\nt7"
        )
        with self.assertRaisesRegex(ExpressionError, "nodes"):
            parse_expression(source, word_bits=64)
        source = "x0"
        for _ in range(MAX_DEPTH):
            source = f"reverse({source}, 64)"
        with self.assertRaisesRegex(ExpressionError, "depth"):
            parse_expression(source, word_bits=64)
        for source in ["t0 = open('secret')\nt0", "x0 = 1\nx0", "t0 = 1\nt0 = 2\nt0"]:
            with self.subTest(source=source), self.assertRaises(ExpressionError):
                parse_expression(source, word_bits=64)
        for name in ["uint64_t", "UINT64_C", "UINT64_MAX"]:
            with self.subTest(name=name), self.assertRaises(ExpressionError):
                emit_c(parse_expression("x0", word_bits=64), name, word_bits=64)

    def test_native_u64_c_matches_direct_numerical_oracles_with_ubsan(self):
        clang = shutil.which("clang")
        if not clang:
            self.skipTest("clang unavailable")
        fixtures = [
            ("x0 + x1", lambda a, b, c, d: (a + b) % MOD),
            ("x0 - x1", lambda a, b, c, d: (a - b) % MOD),
            ("x0 * x1", lambda a, b, c, d: (a * b) % MOD),
            ("x0 & x1", lambda a, b, c, d: a & b),
            ("x0 | x1", lambda a, b, c, d: a | b),
            ("x0 ^ x1", lambda a, b, c, d: a ^ b),
            ("x0 >> x1", lambda a, b, c, d: a >> (b % 64)),
            ("x0 << x1", lambda a, b, c, d: (a << (b % 64)) % MOD),
            ("asr(x0, x1)", lambda a, b, c, d: (signed(a) >> (b % 64)) % MOD),
            (
                "ifelse(lt(x0, x1), x2, x3)",
                lambda a, b, c, d: c if signed(a) < signed(b) else d,
            ),
            (
                "ifelse(gt(x0, x1), x2, x3)",
                lambda a, b, c, d: c if signed(a) > signed(b) else d,
            ),
            ("ifelse(ult(x0, x1), x2, x3)", lambda a, b, c, d: c if a < b else d),
            ("ifelse(ugt(x0, x1), x2, x3)", lambda a, b, c, d: c if a > b else d),
            ("ifelse(eq(x0, x1), x2, x3)", lambda a, b, c, d: c if a == b else d),
            ("reverse(x0, 64)", lambda a, b, c, d: int(format(a, "064b")[::-1], 2)),
            ("reverse(x3, 1)", lambda a, b, c, d: d % 2),
            ("ifelse(x0, x2, x3)", lambda a, b, c, d: c if a != 0 else d),
            ("t0 = x0+x3\nt1 = t0*x1\nt1^(t1 >> x2)", shared_mix),
            (
                "t0 = x0+0x9e3779b97f4a7c15\nt1 = (t0^(t0 >> 30))*0xbf58476d1ce4e5b9\nt2 = (t1^(t1 >> 27))*0x94d049bb133111eb\nt2^(t2 >> 31)",
                lambda a, b, c, d: splitmix64(a),
            ),
        ]
        # The known zero-seed mixer output anchors the numerical oracle itself.
        self.assertEqual(splitmix64(0), 0xE220A8397B1DCDAF)
        edges = [
            0,
            1,
            31,
            32,
            62,
            63,
            64,
            65,
            127,
            128,
            1 << 32,
            (1 << 53) - 1,
            1 << 53,
            (1 << 53) + 1,
            SIGN - 1,
            SIGN,
            SIGN + 1,
            MASK,
        ]
        cases = [
            (a, b, 0xFEDCBA9876543210, MASK ^ a)
            for a, b in itertools.product(edges, repeat=2)
        ]
        rng = random.Random(640047)
        cases.extend(tuple(rng.getrandbits(64) for _ in range(4)) for _ in range(128))
        source = "\n".join(
            emit_c(
                parse_expression(text, word_bits=64),
                f"wide_{i}",
                argument_count=4,
                word_bits=64,
            )
            for i, (text, _) in enumerate(fixtures)
        )
        source += "\n#include <stdio.h>\n#include <inttypes.h>\nint main(void) {\n"
        for fixture_id, (_, expected) in enumerate(fixtures):
            for args in cases:
                literals = ", ".join(f"UINT64_C(0x{value:016x})" for value in args)
                source += f'printf("%" PRIu64 "\\n", wide_{fixture_id}({literals}));\n'
        source += "return 0;\n}\n"
        with tempfile.TemporaryDirectory(prefix="rewynth-u64-expression-") as folder:
            c_path = pathlib.Path(folder) / "wide.c"
            exe = pathlib.Path(folder) / "wide"
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
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(
                [str(exe)], text=True, capture_output=True, timeout=10, check=False
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)
        actual = [int(line) for line in executed.stdout.splitlines()]
        expected = [oracle(*args) for _, oracle in fixtures for args in cases]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 8588)


if __name__ == "__main__":
    unittest.main()
