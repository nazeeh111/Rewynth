"""Whole-state edits must not inherit a return-only equivalence conclusion."""

import json
from pathlib import Path
import unittest

from native_recovery.artifacts import Artifact
from native_recovery.engine import run_operation
from native_recovery.transitions import input_count
from native_recovery.words import normalize_request


class MemoryProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "src/native_recovery/resources/examples/pcg-basic.o"
        cls.artifact = Artifact(path.read_bytes())
        cls.function, cls.code = cls.artifact.function("_pcg32_random_r")

    def operate(self, operation, **extra):
        request = {"operation": operation, "artifact": self.artifact.digest,
                   "arity": 1, "word_bits": 64, "memory": {"argument": 0, "words": 2}, **extra}
        return run_operation(request, self.code, self.function.address, self.function.name)

    def test_recover_full_transition_and_reject_deleted_store(self):
        recovered = self.operate("recover")
        self.assertEqual(recovered["reconstruction"]["verification"]["status"], "unsat")
        source = recovered["expression"]
        verified = self.operate("verify", expression=source)
        self.assertEqual(verified["verification"]["status"], "unsat")
        edit = json.loads(source)
        edit["memory"][0] = "x0"  # Same immediate return, lost next-state write.
        broken = self.operate("verify", expression=json.dumps(edit))["verification"]
        self.assertEqual(broken["status"], "sat")
        witness = broken["counterexample"]
        self.assertEqual(witness["original_output_u64"], witness["candidate_output_u64"])
        self.assertEqual(witness["differences"], ["memory[0]"])
        # An unchanged field is observable, not omitted because no store touches it.
        edit = json.loads(source)
        edit["memory"][1] = "x1 ^ 1"
        broken = self.operate("verify", expression=json.dumps(edit))["verification"]
        self.assertEqual(broken["status"], "sat")
        self.assertEqual(broken["counterexample"]["differences"], ["memory[1]"])
        self.assertIn("rewynth_state rewynth_transition(uint64_t x0, uint64_t x1)", verified["source"])

    def test_evaluate_exact_state_and_constraints(self):
        state = 0x853C49E6748FEA9B
        inc = 0xDA3E39CB94B95BDB
        witness = self.operate("evaluate", inputs=[hex(state), hex(inc)])["witness"]
        exact = lambda v: int(v, 0) if isinstance(v, str) else v
        expected = (state * 6364136223846793005 + inc) & ((1 << 64) - 1)
        self.assertEqual(list(map(exact, witness["memory_u64"])), [expected, inc])
        self.assertTrue(any(row.get("kind") == "memory_write" for row in witness["trace"]))
        domain = [{"min": "0", "max": "0", "signed": False}, None]
        with self.assertRaisesRegex(ValueError, "domain"):
            self.operate("evaluate", inputs=["1", "1"], domain=domain)
        with self.assertRaises(ValueError):
            self.operate("evaluate", inputs=["1"])

    def test_memory_inverses_and_default_admission_are_explicit(self):
        for operation in ("inverse", "derive_inverse"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "Inverse"):
                self.operate(operation, target="1")
        with self.assertRaises(ValueError):
            run_operation({"operation": "recover", "artifact": self.artifact.digest, "arity": 1, "word_bits": 64}, self.code, self.function.address, self.function.name)

    def test_transition_shape_and_expression_boundaries(self):
        sources = ["x0", "{}", '{"return":"x0","return":"x1","memory":["x0","x1"]}',
                   json.dumps({"return": "x0", "memory": ["x0"]}),
                   json.dumps({"return": "eq(x0,x1)", "memory": ["x0", "x1"]}),
                   json.dumps({"return": "x3", "memory": ["x0", "x1"]}),
                   json.dumps({"return": "__import__('os')", "memory": ["x0", "x1"]}),
                   json.dumps({"return": "0 #" + "🌍" * 10000, "memory": ["0 #" + "🌍" * 10000, "0 #" + "🌍" * 10000]}, ensure_ascii=False),
                   " " * 65537]
        for source in sources:
            with self.subTest(source=source[:80]), self.assertRaises(ValueError):
                self.operate("verify", expression=source)

    def test_public_declaration_and_wire_domain_mapping(self):
        invalid = [{}, {"argument": True, "words": 2}, {"argument": 1, "words": 2},
                   {"argument": 0, "words": 0}, {"argument": 0, "words": 4},
                   {"argument": 0, "words": 2, "size": 16}]
        for memory in invalid:
            with self.subTest(memory=memory), self.assertRaises(ValueError):
                input_count(1, memory, 64)
        with self.assertRaises(ValueError):
            input_count(4, {"argument": 0, "words": 2}, 64)
        with self.assertRaises(ValueError):
            input_count(1, {"argument": 0, "words": 1}, 32)
        request = {"arity": 1, "word_bits": 64, "memory": {"argument": 0, "words": 2},
                   "inputs": ["0xffffffffffffffff", "1"], "domain": [None, None]}
        self.assertEqual(normalize_request(request, wire=True)["inputs"], [(1 << 64)-1, 1])
        with self.assertRaises(ValueError):
            normalize_request({**request, "domain": [None]}, wire=True)
        with self.assertRaises(ValueError):
            normalize_request({**request, "inputs": [9007199254740993, "1"]}, wire=True)


if __name__ == "__main__":
    unittest.main()
