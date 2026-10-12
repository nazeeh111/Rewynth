"""Execute only the pinned public/owned fixture and generated source, never uploads."""

import ctypes
import hashlib
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tempfile
import unittest
from native_recovery.artifacts import Artifact
from native_recovery.engine import run_operation
from native_recovery.recovery_core import lift_function, verify_ast
from native_recovery.expression import parse_expression

EXAMPLE = (
    Path(__file__).parents[1] / "src/native_recovery/resources/examples/kernels.dylib"
)


@unittest.skipUnless(
    platform.system() == "Darwin"
    and platform.machine() == "arm64"
    and shutil.which("clang"),
    "Controlled native fixture execution requires ARM64 macOS and clang",
)
class ProductNativeTests(unittest.TestCase):
    def test_exact_product_exports_against_original_cpu_and_recompiled_model(self):
        raw = EXAMPLE.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "d6b206f48f758bc43e3498a7de54054f3fcb77b2fafc85618faf96d1f8f1f53e",
        )
        artifact = Artifact(raw)
        original = ctypes.CDLL(str(EXAMPLE.resolve()))
        rng = random.Random(0x42496E)
        cases = [
            ("_kernel_clamp", 1, None),
            ("_kernel_reverse", 1, None),
            ("_kernel_avalanche", 1, None),
            ("_kernel_mixed", 2, None),
            ("_kernel_bits", 4, None),
            ("_kernel_luma", 3, [{"min": 0, "max": 255, "signed": False}] * 3),
        ]
        with tempfile.TemporaryDirectory() as folder:
            for name, arity, domain in cases:
                f, code = artifact.function(name)
                request = {
                    "artifact": artifact.digest,
                    "operation": "recover",
                    "arity": arity,
                    "domain": domain,
                }
                result = run_operation(request, code, f.address, f.name)
                self.assertEqual(
                    result["reconstruction"]["status"], "verified_model", name
                )
                source = Path(folder) / (name + ".c")
                library = source.with_suffix(".dylib")
                source.write_text(result["source"])
                subprocess.run(
                    ["clang", "-O2", "-dynamiclib", str(source), "-o", str(library)],
                    check=True,
                    capture_output=True,
                )
                forward = getattr(original, name[1:])
                forward.argtypes = [ctypes.c_uint32] * arity
                forward.restype = ctypes.c_uint32
                rebuilt = ctypes.CDLL(str(library)).recovered
                rebuilt.argtypes = [ctypes.c_uint32] * arity
                rebuilt.restype = ctypes.c_uint32
                maximum = 256 if domain else 1 << 32
                samples = [
                    [rng.randrange(maximum) for _ in range(arity)] for _ in range(500)
                ]
                samples += [
                    [n] * arity
                    for n in (
                        [0, 1, 127, 128, 254, 255]
                        if domain
                        else [
                            0,
                            1,
                            255,
                            256,
                            0xFFFF,
                            0x7FFFFFFF,
                            0x80000000,
                            0xFFFFFFFF,
                        ]
                    )
                ]
                for values in samples:
                    self.assertEqual(forward(*values), rebuilt(*values), (name, values))
                generated = Artifact(library.read_bytes())
                gf, gcode = generated.function("_recovered")
                generated_model = lift_function(
                    gcode, gf.address, gf.name, arity, domain
                )
                verification = verify_ast(
                    generated_model,
                    parse_expression(result["expression"]),
                    timeout_ms=5000,
                )
                self.assertEqual(verification["status"], "unsat", (name, verification))


if __name__ == "__main__":
    unittest.main()
