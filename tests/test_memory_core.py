"""Synthetic, data-only ARM64 state transitions; no native fixture execution."""
import unittest

import z3

from native_recovery import recovery_core as core


MASK = (1 << 64) - 1
RET = 0xD65F03C0


def code(*instructions):
    return b"".join(word.to_bytes(4, "little") for word in instructions)


def access(load, size, rt, rn=0, offset=0):
    # ARM64 unsigned-immediate addressing; offset is scaled by access size.
    bases = {1: 0x39000000, 2: 0x79000000, 4: 0xB9000000, 8: 0xF9000000}
    assert offset >= 0 and offset % size == 0
    return bases[size] | (int(load) << 22) | ((offset // size) << 10) | (rn << 5) | rt


def pair(load, rt, rt2, rn=0, offset=0, size=8):
    assert offset % size == 0
    return (0xA9000000 if size == 8 else 0x29000000) | (int(load) << 22) | (((offset // size) & 127) << 15) | (rt2 << 10) | (rn << 5) | rt


def add(rd, rn, immediate):
    return 0x91000000 | (immediate << 10) | (rn << 5) | rd


def mov(rd, rn):
    return 0xAA0003E0 | (rn << 16) | rd


def lift(*instructions, arity=1, memory=None, domain=None):
    return core.lift_function(code(*instructions), 0, "synthetic_memory", arity,
                              domain, word_bits=64,
                              memory={"argument": 0, "words": 2} if memory is None else memory)


class MemoryCoreTests(unittest.TestCase):
    def test_load_update_and_preserve_second_word(self):
        # ldp x9,x10,[x0]; add x9,x9,#1; str x9,[x0]; mov x0,x10; ret
        model = lift(pair(True, 9, 10), add(9, 9, 1), access(False, 8, 9), mov(0, 10), RET)
        self.assertEqual(model.arity, 2)
        self.assertEqual(model.machine_arity, 1)
        for state, inc in [(0, 7), (MASK, 1 << 63), (0xDEADBEEF, MASK)]:
            self.assertEqual(model.evaluate_transition([state, inc]),
                             {"return": inc, "memory": [(state + 1) & MASK, inc]})
            self.assertEqual(model.evaluate([state, inc]), inc)
        # Aligned accesses must retain whole words, not expand to eight byte ASTs.
        self.assertTrue(z3.eq(model.expr, model.inputs[1]))
        self.assertTrue(z3.eq(model.post_memory[1], model.inputs[1]))
        self.assertEqual(core.expression_to_ast(model.post_memory[0], model.inputs)["op"], "add")

    def test_logical_inputs_and_domains_follow_machine_register_order(self):
        # Pointer is x1; logical inputs are x0,x2,mem[0],mem[8].
        model = lift(access(True, 8, 9, 1), 0x8B020129, access(False, 8, 9, 1), RET,
                     arity=3, memory={"argument": 1, "words": 2},
                     domain=[{"min": 1, "max": 3}, None, None, None])
        self.assertEqual(model.evaluate_transition([2, 11, 7, 23]),
                         {"return": 2, "memory": [18, 23]})
        assumptions = model.assumptions()
        self.assertEqual(assumptions["argument_registers"], ["x0", "x1", "x2"])
        self.assertEqual([row.get("register") for row in assumptions["logical_inputs"][:2]], ["x0", "x2"])
        self.assertEqual(assumptions["memory"]["base_address"], core.MEMORY_BASE)
        solver = z3.Solver(); solver.add(*model.constraints(), model.inputs[0] == 4)
        self.assertEqual(solver.check(), z3.unsat)

    def test_little_endian_partial_overlap_and_forwarding(self):
        # x1 supplies low store bytes, x2 is a derived pointer into the region.
        model = lift(access(False, 4, 1), add(2, 0, 3), access(False, 2, 1, 2),
                     access(True, 8, 0), RET, arity=2)
        initial = 0x8877665544332211
        value = 0xFEDCBA9876543210
        expected = bytearray(initial.to_bytes(8, "little"))
        expected[0:4] = value.to_bytes(8, "little")[:4]
        expected[3:5] = value.to_bytes(8, "little")[:2]
        word = int.from_bytes(expected, "little")
        self.assertEqual(model.evaluate_transition([value, initial, 9]),
                         {"return": word, "memory": [word, 9]})

    def test_unaligned_cross_word_store_and_read(self):
        model = lift(add(2, 0, 5), access(False, 8, 1, 2), access(True, 8, 0, 2), RET, arity=2)
        value, first, second = 0xFEDCBA9876543210, 0x0102030405060708, 0x1112131415161718
        expected = bytearray(first.to_bytes(8, "little") + second.to_bytes(8, "little"))
        expected[5:13] = value.to_bytes(8, "little")
        self.assertEqual(model.evaluate_transition([value, first, second]),
                         {"return": value, "memory": [int.from_bytes(expected[:8], "little"), int.from_bytes(expected[8:], "little")]})

    def test_unsigned_load_widths_and_store_zero_register(self):
        initial = 0xFEDCBA9876543210
        for size in (1, 2, 4, 8):
            with self.subTest(size=size):
                model = lift(access(True, size, 0), RET)
                self.assertEqual(model.evaluate([initial, 7]), initial & ((1 << (size * 8)) - 1))
        model = lift(access(False, 2, 31), access(True, 8, 0), RET)
        self.assertEqual(model.evaluate_transition([initial, 7]),
                         {"return": initial & ~65535, "memory": [initial & ~65535, 7]})

    def test_pair_stores_and_negative_fixed_displacement(self):
        # Derived pointer x3 is base+8, negative pair offset returns to base.
        model = lift(add(3, 0, 8), pair(False, 1, 2, 3, -8), pair(True, 0, 4), RET,
                     arity=3, memory={"argument": 0, "words": 2})
        self.assertEqual(model.evaluate_transition([11, 23, 7, 9]),
                         {"return": 11, "memory": [11, 23]})
        # W pair writes occupy two four-byte slots, leaving upper word untouched.
        model = lift(pair(False, 1, 1, size=4), access(True, 8, 0), RET, arity=2)
        self.assertEqual(model.evaluate_transition([0xABCDEF0123456789, 0, 7]),
                         {"return": 0x2345678923456789, "memory": [0x2345678923456789, 7]})

    def test_conditional_store_merges_with_unchanged_memory(self):
        # cbz x1,+8; str x1,[x0]; ldr x0,[x0]; ret
        model = lift(0xB4000041, access(False, 8, 1), access(True, 8, 0), RET, arity=2)
        for value, result in [(0, 19), (7, 7), (MASK, MASK)]:
            self.assertEqual(model.evaluate_transition([value, 19, 23]),
                             {"return": result, "memory": [result, 23]})
        self.assertEqual([r["kind"] for r in model.trace([0, 19, 23]) if r.get("kind", "").startswith("memory_")], ["memory_read"])

    def test_separate_returns_collect_each_memory_state(self):
        # cbz x1,+12; str x1,[x0]; ret; str x1,[x0,#8]; ret
        model = lift(0xB4000061, access(False, 8, 1), RET, access(False, 8, 1, offset=8), RET, arity=2)
        self.assertEqual(model.evaluate_transition([0, 19, 23])["memory"], [19, 0])
        self.assertEqual(model.evaluate_transition([7, 19, 23])["memory"], [7, 23])

    def test_pair_trace_retains_both_memory_and_register_values(self):
        model = lift(pair(True, 9, 10), pair(False, 10, 9), mov(0, 9), RET)
        rows = model.trace([11, 23])
        self.assertEqual([(r["destination"], r["value_u64"]) for r in rows if r["address"] == 0],
                         [("memory[0:8]", 11), ("memory[8:16]", 23), ("x9", 11), ("x10", 23)])
        self.assertEqual([r["value_u64"] for r in rows if r.get("kind") == "memory_write"], [23, 11])

    def test_memory_declaration_validation_and_old_default_refusal(self):
        for memory, arity, bits in [({}, 1, 64), ({"argument": True, "words": 1}, 1, 64),
            ({"argument": 1, "words": 1}, 1, 64), ({"argument": 0, "words": False}, 1, 64),
            ({"argument": 0, "words": 4}, 1, 64), ({"argument": 0, "words": 1, "extra": 0}, 1, 64),
            ({"argument": 0, "words": 2}, 4, 64), ({"argument": 0, "words": 1}, 1, 32), ([], 1, 64)]:
            with self.subTest(memory=memory), self.assertRaises(core.Unsupported):
                core.lift_function(code(RET), 0, "bad", arity, word_bits=bits, memory=memory)
        with self.assertRaises(core.Unsupported):
            core.lift_function(code(access(True, 8, 0), RET), 0, "default", 1, word_bits=64)
        with self.assertRaises(core.Unsupported):
            lift(RET, domain=[None])

    def test_bounds_symbolic_address_writeback_and_unsupported_memory_refuse(self):
        for instructions in [
            [access(True, 8, 0, offset=16), RET],
            [add(2, 0, 12), access(True, 8, 0, 2), RET],
            [access(True, 8, 0, 1), RET],
            [0xF8616800, RET],  # ldr x0,[x0,x1]
            [0xF8408400, RET],  # ldr x0,[x0],#8
            [0xF8408C00, RET],  # ldr x0,[x0,#8]!
            [0xA8C10409, RET],  # pair post-index/writeback
            [0xB9800000, RET],  # ldrsw
            [0xC85F7C00, RET],  # ldxr
            [pair(True, 9, 9), RET],  # unpredictable duplicate LDP destination
        ]:
            with self.subTest(instructions=instructions), self.assertRaises(core.Unsupported):
                lift(*instructions, arity=2)

    def test_transition_values_validate_and_nonmemory_api_stays_compatible(self):
        model = lift(access(True, 8, 0), RET)
        for values in ([1], [1, 1 << 64], [True, 1]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                model.evaluate_transition(values)
        plain = core.lift_function(code(RET), 0, "plain", 1, word_bits=64)
        self.assertEqual(plain.evaluate_transition([7]), {"return": 7, "memory": []})
        self.assertEqual(plain.assumptions()["memory"], "none; memory instructions rejected")

    def test_one_and_three_word_declarations_preserve_full_region(self):
        for words in (1, 3):
            model = lift(access(True, 8, 0, offset=8*(words-1)), RET,
                         memory={"argument": 0, "words": words})
            values = [11, 23, MASK][:words]
            self.assertEqual(model.evaluate_transition(values), {"return": values[-1], "memory": values})
            self.assertEqual(len(model.post_memory), words)

    def test_scalar_proof_and_inverse_entrypoints_refuse_memory_models(self):
        model = lift(access(False, 8, 1), RET, arity=2)
        # Return x0 is the fixed pointer before and after any store edit. That
        # return equality must never become an equivalence claim for this mode.
        for operation in [
            lambda: core.verify_ast(model, core.constant(core.MEMORY_BASE, 64)),
            lambda: core.inverse_query(model, core.MEMORY_BASE),
            lambda: core.synthesize(model, "lifted_semantics"),
        ]:
            with self.assertRaisesRegex(core.Unsupported, "[Mm]emory"):
                operation()


if __name__ == "__main__":
    unittest.main()
