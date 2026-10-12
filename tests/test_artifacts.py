import struct
import unittest
from pathlib import Path
from native_recovery.artifacts import Artifact, ArtifactError


class ReaderTests(unittest.TestCase):
    def test_linked_wide_relocation_starting_before_code_is_rejected(self):
        ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
        header = struct.pack(
            "<16sHHIQQQIHHHHHH", ident, 3, 183, 1, 0, 0, 64, 0, 64, 0, 0, 64, 5, 0
        )
        sections = [
            b"\0" * 64,
            struct.pack("<IIQQQQIIQQ", 0, 1, 6, 0x1004, 384, 4, 0, 0, 4, 0),
            struct.pack("<IIQQQQIIQQ", 0, 2, 0, 0, 388, 24, 3, 0, 8, 24),
            struct.pack("<IIQQQQIIQQ", 0, 3, 0, 0, 412, 8, 0, 0, 1, 0),
            struct.pack("<IIQQQQIIQQ", 0, 4, 0, 0, 420, 24, 2, 0, 8, 24),
        ]
        data = (
            header
            + b"".join(sections)
            + bytes.fromhex("c0035fd6")
            + struct.pack("<IBBHQQ", 1, 0x12, 0, 1, 0x1004, 4)
            + b"\0sample\0"
            + struct.pack("<QQq", 0x1000, 257, 0)
        )
        artifact = Artifact(data)
        with self.assertRaisesRegex(ArtifactError, "relocations"):
            artifact.function("sample")

    def test_actual_compiled_macho(self):
        path = (
            Path(__file__).parents[1]
            / "src/native_recovery/resources/examples/kernels.dylib"
        )
        a = Artifact(path.read_bytes())
        f, code = a.function("_kernel_luma")
        self.assertEqual(f.size, 32)
        self.assertEqual(len(code), 32)
        self.assertEqual(code[-4:], bytes.fromhex("c0035fd6"))
        self.assertEqual(len(a.digest), 64)
        self.assertTrue(
            {"_kernel_luma", "_kernel_clamp", "_kernel_reverse"}
            <= {f.name for f in a.functions}
        )

    def test_untrusted_magic_and_truncation(self):
        for data in (b"", b"Z" * 100, bytes.fromhex("cffaedfe") + b"\0" * 28):
            with self.assertRaises(ArtifactError):
                Artifact(data)

    def test_oversized_commands_do_not_allocate(self):
        header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 1, 1, 0xFFFFFFFF, 0, 0)
        with self.assertRaises(ArtifactError):
            Artifact(header)

    def test_elf_wrong_architecture(self):
        ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
        header = struct.pack(
            "<16sHHIQQQIHHHHHH", ident, 1, 62, 1, 0, 0, 0, 0, 64, 0, 0, 64, 1, 0
        )
        with self.assertRaisesRegex(ArtifactError, "ARM64"):
            Artifact(header)

    def test_elf_real_byte_offsets(self):
        ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
        header = struct.pack(
            "<16sHHIQQQIHHHHHH", ident, 1, 183, 1, 0, 0, 64, 0, 64, 0, 0, 64, 4, 0
        )
        # Null, code, symbols and strings; code offset320, symbol offset324.
        sections = [
            b"\0" * 64,
            struct.pack("<IIQQQQIIQQ", 0, 1, 6, 0, 320, 4, 0, 0, 4, 0),
            struct.pack("<IIQQQQIIQQ", 0, 2, 0, 0, 324, 24, 3, 0, 8, 24),
            struct.pack("<IIQQQQIIQQ", 0, 3, 0, 0, 348, 8, 0, 0, 1, 0),
        ]
        data = (
            header
            + b"".join(sections)
            + bytes.fromhex("c0035fd6")
            + struct.pack("<IBBHQQ", 1, 0x12, 0, 1, 0, 4)
            + b"\0sample\0"
        )
        a = Artifact(data)
        f, code = a.function("sample")
        self.assertEqual(f.offset, 320)
        self.assertEqual(code.hex(), "c0035fd6")
        bad = bytearray(data)
        struct.pack_into("<Q", bad, 340, 8)
        with self.assertRaisesRegex(ArtifactError, "exceeds"):
            Artifact(bytes(bad))


if __name__ == "__main__":
    unittest.main()
