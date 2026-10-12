"""Inverse-program tests, including selected native fixture round trips.

Native execution is limited to these specifically authored public/owned fixtures
and AST-generated inverses, never arbitrary imported analysis targets.

xxHash fixture notice, retained from xxhash.h:
Copyright (C) 2012-2023 Yann Collet
BSD 2-Clause License
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
* Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import ctypes
import hashlib
import json
import platform
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
import z3
from native_recovery import recovery_core as core
from native_recovery.inversion import derive_inverse
from native_recovery.expression import emit_c, format_expression, parse_expression


class InverseTests(unittest.TestCase):
    def model(self, expression, domain=None):
        x = z3.BitVec("arg0", 32)
        return core.FunctionModel(
            {"sha256": "synthetic-model"},
            "test",
            1,
            [x],
            expression(x),
            [domain],
            [],
            [],
        )

    def test_constant_arithmetic(self):
        for op in [
            lambda x: x + core.bv(0xDEADBEEF),
            lambda x: x - core.bv(0x12345678),
            lambda x: core.bv(7) - x,
            lambda x: x ^ core.bv(0xBADF00D),
            lambda x: x * core.bv(0x9E3779B1),
            lambda x: -x,
            lambda x: ~x,
        ]:
            with self.subTest(operation=op):
                result = derive_inverse(self.model(op), timeout_ms=100)
                self.assertEqual(result["status"], "verified_inverse_model", result)
                self.assertEqual(result["proofs"]["chain_binding"]["status"], "unsat")
                self.assertTrue(
                    all(
                        p["forward_after_inverse"]["status"] == "unsat"
                        and p["inverse_after_forward"]["status"] == "unsat"
                        for p in result["proofs"]["local_two_sided"]
                    )
                )

    def test_self_xor_shifts_and_rotates(self):
        for amount in [1, 2, 5, 13, 16, 17, 31]:
            for left in [False, True]:
                with self.subTest(amount=amount, left=left):
                    model = self.model(
                        lambda x: x ^ (x << amount if left else z3.LShR(x, amount))
                    )
                    result = derive_inverse(model, timeout_ms=200)
                    self.assertEqual(result["status"], "verified_inverse_model", result)
                    expression = format_expression(result["ast"])
                    self.assertEqual(parse_expression(expression), result["ast"])
        for amount in [0, 1, 7, 13, 31]:
            result = derive_inverse(
                self.model(lambda x: z3.RotateRight(x, amount)), timeout_ms=200
            )
            self.assertEqual(result["status"], "verified_inverse_model", result)

    def test_all_width_reverse(self):
        model = self.model(
            lambda x: z3.Concat(*[z3.Extract(i, i, x) for i in range(32)])
        )
        result = derive_inverse(model, timeout_ms=200)
        self.assertEqual(result["status"], "verified_inverse_model", result)
        self.assertEqual(result["chain"], [{"op": "reverse32"}])

    def test_reject_nonbijective_and_restricted_domains(self):
        for operation in [
            lambda x: x * 2,
            lambda x: x & 255,
            lambda x: z3.LShR(x, 16),
            lambda x: z3.If(x < 0, core.bv(0), z3.If(x > 255, core.bv(255), x)),
            lambda x: x ^ z3.LShR(x, 0),
            lambda x: core.bv(7),
            lambda x: x * x,
        ]:
            result = derive_inverse(self.model(operation), timeout_ms=100)
            self.assertEqual(result["status"], "unsupported", result)
            self.assertNotIn("ast", result)
        result = derive_inverse(
            self.model(lambda x: x + 1, {"min": 0, "max": 255}), timeout_ms=100
        )
        self.assertEqual(result["status"], "unsupported_domain")
        self.assertNotIn("ast", result)
        full = derive_inverse(
            self.model(lambda x: x + 1, {"min": 0, "max": 0xFFFFFFFF}), timeout_ms=100
        )
        self.assertEqual(full["status"], "verified_inverse_model")

    def test_invalid_resources(self):
        model = self.model(lambda x: x + 1)
        for timeout in [True, 0, 5001]:
            with self.assertRaises(ValueError):
                derive_inverse(model, timeout_ms=timeout)
        for maximum in [True, 0, 65]:
            with self.assertRaises(ValueError):
                derive_inverse(model, max_steps=maximum)

    @unittest.skipUnless(
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and shutil.which("clang"),
        "Native replay requires this Mac ARM64 fixture toolchain",
    )
    def test_three_selected_compiled_fixtures(self):
        # xxHash source: https://github.com/Cyan4973/xxHash/blob/dev/xxhash.h
        # XXH32_avalanche, BSD 2-clause, copyright Yann Collet.
        # Murmur source: https://github.com/aappleby/smhasher/blob/master/src/MurmurHash3.cpp
        # fmix32, public domain, Austin Appleby. Third function is owned here.
        source = """#include <stdint.h>
uint32_t xxhash_finalizer(uint32_t x) { x^=x>>15; x*=UINT32_C(0x85ebca77); x^=x>>13; x*=UINT32_C(0xc2b2ae3d); x^=x>>16; return x; }
uint32_t murmur_finalizer(uint32_t x) { x^=x>>16; x*=UINT32_C(0x85ebca6b); x^=x>>13; x*=UINT32_C(0xc2b2ae35); x^=x>>16; return x; }
uint32_t owned_permutation(uint32_t x) { x+=UINT32_C(0x1234abcd); x=(x<<13)|(x>>19); x*=UINT32_C(0x9e3779b1); x^=UINT32_C(0xa5a5a5a5); x^=x<<17; x^=x>>11; return x; }
uint32_t lossy_clamp(uint32_t x) { return (x & UINT32_C(0x80000000)) ? 0u : x>255u ? 255u : x; }
uint32_t even_product(uint32_t x) { return x*2u; }
"""
        with tempfile.TemporaryDirectory(prefix="native-inverse-fixtures-") as folder:
            root = Path(folder)
            forward_source = root / "forward.c"
            forward_source.write_text(source)
            forward_artifact = root / "forward.dylib"
            subprocess.run(
                [
                    "clang",
                    "-O2",
                    "-dynamiclib",
                    str(forward_source),
                    "-o",
                    str(forward_artifact),
                ],
                check=True,
                capture_output=True,
            )
            original = ctypes.CDLL(str(forward_artifact))
            rng = random.Random(0x5A0137)
            observations = []
            for name in ["xxhash_finalizer", "murmur_finalizer", "owned_permutation"]:
                model = core.load_function(forward_artifact, name, 1)
                result = derive_inverse(model, timeout_ms=200)
                self.assertEqual(result["status"], "verified_inverse_model", result)
                inverse_source = root / (name + ".c")
                inverse_source.write_text(
                    emit_c(result["ast"], function_name="inverse", argument_count=1)
                )
                inverse_artifact = root / (name + ".dylib")
                subprocess.run(
                    [
                        "clang",
                        "-O2",
                        "-dynamiclib",
                        str(inverse_source),
                        "-o",
                        str(inverse_artifact),
                    ],
                    check=True,
                    capture_output=True,
                )
                forward = getattr(original, name)
                forward.argtypes = [ctypes.c_uint32]
                forward.restype = ctypes.c_uint32
                backward = ctypes.CDLL(str(inverse_artifact)).inverse
                backward.argtypes = [ctypes.c_uint32]
                backward.restype = ctypes.c_uint32
                samples = [
                    0,
                    1,
                    2,
                    255,
                    256,
                    0xFFFF,
                    0x10000,
                    0x7FFFFFFF,
                    0x80000000,
                    0xFFFFFFFF,
                ]
                samples.extend(rng.randrange(1 << 32) for _ in range(2000))
                for value in samples:
                    self.assertEqual(
                        backward(forward(value)),
                        value,
                        (name, "inverse(forward)", value),
                    )
                    self.assertEqual(
                        forward(backward(value)),
                        value,
                        (name, "forward(inverse)", value),
                    )
                try:
                    inverse_model = core.load_function(inverse_artifact, "inverse", 1)
                    comparison = core.verify_ast(
                        inverse_model, result["ast"], timeout_ms=500
                    )
                    self.assertIn(
                        comparison["status"], ["unsat", "unknown"], comparison
                    )
                    if comparison["status"] == "unknown":
                        self.assertEqual(comparison.get("reason"), "timeout")
                except core.Unsupported as error:
                    comparison = {"status": "unavailable", "reason": str(error)}
                observations.append(
                    {
                        "function": name,
                        "original_artifact_sha256": model.metadata.get("sha256"),
                        "original_function_sha256": model.metadata.get(
                            "function_sha256"
                        ),
                        "inverse_source_sha256": hashlib.sha256(
                            inverse_source.read_bytes()
                        ).hexdigest(),
                        "inverse_artifact_sha256": hashlib.sha256(
                            inverse_artifact.read_bytes()
                        ).hexdigest(),
                        "compiler": subprocess.check_output(
                            ["clang", "--version"], text=True
                        ).splitlines()[0],
                        "chain": result["chain"],
                        "roundtrip_inputs": len(samples),
                        "roundtrip_directions": 2,
                        "proofs": result["proofs"],
                        "recompiled_inverse_model_equivalence": comparison,
                    }
                )
            for name in ["lossy_clamp", "even_product"]:
                result = derive_inverse(
                    core.load_function(forward_artifact, name, 1), timeout_ms=200
                )
                self.assertEqual(result["status"], "unsupported", result)
            print(
                "\nNATIVE_INVERSE_EVIDENCE " + json.dumps(observations, sort_keys=True),
                flush=True,
            )


if __name__ == "__main__":
    unittest.main()
