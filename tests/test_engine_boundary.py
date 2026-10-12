import unittest
from native_recovery.engine import run_operation


class EngineBoundaryTests(unittest.TestCase):
    def test_high_kernel_addresses_remain_exact_in_browser_json(self):
        address = 0xFFFFFFF000001004
        result = run_operation(
            {"artifact": "a" * 64, "operation": "evaluate", "arity": 1, "inputs": [42]},
            bytes.fromhex("00044011c0035fd6"),
            address,
            "own_shift",
        )
        self.assertEqual(result["model"]["instructions"][0]["address"], hex(address))
        self.assertEqual(result["witness"]["trace"][0]["address"], hex(address))
        self.assertEqual(result["witness"]["output_u32"], 4138)


if __name__ == "__main__":
    unittest.main()
