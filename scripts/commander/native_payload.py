"""Bounded inspection of PE payloads. This never loads or executes a DLL.

Structure and exported names complement build provenance; neither proves a
successful desktop session or that an exported function behaves correctly.
"""
from __future__ import annotations

import mmap
from pathlib import Path
import struct


def inspect_pe(path: Path, *, dll: bool, required_exports=()) -> dict:
    path = Path(path)
    if not 256 <= path.stat().st_size <= 512 * 1024 * 1024:
        raise ValueError("native PE payload size outside bounds")
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        def span(offset, count):
            if offset < 0 or count < 0 or offset + count > len(data):
                raise ValueError("native PE structure exceeds payload")
            return offset

        def unpack(fmt, offset):
            return struct.unpack_from(fmt, data, span(offset, struct.calcsize(fmt)))

        if data[:2] != b"MZ":
            raise ValueError("native component is not a PE payload")
        pe = unpack("<I", 0x3c)[0]
        if data[span(pe, 24):pe + 4] != b"PE\0\0":
            raise ValueError("native component lacks PE signature")
        machine, sections, _, _, _, optional_size, flags = unpack("<HHIIIHH", pe + 4)
        if machine != 0x8664 or not 1 <= sections <= 96 or bool(flags & 0x2000) != dll or not flags & 2:
            raise ValueError("native component requires executable Windows AMD64 PE")
        optional = pe + 24
        span(optional, optional_size)
        if optional_size < 120 or unpack("<H", optional)[0] != 0x20b:
            raise ValueError("native component requires PE32+ headers")
        table = optional + optional_size
        span(table, sections * 40)
        mappings = []
        for index in range(sections):
            header = table + index * 40
            virtual_size, rva, raw_size, raw = unpack("<IIII", header + 8)
            if raw_size:
                span(raw, raw_size)
                mappings.append((rva, max(virtual_size, raw_size), raw, raw_size))

        def offset(rva, count):
            matches = [raw + rva - start for start, size, raw, raw_size in mappings
                       if start <= rva and rva + count <= start + size and rva - start + count <= raw_size]
            if len(matches) != 1:
                raise ValueError("native PE RVA lacks a unique backed section")
            return span(matches[0], count)

        entry = unpack("<I", optional + 16)[0]
        if not dll:
            if not entry:
                raise ValueError("native executable lacks an entry point")
            offset(entry, 1)
        exports = set()
        directories = unpack("<I", optional + 108)[0]
        export_rva, export_size = unpack("<II", optional + 112) if directories else (0, 0)
        if export_rva and export_size:
            directory = offset(export_rva, 40)
            functions, names, addresses, name_rvas, ordinals = unpack("<IIIII", directory + 20)
            if functions > 65536 or names > functions:
                raise ValueError("native PE export count outside bounds")
            addresses, name_rvas, ordinals = offset(addresses, functions * 4), offset(name_rvas, names * 4), offset(ordinals, names * 2)
            for index in range(names):
                start = offset(unpack("<I", name_rvas + index * 4)[0], 1)
                end = data.find(b"\0", start, min(start + 257, len(data)))
                if end == -1:
                    raise ValueError("native PE export name outside bounds")
                # Check the entire name remains in the same backed RVA range.
                offset(unpack("<I", name_rvas + index * 4)[0], end - start + 1)
                try:
                    name = data[start:end].decode("ascii")
                except UnicodeDecodeError as exc:
                    raise ValueError("native PE export name is not ASCII") from exc
                ordinal = unpack("<H", ordinals + index * 2)[0]
                if ordinal >= functions or name in exports:
                    raise ValueError("native PE export ordinal/name invalid")
                function_rva = unpack("<I", addresses + ordinal * 4)[0]
                if name in required_exports:
                    if export_rva <= function_rva < export_rva + export_size:
                        raise ValueError("native SENTRA ABI export must not be forwarded")
                    offset(function_rva, 1)
                exports.add(name)
        if not set(required_exports) <= exports:
            raise ValueError("native payload lacks required SENTRA ABI export")
        return {"format": "PE32+", "machine": "AMD64", "dll": dll,
                "required_exports": sorted(required_exports), "export_count": len(exports)}
