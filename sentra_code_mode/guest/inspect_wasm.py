"""Small ABI reader for the build pipeline; no WASM execution or host runtime.

Rejects start functions, WASI/imported memory, extra exports, ABI type mismatch
and unbounded/shared/memory64 declarations. Runtime repeats these checks.
"""
import sys
from pathlib import Path

FUNCTIONS = {
    "configure": ([0x7e] + [0x7f] * 6, [0x7f]), "eval_source": ([0x7f, 0x7f], [0x7f]),
    "classify_exception": ([], [0x7f]), "alloc": ([0x7f], [0x7f]),
    "reset_heap": ([], []), "shutdown": ([], []), "fuel_used": ([], [0x7e]),
    **{name: ([], [0x7f]) for name in ("result_ptr", "result_len", "error_ptr", "error_len", "tool_count")},
}


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def byte(self):
        if self.pos >= len(self.data):
            raise ValueError("truncated WASM ABI")
        value = self.data[self.pos]; self.pos += 1
        return value

    def uint(self):
        value = 0
        for shift in range(0, 35, 7):
            byte = self.byte()
            if shift == 28 and byte & 0xf0:
                raise ValueError("WASM integer overflow")
            value |= (byte & 0x7f) << shift
            if not byte & 0x80:
                return value
        raise ValueError("unbounded WASM integer")

    def take(self, length):
        if length > len(self.data) - self.pos:
            raise ValueError("WASM section exceeds bytes")
        value = self.data[self.pos:self.pos + length]; self.pos += length
        return value

    def name(self):
        length = self.uint()
        if length > 256:
            raise ValueError("unbounded WASM name")
        return self.take(length).decode("utf-8")


def inspect_abi(raw, *, memory_bytes=32 * 1024 * 1024):
    if not 8 <= len(raw) <= 32 * 1024 * 1024 or raw[:8] != b"\x00asm\x01\x00\x00\x00":
        raise ValueError("WASM v1 binary required")
    reader = Reader(raw[8:]); sections = {}
    while reader.pos < len(reader.data):
        kind, length = reader.byte(), reader.uint()
        data = reader.take(length)
        if kind == 0:
            continue
        if kind in sections or kind == 8:
            raise ValueError("duplicate section or forbidden guest start function")
        sections[kind] = data
    types = []
    part = Reader(sections.get(1, b"\x00"))
    count = part.uint()
    if count > 16384:
        raise ValueError("unbounded function types")
    for _ in range(count):
        if part.byte() != 0x60:
            raise ValueError("only guest function types accepted")
        n = part.uint()
        if n > 32:
            raise ValueError("unbounded function parameters")
        params = [part.byte() for _ in range(n)]
        n = part.uint()
        if n > 1:
            raise ValueError("unexpected multi-value guest signature")
        types.append((params, [part.byte() for _ in range(n)]))
    imports = Reader(sections.get(2, b"\x00"))
    if imports.uint() != 1 or imports.name() != "env" or imports.name() != "sentra_host_call" or imports.byte() != 0:
        raise ValueError("sole env.sentra_host_call function import required")
    imported_type = imports.uint()
    if imported_type >= len(types) or types[imported_type] != ([0x7f] * 4, [0x7f]):
        raise ValueError("host import signature differs from ABI")
    if imports.pos != len(imports.data):
        raise ValueError("unexpected import section bytes")
    functions = Reader(sections.get(3, b"\x00"))
    count = functions.uint()
    if count > 65536:
        raise ValueError("unbounded guest functions")
    function_types = [imported_type] + [functions.uint() for _ in range(count)]
    memory = Reader(sections.get(5, b"\x00"))
    if memory.uint() != 1 or memory.uint() != 1:
        raise ValueError("one unshared wasm32 memory with an explicit maximum required")
    initial, maximum = memory.uint(), memory.uint()
    if initial > maximum or initial * 65536 > memory_bytes or maximum > 512:
        raise ValueError("guest memory outside ABI bounds")
    exports = Reader(sections.get(7, b"\x00")); names = set()
    count = exports.uint()
    if count != len(FUNCTIONS) + 1:
        raise ValueError("guest export count differs from ABI")
    for _ in range(count):
        name, kind, index = exports.name(), exports.byte(), exports.uint()
        if name in names:
            raise ValueError("duplicate guest export")
        names.add(name)
        if name == "memory":
            if (kind, index) != (2, 0):
                raise ValueError("guest exported memory identity differs")
        elif name not in FUNCTIONS or kind != 0 or index >= len(function_types):
            raise ValueError("unexpected guest export")
        else:
            type_id = function_types[index]
            if type_id >= len(types) or types[type_id] != FUNCTIONS[name]:
                raise ValueError("guest exported function signature differs")
    if names != {"memory", *FUNCTIONS}:
        raise ValueError("missing guest exports")
    return {"abi": 1, "host_imports": ["env.sentra_host_call"], "wasi_imports": False,
            "initial_memory_bytes": initial * 65536, "maximum_memory_bytes": maximum * 65536}


if __name__ == "__main__":
    with Path(sys.argv[1]).open("rb") as stream:
        inspect_abi(stream.read(32 * 1024 * 1024 + 1))
