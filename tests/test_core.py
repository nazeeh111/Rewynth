import sys, unittest, json
from pathlib import Path
from native_recovery.recovery_core import *


class CoreTests(unittest.TestCase):
    def test_shifted_immediate_regression(self):
        m = lift_function(bytes.fromhex("00044011c0035fd6"), 0, "shift", 1)
        self.assertEqual(m.evaluate([0]), 4096)
        self.assertEqual(
            verify_ast(m, binary("add", input_node(0), constant(1)))["status"], "sat"
        )
        self.assertEqual(
            verify_ast(m, binary("add", input_node(0), constant(4096)))["status"],
            "unsat",
        )

    def test_json_integer_types(self):
        for node in [
            {"op": "const", "value": True},
            {"op": "input", "index": False},
            {"op": "reverse", "arg": input_node(0), "width": True},
            {"op": "const", "value": 1, "surprise": "ignored"},
            {"op": [], "a": {}, "b": {}},
        ]:
            with self.subTest(node=node), self.assertRaises(Unsupported):
                ast_expr(node, [z3.BitVec("x", 32)])
        for a in [True, 0, 5]:
            with self.subTest(arity=a), self.assertRaises(Unsupported):
                lift_function(bytes.fromhex("c0035fd6"), 0, "x", a)
        with self.assertRaises(Unsupported):
            lift_function(
                bytes.fromhex("c0035fd6"), 0, "x", 1, [{"min": False, "max": 10}]
            )

    def test_one_bit_reverse(self):
        x = z3.BitVec("x", 32)
        node = {"op": "reverse", "arg": input_node(0), "width": 1}
        self.assertEqual(
            z3.simplify(
                z3.substitute(ast_expr(node, [x]), (x, bv(0xFFFFFFFF)))
            ).as_long(),
            1,
        )

    def test_reject_top_level_boolean(self):
        m = lift_function(bytes.fromhex("c0035fd6"), 0, "identity", 1)
        with self.assertRaises(Unsupported):
            verify_ast(m, binary("eq", input_node(0), constant(0)))

    def test_decode_must_reach_return(self):
        for raw in [
            "00000000c0035fd6",
            "00044011",
            "c0035fd600",
            "000040b9c0035fd6",
            "00000014c0035fd6",
        ]:
            with self.subTest(raw=raw), self.assertRaises(Unsupported):
                lift_function(bytes.fromhex(raw), 0, "rejected", 1)

    def test_gf2_fallback_and_nonaffine(self):
        base = Path(__file__).parent
        m = load_function(
            base.parent / "src/native_recovery/resources/examples/kernels.dylib",
            "kernel_bits",
            4,
        )
        result = synthesize(m, "gf2_affine")
        self.assertEqual(result["status"], "verified_model")
        self.assertEqual(result["oracle_probes"], 129)
        m = load_function(
            base.parent / "src/native_recovery/resources/examples/kernels.dylib",
            "kernel_mixed",
            2,
        )
        result = synthesize(m)
        self.assertEqual(result["status"], "verified_model")
        self.assertEqual(result["grammar"], "lifted_semantics")
        self.assertTrue(result["counterexamples"])

    def test_width_and_flags_generic_lowering(self):
        base = Path(__file__).parent
        for name in [
            "flag_add_carry",
            "flag_add_overflow",
            "flag_sub_carry",
            "flag_sub_overflow",
            "flag_logic",
            "condition_negate",
            "condition_increment",
        ]:
            with self.subTest(name=name):
                m = load_function(base / "fixtures/isa-probe.dylib", name, 4)
                self.assertEqual(
                    synthesize(m, "lifted_semantics")["status"], "verified_model"
                )

    def test_public_nonlinear_hash(self):
        m = load_function(
            Path(__file__).parents[1]
            / "src/native_recovery/resources/examples/kernels.dylib",
            "kernel_avalanche",
            1,
        )
        result = synthesize(m)
        self.assertEqual(result["status"], "verified_model")
        self.assertEqual(result["grammar"], "lifted_semantics")
        inv = inverse_query(m, 0x12345678, 10000)
        self.assertEqual(inv["status"], "sat")
        self.assertEqual(m.evaluate(inv["witness"]["inputs_u32"]), 0x12345678)

    def test_narrow_expr_recovery(self):
        x = z3.BitVec("x", 32)
        expressions = [
            z3.ZeroExt(24, z3.Extract(7, 0, x) + z3.BitVecVal(255, 8)),
            z3.SignExt(24, z3.Extract(7, 0, x)),
            z3.If(z3.Extract(7, 0, x) < z3.BitVecVal(3, 8), x, bv(0)),
        ]
        for e in expressions:
            with self.subTest(expression=str(e)):
                ast = expression_to_ast(e, [x])
                s = z3.Solver()
                s.add(e != ast_expr(ast, [x]))
                self.assertEqual(s.check(), z3.unsat)

    def test_shared_expression_expansion_is_bounded_before_allocation(self):
        x = z3.BitVec("x", 32)
        expression = x
        for _ in range(100):
            expression = expression * expression
        with self.assertRaisesRegex(Unsupported, "expansion"):
            expression_to_ast(expression, [x])

    def test_domain_bounded_synthesis_samples(self):
        m = load_function(
            Path(__file__).parents[1]
            / "src/native_recovery/resources/examples/kernels.dylib",
            "kernel_clamp",
            1,
            [{"min": 0, "max": 127}],
        )
        result = synthesize(m)
        self.assertEqual(result["status"], "verified_model")


if __name__ == "__main__":
    unittest.main()
