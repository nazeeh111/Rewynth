"""Read function bytes without loading or executing an executable."""

from dataclasses import dataclass
from hashlib import sha256
from bisect import bisect_right
import struct

MAX_ARTIFACT = 32 * 1024 * 1024
MAX_FUNCTION = 4096


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class Function:
    name: str
    address: int
    offset: int
    size: int

    def public(self):
        return {
            "name": self.name,
            "address": hex(self.address),
            "size": self.size,
            "supported_size": 0 < self.size <= MAX_FUNCTION,
        }


class Artifact:
    def __init__(self, data: bytes):
        if not 32 <= len(data) <= MAX_ARTIFACT:
            raise ArtifactError("Artifact must be between 32 bytes and 32 MiB.")
        self.data = bytes(data)
        self.digest = sha256(data).hexdigest()
        self.functions = []
        self.relocations = []
        if data[:4] == b"\xcf\xfa\xed\xfe":
            self.format = "Mach-O ARM64"
            self._macho()
        elif data[:4] == b"\x7fELF":
            self.format = "ELF ARM64"
            self._elf()
        else:
            raise ArtifactError(
                "Select a thin, little-endian ARM64 Mach-O or ELF artifact. Universal binaries need a selected ARM64 slice."
            )
        if not self.functions:
            raise ArtifactError(
                "No named code functions found. Supply a symbol-bearing artifact; stripped/function-boundary inference is outside this version."
            )
        self.functions.sort(key=lambda f: (f.address, f.name))

    def _unpack(self, fmt, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(self.data):
            raise ArtifactError("Truncated artifact structure.")
        return struct.unpack_from(fmt, self.data, offset)

    def _range(self, offset, size):
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise ArtifactError("Artifact range exceeds supplied bytes.")
        return self.data[offset : offset + size]

    @staticmethod
    def _name(table, index):
        if not 0 <= index < len(table):
            raise ArtifactError("Invalid symbol name offset.")
        end = table.find(b"\0", index)
        if end < 0 or end - index > 1024:
            raise ArtifactError("Missing or oversized symbol name.")
        return table[index:end].decode("utf-8", errors="replace")

    def _macho(self):
        _, cpu, subtype, filetype, count, commands_size, _, _ = self._unpack("<8I", 0)
        if cpu != 0x100000C or subtype & 0xFFFFFF != 0 or filetype not in (1, 2, 6, 8):
            raise ArtifactError(
                "Requires ordinary ARM64 Mach-O code, without ARM64e pointer authentication."
            )
        if count > 4096:
            raise ArtifactError("Too many Mach-O commands.")
        command_end = 32 + commands_size
        self._range(32, commands_size)
        position, section_number = 32, 0
        code_sections, symtab = {}, None
        total_relocations = 0
        for _ in range(count):
            command, size = self._unpack("<II", position)
            if size < 8 or position + size > command_end:
                raise ArtifactError("Invalid Mach-O command extent.")
            if command == 0x19:
                if size < 72:
                    raise ArtifactError("Truncated Mach-O segment.")
                *_, sections, _ = self._unpack("<II16sQQQQiiII", position)
                if sections > 4096 or 72 + sections * 80 > size:
                    raise ArtifactError("Invalid Mach-O section count.")
                for ordinal in range(sections):
                    section_number += 1
                    (
                        name,
                        segment,
                        address,
                        extent,
                        offset,
                        _,
                        relocation_offset,
                        relocation_count,
                        flags,
                        _,
                        _,
                        _,
                    ) = self._unpack("<16s16sQQ8I", position + 72 + 80 * ordinal)
                    if name.rstrip(b"\0") == b"__text":
                        self._range(offset, extent)
                        code_sections[section_number] = (address, extent, offset)
                        if relocation_count > 200000:
                            raise ArtifactError(
                                "Code relocation count exceeds reader budget."
                            )
                        total_relocations += relocation_count
                        if total_relocations > 200000:
                            raise ArtifactError(
                                "Aggregate Mach-O code relocation count exceeds reader budget."
                            )
                        self._range(relocation_offset, 8 * relocation_count)
                        for relocation in range(relocation_count):
                            relative, relocation_info = self._unpack(
                                "<iI", relocation_offset + 8 * relocation
                            )
                            relocation_width = 1 << ((relocation_info >> 25) & 3)
                            if relative < 0 or relative + relocation_width > extent:
                                raise ArtifactError(
                                    "Unsupported or invalid Mach-O code relocation."
                                )
                            self.relocations.append(
                                (offset + relative, relocation_width)
                            )
            elif command == 2:
                if size < 24 or symtab is not None:
                    raise ArtifactError("Invalid or repeated Mach-O symbol table.")
                _, _, symbol_offset, symbol_count, string_offset, string_size = (
                    self._unpack("<6I", position)
                )
                if symbol_count > 200000:
                    raise ArtifactError("Symbol count exceeds reader budget.")
                self._range(symbol_offset, 16 * symbol_count)
                symtab = (
                    symbol_offset,
                    symbol_count,
                    self._range(string_offset, string_size),
                )
            position += size
        if position != command_end or symtab is None:
            raise ArtifactError("Missing symbol table or inconsistent command area.")
        offset, count, strings = symtab
        entries = []
        for index in range(count):
            name_index, kind, section, _, value = self._unpack(
                "<IBBHQ", offset + 16 * index
            )
            if kind & 0xE0 or kind & 0xE != 0xE or section not in code_sections:
                continue
            base, size, fileoffset = code_sections[section]
            if not base <= value < base + size:
                raise ArtifactError("Code symbol lies outside its section.")
            name = self._name(strings, name_index)
            if name and not name.startswith(("ltmp", "L")):
                entries.append((value, section, name))
        by_section = {}
        for value, section, name in entries:
            by_section.setdefault(section, {}).setdefault(value, []).append(name)
        for section, symbols in by_section.items():
            base, size, fileoffset = code_sections[section]
            addresses = sorted(symbols)
            for index, address in enumerate(addresses):
                end = (
                    addresses[index + 1] if index + 1 < len(addresses) else base + size
                )
                for name in symbols[address]:
                    self.functions.append(
                        Function(
                            name, address, fileoffset + address - base, end - address
                        )
                    )
        if len(self.functions) > 8192:
            raise ArtifactError("Named function count exceeds 8192.")

    def _elf(self):
        if self.data[4:7] != b"\x02\x01\x01":
            raise ArtifactError("Requires little-endian ELF64.")
        header = self._unpack("<16sHHIQQQIHHHHHH", 0)
        if header[2] != 183 or header[1] not in (1, 2, 3):
            raise ArtifactError(
                "Requires an ARM64 ELF object, executable or shared library."
            )
        section_offset, section_size, section_count = header[6], header[11], header[12]
        if section_size != 64 or not 0 < section_count <= 8192:
            raise ArtifactError("Unsupported ELF section table.")
        self._range(section_offset, 64 * section_count)
        sections = [
            self._unpack("<IIQQQQIIQQ", section_offset + 64 * i)
            for i in range(section_count)
        ]
        linked_code = sorted(
            (s[3], s[3] + s[5], s[4]) for s in sections if s[2] & 4 and s[5]
        )
        if header[1] != 1:
            for i, (begin, end, fileoffset) in enumerate(linked_code):
                self._range(fileoffset, end - begin)
                if i and begin < linked_code[i - 1][1]:
                    raise ArtifactError(
                        "Overlapping ELF executable sections are unsupported."
                    )
        code_starts = [s[0] for s in linked_code]
        total_relocations = 0
        for section in sections:
            if section[1] not in (4, 9):
                continue
            size = 24 if section[1] == 4 else 16
            offset, extent, target, entrysize = (
                section[4],
                section[5],
                section[7],
                section[9],
            )
            if (
                entrysize != size
                or extent % size
                or extent // size > 200000
                or target >= section_count
            ):
                raise ArtifactError("Invalid ELF relocation table.")
            total_relocations += extent // size
            if total_relocations > 200000:
                raise ArtifactError(
                    "Aggregate ELF relocation count exceeds reader budget."
                )
            self._range(offset, extent)
            for position in range(offset, offset + extent, size):
                relative, relocation_info = self._unpack("<QQ", position)
                relocation_type = relocation_info & 0xFFFFFFFF
                known_width = {
                    257: 8,
                    258: 4,
                    259: 2,
                    260: 8,
                    261: 4,
                    262: 2,
                    263: 4,
                    1027: 8,
                }.get(relocation_type)
                if header[1] == 1:
                    if sections[target][2] & 4:
                        if relative + (known_width or 1) > sections[target][5]:
                            raise ArtifactError("ELF code relocation exceeds section.")
                        if known_width is None:
                            self.relocations.append(
                                (sections[target][4], sections[target][5])
                            )
                        else:
                            self.relocations.append(
                                (sections[target][4] + relative, known_width)
                            )
                else:
                    index = bisect_right(code_starts, relative) - 1
                    # A wide fixup can begin before a code section and overlap
                    # its first instruction. Preserve the complete interval.
                    next_index = index + 1
                    if known_width and next_index < len(linked_code):
                        begin, end, fileoffset = linked_code[next_index]
                        if relative < begin < relative + known_width:
                            self.relocations.append(
                                (
                                    fileoffset,
                                    min(end - begin, relative + known_width - begin),
                                )
                            )
                    if index >= 0:
                        begin, end, fileoffset = linked_code[index]
                        if relative < end:
                            if known_width is None:
                                self.relocations.append((fileoffset, end - begin))
                            elif relative + known_width > end:
                                raise ArtifactError(
                                    "ELF code relocation exceeds section."
                                )
                            else:
                                self.relocations.append(
                                    (fileoffset + relative - begin, known_width)
                                )
        seen = set()
        total_symbols = 0
        for section in sections:
            if section[1] not in (2, 11):
                continue
            _, _, _, _, offset, extent, link, _, _, entrysize = section
            if (
                entrysize != 24
                or extent % 24
                or extent // 24 > 200000
                or link >= section_count
            ):
                raise ArtifactError("Invalid ELF symbol table.")
            total_symbols += extent // 24
            if total_symbols > 200000:
                raise ArtifactError("Aggregate ELF symbol count exceeds reader budget.")
            self._range(offset, extent)
            strings = self._range(sections[link][4], sections[link][5])
            for position in range(offset, offset + extent, 24):
                name_index, info, _, section_index, value, size = self._unpack(
                    "<IBBHQQ", position
                )
                if info & 15 != 2 or not 0 < section_index < section_count or size == 0:
                    continue
                target = sections[section_index]
                if not target[2] & 4:
                    continue
                relative = value if header[1] == 1 else value - target[3]
                if relative < 0 or relative + size > target[5]:
                    raise ArtifactError("ELF function exceeds code section.")
                self._range(target[4] + relative, size)
                name = self._name(strings, name_index)
                key = (name, value, target[4] + relative)
                if name and key not in seen:
                    self.functions.append(
                        Function(name, value, target[4] + relative, size)
                    )
                    seen.add(key)
        if len(self.functions) > 8192:
            raise ArtifactError("Named function count exceeds 8192.")

    def function(self, name):
        matches = [f for f in self.functions if f.name == name]
        if len(matches) != 1:
            raise ArtifactError("Function name is missing or ambiguous.")
        function = matches[0]
        if not 0 < function.size <= MAX_FUNCTION or function.size % 4:
            raise ArtifactError(
                "Function must be 4-byte aligned and no larger than 4096 bytes."
            )
        if any(
            offset < function.offset + function.size and offset + size > function.offset
            for offset, size in self.relocations
        ):
            raise ArtifactError(
                "Function contains unresolved code relocations. Analyze a linked artifact so instruction bytes have their final meaning."
            )
        return function, self._range(function.offset, function.size)

    def public(self):
        return {
            "sha256": self.digest,
            "format": self.format,
            "size": len(self.data),
            "functions": [f.public() for f in self.functions],
        }
