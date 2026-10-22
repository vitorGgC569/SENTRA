"""Actual FCI cabinets, MSI media/file tables and extraction; no installation."""
import os
from pathlib import Path
import shutil
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Installer/FCI integration")


def test_partitions_keep_order_at_exact_bound_and_reject_single_oversize(tmp_path):
    from scripts.commander.build_msi import _cabinet_partitions
    files = []
    for i, size in enumerate((4, 4, 1)):
        path = tmp_path / str(i)
        path.write_bytes(b"x" * size)
        files.append((str(path), "id" + str(i)))
    assert _cabinet_partitions(files, 8) == [files[:2], files[2:]]
    with pytest.raises(ValueError, match="individual MSI file"):
        _cabinet_partitions(files, 3)
    for limit in (0, -1, True, 2 ** 31):
        with pytest.raises(ValueError, match="CAB input bound"):
            _cabinet_partitions(files, limit)


def _rows(db, query, columns):
    view = db.OpenView(query)
    view.Execute(None)
    result = []
    while True:
        record = view.Fetch()
        if record is None:
            break
        result.append(tuple(record.GetInteger(i) if kind == "int" else record.GetString(i)
                            for i, kind in enumerate(columns, 1)))
    view.Close()
    return result


def _extract_cabinet(cabinet, destination):
    """Use the actual Windows CAB decoder without expand.exe's DPX worker."""
    import ctypes
    from ctypes import wintypes

    class FileInCabinet(ctypes.Structure):
        _fields_ = [("NameInCabinet", wintypes.LPCWSTR), ("FileSize", wintypes.DWORD),
                    ("Win32Error", wintypes.DWORD), ("DosDate", wintypes.WORD),
                    ("DosTime", wintypes.WORD), ("DosAttribs", wintypes.WORD),
                    ("FullTargetName", wintypes.WCHAR * 260)]

    callback_type = ctypes.WINFUNCTYPE(wintypes.UINT, ctypes.c_void_p,
        wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t)
    errors = []

    @callback_type
    def callback(_context, notification, first, _second):
        if notification == 0x11:  # SPFILENOTIFY_FILEINCABINET
            try:
                info = ctypes.cast(first, ctypes.POINTER(FileInCabinet)).contents
                name = info.NameInCabinet
                assert name and Path(name).name == name
                target = str(destination / name)
                assert len(target) < 260
                info.FullTargetName = target
                return 1  # FILEOP_DOIT
            except Exception as error:
                errors.append(str(error))
                return 0  # FILEOP_ABORT
        return 0

    api = ctypes.WinDLL("setupapi", use_last_error=True)
    api.SetupIterateCabinetW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                        callback_type, ctypes.c_void_p]
    api.SetupIterateCabinetW.restype = wintypes.BOOL
    assert api.SetupIterateCabinetW(str(cabinet), 0, callback, None), ctypes.get_last_error()
    assert not errors, errors


def test_actual_partitioned_cabs_preserve_global_msi_sequences_and_all_bytes(tmp_path, monkeypatch):
    import msilib
    from scripts.commander import build_msi as build
    source = tmp_path / "source"
    source.mkdir()
    originals = {}
    for name in ("entry.txt", "LICENSE", "nested/LICENSE", "nested/proof.json"):
        path = source / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes((name.encode() + b"-" * 80)[:80])
        originals[name] = path.read_bytes()
    output = tmp_path / "fixture.msi"
    db = msilib.init_database(str(output), msilib.schema, "Disposable MSI QA",
        "{" + str(uuid.uuid4()).upper() + "}", "1.0.0", "Disposable QA")
    captured = tmp_path / "captured"
    captured.mkdir()
    original_add_stream = build.add_stream

    def capture(database, name, filename):
        shutil.copyfile(filename, captured / name)
        original_add_stream(database, name, filename)

    monkeypatch.setattr(build, "add_stream", capture)
    cab = build._PartitionedCAB("sentra.cab", tmp_path / "scratch", input_limit=160)
    target = msilib.Directory(db, cab, None, str(source), "TARGETDIR", "SourceDir")
    feature = msilib.Feature(db, "Fixture", "Fixture", "Disposable", 1, directory=target.logical)
    feature.set_current()
    file_ids = build._add_tree(db, cab, feature, target, source)
    cab.commit(db)
    media = _rows(db, "SELECT `DiskId`,`LastSequence`,`Cabinet` FROM `Media` ORDER BY `DiskId`",
                  ("int", "int", "str"))
    assert media == [(1, 2, "#sentra-0001.cab"), (2, 4, "#sentra-0002.cab")]
    file_rows = _rows(db, "SELECT `File`,`Sequence` FROM `File` ORDER BY `Sequence`", ("str", "int"))
    assert [row[1] for row in file_rows] == [1, 2, 3, 4]
    assert len({row[0] for row in file_rows}) == 4
    streams = {row[0] for row in _rows(db, "SELECT `Name` FROM `_Streams`", ("str",))}
    assert {"sentra-0001.cab", "sentra-0002.cab"} <= streams
    reconstructed = {}
    for disk, last_sequence, name in media:
        folder = tmp_path / f"expanded-{disk}"
        folder.mkdir()
        _extract_cabinet(captured / name[1:], folder)
        reconstructed.update({path.name: path.read_bytes() for path in folder.iterdir()})
    assert {name: reconstructed[logical] for name, logical in file_ids.items()} == originals
    assert not list((tmp_path / "scratch").iterdir())


def test_cab_failure_does_not_commit_partial_media(tmp_path, monkeypatch):
    from scripts.commander import build_msi as build
    source = tmp_path / "input"
    source.write_bytes(b"content")
    cab = build._PartitionedCAB("sentra.cab", tmp_path / "scratch")
    cab.append(str(source), source.name, None)
    calls = []

    def fail(*_):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(build, "FCICreate", fail)
    monkeypatch.setattr(build, "add_data", lambda *_: calls.append("media"))
    monkeypatch.setattr(build, "add_stream", lambda *_: calls.append("stream"))
    with pytest.raises(OSError, match="disk failure"):
        cab.commit(object())
    assert not calls
    assert not list((tmp_path / "scratch").iterdir())
