"""Synthetic PE structures exercise inspection, never native execution."""
import struct

import pytest

from scripts.commander.native_payload import inspect_pe


def pe_fixture(*, dll=False, export=True):
    data = bytearray(0x800)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 1, 0, 0, 0, 0xf0, 2 | (0x2000 if dll else 0))
    struct.pack_into('<H', data, 0x98, 0x20b)
    struct.pack_into('<I', data, 0x98 + 16, 0x1000)
    struct.pack_into('<I', data, 0x98 + 108, 16)
    struct.pack_into('<IIII', data, 0x188 + 8, 0x600, 0x1000, 0x600, 0x200)
    if export:
        struct.pack_into('<II', data, 0x98 + 112, 0x1100, 0x100)
        struct.pack_into('<IIIII', data, 0x300 + 20, 1, 1, 0x1140, 0x1150, 0x1160)
        struct.pack_into('<I', data, 0x340, 0x1000)
        struct.pack_into('<I', data, 0x350, 0x1180)
        name = b'sentra_desktop_control_abi_v1\0'
        data[0x380:0x380 + len(name)] = name
    return bytes(data)


def inspect(tmp_path, data, **kwargs):
    path = tmp_path / 'fixture.dll'
    path.write_bytes(data)
    return inspect_pe(path, **kwargs)


def test_inspects_structure_without_claiming_execution(tmp_path):
    result = inspect(tmp_path, pe_fixture(dll=True), dll=True, required_exports=('sentra_desktop_control_abi_v1',))
    assert result['machine'] == 'AMD64' and result['export_count'] == 1
    assert 'runtime_verified' not in result


@pytest.mark.parametrize('data', [b'MZ' + bytes(254), b'fixture-not-a-program' * 20])
def test_rejects_header_only_and_arbitrary_bytes(tmp_path, data):
    with pytest.raises(ValueError):
        inspect(tmp_path, data, dll=False)


def test_refuses_wrong_machine_and_library_kind(tmp_path):
    data = bytearray(pe_fixture(dll=True))
    with pytest.raises(ValueError, match='AMD64'):
        inspect(tmp_path, data, dll=False)
    struct.pack_into('<H', data, 0x84, 0x14c)
    with pytest.raises(ValueError, match='AMD64'):
        inspect(tmp_path, data, dll=True)


def test_missing_export_cannot_be_asserted_by_metadata(tmp_path):
    with pytest.raises(ValueError, match='required SENTRA'):
        inspect(tmp_path, pe_fixture(dll=True, export=False), dll=True, required_exports=('sentra_desktop_control_abi_v1',))


def test_forwarded_export_does_not_prove_custom_library(tmp_path):
    data = bytearray(pe_fixture(dll=True))
    struct.pack_into('<I', data, 0x340, 0x1180)
    with pytest.raises(ValueError, match='forwarded'):
        inspect(tmp_path, data, dll=True, required_exports=('sentra_desktop_control_abi_v1',))


def test_unbacked_export_rva_is_refused(tmp_path):
    data = bytearray(pe_fixture(dll=True))
    struct.pack_into('<I', data, 0x350, 0x90000000)
    with pytest.raises(ValueError, match='backed section'):
        inspect(tmp_path, data, dll=True)
