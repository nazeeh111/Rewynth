"""The HTTP wire must reject lossy numeric input before an analysis starts."""

import unittest
from native_recovery.words import normalize_request, encode_exact, pattern


class WordBoundaryTests(unittest.TestCase):
    def test_wide_exact_transport_and_reject_rounded_json_numbers(self):
        wide = {
            "word_bits": 64,
            "arity": 1,
            "inputs": ["18446744073709551615"],
            "target": "0xdeadbeef12345679",
            "domain": [{"min": "0", "max": "0xffffffffffffffff", "signed": False}],
        }
        r = normalize_request(wide, wire=True)
        self.assertEqual(r["inputs"], [(1 << 64) - 1])
        self.assertEqual(r["target"], 0xDEADBEEF12345679)
        self.assertEqual(r["domain"][0]["max"], (1 << 64) - 1)
        self.assertEqual(encode_exact(r)["inputs"], ["0xffffffffffffffff"])
        self.assertEqual(wide["inputs"], ["18446744073709551615"])
        for value in [
            9007199254740993,
            9007199254740992.0,
            True,
            None,
            "18446744073709551616",
            "-1",
            "1e9",
            "NaN",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_request(
                    {"word_bits": 64, "arity": 1, "inputs": [value]}, wire=True
                )
        for bits in [True, 16, 128, "64", 64.0]:
            with self.assertRaises(ValueError):
                normalize_request({"word_bits": bits})

    def test_signed_domains_and_default_compatibility(self):
        r = normalize_request(
            {
                "word_bits": 64,
                "arity": 1,
                "domain": [
                    {
                        "min": "-9223372036854775808",
                        "max": "9223372036854775807",
                        "signed": True,
                    }
                ],
            },
            wire=True,
        )
        self.assertEqual(r["domain"][0]["min"], -(1 << 63))
        self.assertEqual(pattern(-1, 64, signed=True), (1 << 64) - 1)
        for domain in [
            {"min": "-1", "max": "0", "signed": False},
            {"min": "1", "max": "0", "signed": True},
            {"min": "0", "max": "9223372036854775808", "signed": True},
            {"min": 0, "max": "1", "signed": False},
            {"min": "0", "max": "1", "signed": 1},
        ]:
            with self.assertRaises(ValueError):
                normalize_request(
                    {"word_bits": 64, "arity": 1, "domain": [domain]}, wire=True
                )
        old = normalize_request(
            {"arity": 1, "inputs": [0xFFFFFFFF], "domain": [None]}, wire=True
        )
        self.assertEqual(old["word_bits"], 32)
        self.assertEqual(old["inputs"], [0xFFFFFFFF])
        self.assertEqual(
            encode_exact({"address": 0xFFFFFFF000001004, "n": -(1 << 63)}),
            {"address": "0xfffffff000001004", "n": "-0x8000000000000000"},
        )


if __name__ == "__main__":
    unittest.main()
