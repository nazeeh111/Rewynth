"""Independent CPU checks for the bitfield operation used by rebuilt inverses."""

import ctypes
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tempfile
import unittest
from native_recovery.recovery_core import load_function


@unittest.skipUnless(
    platform.system() == "Darwin"
    and platform.machine() == "arm64"
    and shutil.which("clang"),
    "Owned native fixture requires ARM64 macOS and clang",
)
class NativeBitfieldTests(unittest.TestCase):
    def test_preserved_high_bits_and_extracted_low_bits(self):
        fields = [(0, 1), (0, 32), (13, 19), (31, 1), (8, 8)]
        source = ".text\n" + "".join(
            ".globl _field"
            + str(i)
            + "\n_field"
            + str(i)
            + ":\nbfxil w0,w1,#"
            + str(lsb)
            + ",#"
            + str(width)
            + "\nret\n"
            for i, (lsb, width) in enumerate(fields)
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "owned.s").write_text(source)
            library = root / "owned.dylib"
            subprocess.run(
                ["clang", "-dynamiclib", str(root / "owned.s"), "-o", str(library)],
                check=True,
                capture_output=True,
            )
            native = ctypes.CDLL(str(library))
            rng = random.Random(320519)
            edges = [0, 1, 0xFF, 0xFFFF, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
            inputs = [(a, b) for a in edges for b in edges] + [
                (rng.randrange(1 << 32), rng.randrange(1 << 32)) for _ in range(300)
            ]
            for i, (lsb, width) in enumerate(fields):
                model = load_function(library, "field" + str(i), 2)
                function = getattr(native, "field" + str(i))
                function.argtypes = [ctypes.c_uint32] * 2
                function.restype = ctypes.c_uint32
                mask = (1 << width) - 1
                for a, b in inputs:
                    expected = (a & (0xFFFFFFFF ^ mask)) | ((b >> lsb) & mask)
                    self.assertEqual(model.evaluate([a, b]), expected)
                    self.assertEqual(function(a, b), expected)


if __name__ == "__main__":
    unittest.main()
