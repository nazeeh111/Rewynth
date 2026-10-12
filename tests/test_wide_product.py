"""Real packaged64-bit artifact, exact protocol and controlled native exports."""

import ctypes
import hashlib
import platform
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
from native_recovery import recovery_core as core
from native_recovery.artifacts import Artifact
from native_recovery.engine import run_operation

RESOURCE = Path(core.__file__).parent / "resources/examples"
FIXTURE = RESOURCE / "wide-kernels.dylib"
FIXTURE_SHA = "1148e2df4e459d85076c101972985d334c9660e4b279a004bbdc3cc33ac801d4"
CASES = [
    ("splitmix64_step", 1),
    ("wide_lattice", 2),
    ("wide_permute", 1),
    ("wide_lossy", 1),
    ("wide_select", 2),
    ("wide_field", 2),
]


def artifact():
    data = FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == FIXTURE_SHA
    return Artifact(data)


def operation(a, name, arity, op, **fields):
    f, code = a.function("_" + name)
    return run_operation(
        {
            "artifact": a.digest,
            "word_bits": 64,
            "arity": arity,
            "operation": op,
            **fields,
        },
        code,
        f.address,
        f.name,
    )


class WideProductTests(unittest.TestCase):
    def test_actual_compiled_forward_inverse_and_exact_counterexample(self):
        a = artifact()
        for name, arity in CASES:
            r = operation(a, name, arity, "recover")
            self.assertEqual(r["reconstruction"]["status"], "verified_model", r)
            self.assertIn("uint64_t recovered(", r["source"])
            self.assertEqual(r["model"]["assumptions"]["word_bits"], 64)
        r = operation(a, "splitmix64_step", 1, "derive_inverse")
        self.assertEqual(r["inverse_program"]["status"], "verified_inverse_model", r)
        self.assertIn("uint64_t rewynth_inverse(", r["source"])
        self.assertEqual(
            r["inverse_program"]["proofs"]["chain_binding"]["status"], "unsat"
        )
        e = operation(
            a, "splitmix64_step", 1, "evaluate", inputs=["0x123456789abcdef0"]
        )
        self.assertEqual(e["witness"]["output_u64"], "0x161922c645ce50e8")
        self.assertEqual(e["witness"]["inputs_u64"], ["0x123456789abcdef0"])
        # The lowbit beyond JSON's2^53 precision must survive; rounded input yields3.
        e = operation(a, "wide_lossy", 1, "evaluate", inputs=["0x20000000000001"])
        self.assertEqual(e["witness"]["output_u64"], 4)
        bad = operation(a, "wide_lossy", 1, "verify", expression="x0")
        self.assertEqual(bad["verification"]["status"], "sat", bad)
        w = bad["verification"]["counterexample"]
        self.assertNotEqual(w["original_output_u64"], w["candidate_output_u64"])
        self.assertNotEqual(
            operation(a, "wide_lossy", 1, "derive_inverse")["inverse_program"][
                "status"
            ],
            "verified_inverse_model",
        )
        restricted = operation(
            a,
            "splitmix64_step",
            1,
            "derive_inverse",
            domain=[{"min": "0", "max": "255", "signed": False}],
        )
        self.assertNotEqual(
            restricted["inverse_program"]["status"], "verified_inverse_model"
        )
        # Reversible arithmetic can compile outside the extractor's chain shape.
        self.assertNotEqual(
            operation(a, "wide_permute", 1, "derive_inverse")["inverse_program"][
                "status"
            ],
            "verified_inverse_model",
        )

    @unittest.skipUnless(
        platform.system() == "Darwin"
        and platform.machine() == "arm64"
        and shutil.which("clang"),
        "ControlledARM64macOSfixtureexecutionrequiresClang",
    )
    def test_actual_native_forward_exports_and_derived_backward_program(self):
        a = artifact()
        original = ctypes.CDLL(str(FIXTURE.resolve()))
        rng = random.Random(6402)
        values = [
            0,
            1,
            (1 << 64) - 1,
            1 << 63,
            (1 << 63) - 1,
            (1 << 32) - 1,
            1 << 32,
            0x20000000000001,
            0x123456789ABCDEF0,
        ] + [rng.getrandbits(64) for _ in range(256)]
        exports = []
        for index, (name, arity) in enumerate(CASES):
            r = operation(a, name, arity, "recover")
            exports.append(
                r["source"].replace(
                    "uint64_t recovered(", f"uint64_t exported_{index}("
                )
            )
        inv = operation(a, "splitmix64_step", 1, "derive_inverse")
        self.assertEqual(inv["inverse_program"]["status"], "verified_inverse_model")
        exports.append(inv["source"])
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "exports.c"
            library = Path(tmp) / "exports.dylib"
            source.write_text("\n".join(exports))
            subprocess.run(
                [
                    shutil.which("clang"),
                    "-O2",
                    "-dynamiclib",
                    str(source),
                    "-o",
                    str(library),
                ],
                check=True,
                capture_output=True,
            )
            rebuilt = ctypes.CDLL(str(library))
            count = 0
            for index, (name, arity) in enumerate(CASES):
                model = core.load_function(FIXTURE, name, arity, word_bits=64)
                f = getattr(original, name)
                g = getattr(rebuilt, f"exported_{index}")
                for fn in (f, g):
                    fn.argtypes = [ctypes.c_uint64] * arity
                    fn.restype = ctypes.c_uint64
                for i, x in enumerate(values):
                    args = [x] if arity == 1 else [x, values[-i - 1]]
                    expected = f(*args)
                    self.assertEqual(model.evaluate(args), expected, (name, args))
                    self.assertEqual(g(*args), expected, (name, args))
                    count += 1
            inverse = rebuilt.rewynth_inverse
            inverse.argtypes = [ctypes.c_uint64]
            inverse.restype = ctypes.c_uint64
            forward = original.splitmix64_step
            forward.argtypes = [ctypes.c_uint64]
            forward.restype = ctypes.c_uint64
            for x in values:
                self.assertEqual(inverse(forward(x)), x)
                self.assertEqual(forward(inverse(x)), x)
            self.assertEqual(inverse(0xE220A8397B1DCDAF), 0)
            print(
                "WIDE_PRODUCT_NATIVE_EVIDENCE",
                {
                    "forward_model_and_C_cases": count,
                    "inverse_roundtrip_assertions": 2 * len(values),
                    "fixture_sha256": FIXTURE_SHA,
                },
            )


if __name__ == "__main__":
    unittest.main()
