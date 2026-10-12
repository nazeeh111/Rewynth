"""Run the shipped browser word evaluator in Node against numerical oracles.

JSON packets retain uint64 constants and inputs as exact strings. Node executes
actual bitvector.js bytes as an ES module; no browser UI or native target runs.
"""

import itertools
import json
import pathlib
import random
import shutil
import subprocess
import unittest

from native_recovery.expression import parse_expression

MOD64 = 1 << 64
MASK64 = MOD64 - 1
SIGN64 = 1 << 63


def signed64(value):
    return (value + SIGN64) % MOD64 - SIGN64


def splitmix64(value):
    z = (value + 0x9E3779B97F4A7C15) % MOD64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) % MOD64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) % MOD64
    return z ^ (z >> 31)


def wire_ast(node):
    """Serialize integer constants exactly as a wide JSON response would."""
    result = {
        key: wire_ast(value) if isinstance(value, dict) else value
        for key, value in node.items()
    }
    if result["op"] == "const":
        result["value"] = hex(result["value"])
    return result


class WideBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        discovered = shutil.which("node")
        if not discovered:
            raise unittest.SkipTest(
                "Node CLI unavailable; browser arithmetic checks require Node"
            )
        cls.node = str(pathlib.Path(discovered).resolve())
        module = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src/native_recovery/resources/web/bitvector.js"
        )
        # Data URL loading avoids Node-version differences in the default type
        # assigned to .js files, while executing the shipped source unchanged.
        cls.harness = f"""
import {{ readFileSync }} from 'node:fs';
const source = readFileSync(new URL({json.dumps(module.as_uri())}), 'utf8');
const {{evaluate}} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
let text = '';
for await (const chunk of process.stdin) text += chunk;
const results = JSON.parse(text).map(item => {{
  try {{
    const value = Object.hasOwn(item, 'word_bits')
      ? evaluate(item.ast, item.inputs, item.word_bits)
      : evaluate(item.ast, item.inputs);
    return {{ok: true, type: typeof value, value: String(value)}};
  }} catch (error) {{
    return {{ok: false, error: String(error.message)}};
  }}
}});
process.stdout.write(JSON.stringify(results));
"""

    def run_packets(self, packets):
        executed = subprocess.run(
            [self.node, "--input-type=module", "--eval", self.harness],
            input=json.dumps(packets),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(executed.returncode, 0, executed.stderr)
        results = json.loads(executed.stdout)
        self.assertEqual(len(results), len(packets))
        return results

    def test_json_hex_decimal_strings_preserve_bits_beyond_number_precision(self):
        values = [(1 << 53) + 1, SIGN64 - 1, SIGN64, MASK64, 0xFEDCBA9876543210]
        requests = []
        expected = []
        for value in values:
            for encoded in [str(value), hex(value), "0X" + format(value, "X")]:
                requests.append(
                    {
                        "ast": {"op": "const", "value": encoded},
                        "inputs": ["0"],
                        "word_bits": 64,
                    }
                )
                requests.append(
                    {
                        "ast": {"op": "input", "index": 0},
                        "inputs": [encoded],
                        "word_bits": 64,
                    }
                )
                expected.extend([value, value])
        results = self.run_packets(requests)
        for result, value in zip(results, expected, strict=True):
            self.assertEqual(
                result, {"ok": True, "type": "bigint", "value": str(value)}
            )

    def test_64_bit_actual_js_matches_independent_mathematical_fixtures(self):
        fixtures = [
            ("x0+x1", lambda a, b, c, d: (a + b) % MOD64),
            ("x0-x1", lambda a, b, c, d: (a - b) % MOD64),
            ("x0*x1", lambda a, b, c, d: (a * b) % MOD64),
            ("x0&x1", lambda a, b, c, d: a & b),
            ("x0|x1", lambda a, b, c, d: a | b),
            ("x0^x1", lambda a, b, c, d: a ^ b),
            ("x0 >> x1", lambda a, b, c, d: a >> (b % 64)),
            ("x0 << x1", lambda a, b, c, d: (a << (b % 64)) % MOD64),
            ("asr(x0,x1)", lambda a, b, c, d: (signed64(a) >> (b % 64)) % MOD64),
            (
                "ifelse(lt(x0,x1),x2,x3)",
                lambda a, b, c, d: c if signed64(a) < signed64(b) else d,
            ),
            (
                "ifelse(gt(x0,x1),x2,x3)",
                lambda a, b, c, d: c if signed64(a) > signed64(b) else d,
            ),
            ("ifelse(ult(x0,x1),x2,x3)", lambda a, b, c, d: c if a < b else d),
            ("ifelse(ugt(x0,x1),x2,x3)", lambda a, b, c, d: c if a > b else d),
            ("ifelse(eq(x0,x1),x2,x3)", lambda a, b, c, d: c if a == b else d),
            ("reverse(x0,64)", lambda a, b, c, d: int(format(a, "064b")[::-1], 2)),
            ("reverse(x3,1)", lambda a, b, c, d: d % 2),
            (
                "ifelse(x0, reverse(x3,64), asr(x2,x1))",
                lambda a, b, c, d: (
                    int(format(d, "064b")[::-1], 2)
                    if a
                    else (signed64(c) >> (b % 64)) % MOD64
                ),
            ),
            (
                "t0=x0+x3\nt1=t0*x1\nt1^(t1 >> x2)",
                lambda a, b, c, d: (
                    (((a + d) % MOD64 * b) % MOD64)
                    ^ ((((a + d) % MOD64 * b) % MOD64) >> (c % 64))
                ),
            ),
            (
                "t0=x0+0x9e3779b97f4a7c15\nt1=(t0^(t0 >> 30))*0xbf58476d1ce4e5b9\nt2=(t1^(t1 >> 27))*0x94d049bb133111eb\nt2^(t2 >> 31)",
                lambda a, b, c, d: splitmix64(a),
            ),
        ]
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
            (1 << 53) + 1,
            SIGN64 - 1,
            SIGN64,
            SIGN64 + 1,
            MASK64,
        ]
        cases = [
            (a, b, 0xFEDCBA9876543210, MASK64 ^ a)
            for a, b in itertools.product(edges, repeat=2)
        ]
        rng = random.Random(0xB16B17)
        cases.extend(tuple(rng.getrandbits(64) for _ in range(4)) for _ in range(96))
        requests, expected = [], []
        for source, oracle in fixtures:
            ast = wire_ast(parse_expression(source, word_bits=64))
            for args in cases:
                # Mix decimal and hexadecimal encodings within each request.
                inputs = [
                    str(value) if index % 2 else hex(value)
                    for index, value in enumerate(args)
                ]
                requests.append({"ast": ast, "inputs": inputs, "word_bits": 64})
                expected.append(oracle(*args))
        actual = self.run_packets(requests)
        self.assertEqual(len(actual), 5548)
        for index, (result, value) in enumerate(zip(actual, expected, strict=True)):
            self.assertEqual(
                result,
                {"ok": True, "type": "bigint", "value": str(value)},
                f"numerical case {index}",
            )

    def test_32_bit_default_and_explicit_number_compatibility(self):
        mod = 1 << 32
        mask = mod - 1
        signed = lambda value: (value + (1 << 31)) % mod - (1 << 31)
        fixtures = [
            ("x0+x1", lambda a, b: (a + b) % mod),
            ("x0*x1", lambda a, b: (a * b) % mod),
            ("x0 >> x1", lambda a, b: a >> (b % 32)),
            ("asr(x0,x1)", lambda a, b: (signed(a) >> (b % 32)) % mod),
            ("reverse(x0,32)", lambda a, b: int(format(a, "032b")[::-1], 2)),
            ("ifelse(lt(x0,x1),x0,x1)", lambda a, b: a if signed(a) < signed(b) else b),
        ]
        requests, expected = [], []
        for source, oracle in fixtures:
            ast = wire_ast(parse_expression(source))
            for a, b in itertools.product(
                [0, 1, 31, 32, 63, 64, 0x7FFFFFFF, 0x80000000, mask], repeat=2
            ):
                for explicit in (False, True):
                    request = {"ast": ast, "inputs": [a, hex(b)]}
                    if explicit:
                        request["word_bits"] = 32
                    requests.append(request)
                    expected.append(oracle(a, b))
        results = self.run_packets(requests)
        self.assertEqual(len(results), 972)
        for result, value in zip(results, expected, strict=True):
            self.assertEqual(
                result, {"ok": True, "type": "number", "value": str(value)}
            )

    def test_unsafe_floats_booleans_range_and_word_size_rejected(self):
        invalid_values = [
            True,
            False,
            1.5,
            1 << 53,
            (1 << 53) + 1,
            MASK64,
            None,
            "1.5",
            "1e20",
            " ",
            "-1",
            "0x10000000000000000",
            "0" * 81,
        ]
        requests = []
        for value in invalid_values:
            requests.append(
                {
                    "ast": {"op": "const", "value": value},
                    "inputs": ["0"],
                    "word_bits": 64,
                }
            )
            requests.append(
                {"ast": {"op": "input", "index": 0}, "inputs": [value], "word_bits": 64}
            )
            # All inputs must be validated, even if this program never reads one.
            requests.append(
                {
                    "ast": {"op": "const", "value": "1"},
                    "inputs": [value],
                    "word_bits": 64,
                }
            )
        for width in [True, False, 0, 31, 33, 63, 65, 32.5, 64.5, "64", None]:
            requests.append(
                {
                    "ast": {"op": "input", "index": 0},
                    "inputs": ["1"],
                    "word_bits": width,
                }
            )
        requests.extend(
            [
                {
                    "ast": {"op": "const", "value": "0x100000000"},
                    "inputs": [0],
                    "word_bits": 32,
                },
                {
                    "ast": {"op": "input", "index": 0},
                    "inputs": ["0x100000000"],
                    "word_bits": 32,
                },
                {"ast": {"op": "const", "value": "0"}, "inputs": [], "word_bits": 64},
                {
                    "ast": {"op": "const", "value": "0"},
                    "inputs": [0] * 5,
                    "word_bits": 64,
                },
                {
                    "ast": {"op": "const", "value": "0"},
                    "inputs": {"0": "0"},
                    "word_bits": 64,
                },
            ]
        )
        for result in self.run_packets(requests):
            self.assertFalse(result["ok"], result)

    def test_entire_ast_limits_hidden_branches_and_strict_shapes(self):
        def balanced(depth):
            return (
                {"op": "input", "index": 0}
                if depth == 0
                else {"op": "add", "a": balanced(depth - 1), "b": balanced(depth - 1)}
            )

        over_nodes = balanced(8)  # 511 nodes, all without any integer overflow.
        over_depth = {"op": "input", "index": 0}
        for _ in range(24):
            over_depth = {"op": "reverse", "arg": over_depth, "width": 64}
        condition = {
            "op": "eq",
            "a": {"op": "const", "value": "0"},
            "b": {"op": "const", "value": "0"},
        }
        requests = []
        for invalid in [
            over_nodes,
            over_depth,
            {"op": "const", "value": True},
            {"op": "const", "value": "1", "extra": "hidden"},
            {"op": "input", "index": True},
            {"op": "input", "index": 4},
            {"op": "reverse", "arg": {"op": "input", "index": 0}, "width": True},
            {"op": "reverse", "arg": {"op": "input", "index": 0}, "width": 65},
            {"op": "const", "value": "1.5"},
            {
                "op": "unknown",
                "a": {"op": "const", "value": "0"},
                "b": {"op": "const", "value": "0"},
            },
            [],
            None,
        ]:
            requests.append({"ast": invalid, "inputs": ["0"], "word_bits": 64})
            requests.append(
                {
                    "ast": {
                        "op": "ite",
                        "condition": condition,
                        "then": {"op": "const", "value": "1"},
                        "else": invalid,
                    },
                    "inputs": ["0"],
                    "word_bits": 64,
                }
            )
        requests.append({"ast": condition, "inputs": ["0"], "word_bits": 64})
        for result in self.run_packets(requests):
            self.assertFalse(result["ok"], result)
        # A 255-node balanced tree remains within the same resource boundary.
        self.assertEqual(
            self.run_packets([{"ast": balanced(7), "inputs": ["3"], "word_bits": 64}])[
                0
            ],
            {"ok": True, "type": "bigint", "value": "384"},
        )


if __name__ == "__main__":
    unittest.main()
