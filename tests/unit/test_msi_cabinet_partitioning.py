"""Actual FCI cabinets, MSI media/file tables and extraction; no installation."""
import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
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


def test_external_cabs_are_real_installer_media_and_extract_without_registration(tmp_path):
    """Exercise Windows Installer itself, not only the CAB decoder or tables."""
    import msilib
    from scripts.commander import build_msi as build

    msilib._directories.clear()
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
    msilib.add_tables(db, msilib.sequence)
    msilib.add_data(db, "Property", [("ALLUSERS", "2"), ("MSIINSTALLPERUSER", "1")])
    cab = build._PartitionedCAB("fixture.cab", tmp_path / "scratch", input_limit=160,
                                external_root=output.parent)
    target = msilib.Directory(db, cab, None, str(source), "TARGETDIR", "SourceDir")
    feature = msilib.Feature(db, "Fixture", "Fixture", "Disposable", 1, directory=target.logical)
    feature.set_current()
    build._add_tree(db, cab, feature, target, source)
    cab.commit(db)
    assert _rows(db, "SELECT `DiskId`,`LastSequence`,`Cabinet` FROM `Media` ORDER BY `DiskId`",
                 ("int", "int", "str")) == [
                     (1, 2, "fixture-0001.cab"), (2, 4, "fixture-0002.cab")]
    streams = {row[0] for row in _rows(db, "SELECT `Name` FROM `_Streams`", ("str",))}
    assert not {"fixture-0001.cab", "fixture-0002.cab"} & streams
    del target, feature, db
    first_cab = output.parent / "fixture-0001.cab"
    held_cab = first_cab.with_suffix(".held")
    first_cab.rename(held_cab)
    try:
        missing = subprocess.run([
            str(Path(os.environ["SystemRoot"]) / "System32/msiexec.exe"),
            "/a", str(output), "/qn", "/norestart",
            "TARGETDIR=" + str(tmp_path / "missing-cab-image"),
            "/L*v", str(tmp_path / "missing-cab.log"),
        ], creationflags=subprocess.CREATE_NO_WINDOW, timeout=180, check=False)
        assert missing.returncode != 0, "an MSI without its required external CAB must not succeed"
    finally:
        held_cab.rename(first_cab)
    image = tmp_path / "administrative-image"
    log = tmp_path / "administrative.log"
    checked = subprocess.run([
        str(Path(os.environ["SystemRoot"]) / "System32/msiexec.exe"),
        "/a", str(output), "/qn", "/norestart", "TARGETDIR=" + str(image), "/L*v", str(log),
    ], creationflags=subprocess.CREATE_NO_WINDOW, timeout=180, check=False)
    assert checked.returncode == 0, (checked.returncode, log.read_text(encoding="utf-16", errors="replace"))
    assert {name: (image / name).read_bytes() for name in originals} == originals
    assert len(cab.media) == 2
    assert all((output.parent / item["name"]).stat().st_size == item["bytes"] for item in cab.media)


def test_failure_in_later_external_cab_leaves_no_published_media(tmp_path, monkeypatch):
    from scripts.commander import build_msi as build
    for index in range(2):
        (tmp_path / str(index)).write_bytes(b"content")
    destination = tmp_path / "published"
    cab = build._PartitionedCAB("fixture.cab", tmp_path / "scratch", input_limit=7,
                                external_root=destination)
    for index in range(2):
        cab.append(str(tmp_path / str(index)), str(index), None)
    actual = build.FCICreate
    calls = []

    def fail_second(path, files):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("second CAB disk failure")
        return actual(path, files)

    monkeypatch.setattr(build, "FCICreate", fail_second)
    monkeypatch.setattr(build, "add_data", lambda *_: pytest.fail("no media before all CABs exist"))
    with pytest.raises(OSError, match="second CAB disk failure"):
        cab.commit(object())
    assert not destination.exists()
    assert cab.media == []


def _distribution_fixture(tmp_path):
    msi = tmp_path / "SENTRA-Desktop-1.0.1-x64.msi"
    msi.write_bytes(b"inventory-verifier-fixture-not-an-installer")
    cabinet = tmp_path / (msi.stem + "-0001.cab")
    cabinet.write_bytes(b"MSCF" + b"cabinet-inventory-fixture" * 4)
    manifest = {"schema": 1, "msi": msi.name,
                "sha256": hashlib.sha256(msi.read_bytes()).hexdigest(),
                "media": [{"name": cabinet.name, "bytes": cabinet.stat().st_size,
                           "sha256": hashlib.sha256(cabinet.read_bytes()).hexdigest(),
                           "last_sequence": 1}]}
    inventory = msi.with_suffix(".media.json")
    inventory.write_text(json.dumps(manifest), encoding="utf-8")
    return msi, inventory, cabinet, manifest


def test_distribution_inventory_includes_database_cabs_and_bound_manifest(tmp_path):
    from scripts.commander.build_msi import msi_distribution_files
    msi, inventory, cabinet, _ = _distribution_fixture(tmp_path)
    assert msi_distribution_files(msi) == [msi, inventory, cabinet]
    cabinet.unlink()
    with pytest.raises(ValueError, match="cabinet missing"):
        msi_distribution_files(msi)


@pytest.mark.parametrize("change", ["database", "cabinet", "traversal", "sequence", "missing-inventory"])
def test_distribution_inventory_rejects_substitution_and_unsafe_media(tmp_path, change):
    from scripts.commander.build_msi import msi_distribution_files
    msi, inventory, cabinet, manifest = _distribution_fixture(tmp_path)
    if change == "database":
        msi.write_bytes(b"different-database")
    elif change == "cabinet":
        cabinet.write_bytes(b"0" * cabinet.stat().st_size)
    elif change == "missing-inventory":
        inventory.unlink()
    else:
        if change == "traversal":
            manifest["media"][0]["name"] = "../other.cab"
        else:
            manifest["media"][0]["last_sequence"] = 0
        inventory.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="MSI external"):
        msi_distribution_files(msi)


def test_production_builder_closes_database_normalizes_dates_and_avoids_case_collisions(tmp_path):
    """Small fake app bytes exercise the actual builder and Installer, no app is run."""
    import msilib
    import struct
    from scripts.commander import build_msi as build

    source = tmp_path / "source"
    names = [
        "sentra-desktop.exe", "sentra-human.exe", "sentra-human-worker.exe", "sentra-mcp.exe",
        "sentra-browser-relay.exe", "sentra-agent.exe", "sentra-diagnostics.exe", "sentra-admin.exe",
        "sentra-update-helper.exe", "sentra-oma.exe", "sentra-cli.exe", "sentra-canvas.exe", "sentra.exe",
        "tunnel-client.exe", "docs/onboarding_media/SENTRA_SETUP_GUIDE.html",
        "docs/SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md",
        "docs/onboarding_media/mcp-create-tunnel.mp4", "docs/onboarding_media/mcp-connect-connector.mp4",
        "edge_extension/manifest.json", "web-models/win-unpacked/Codex Web GPT.exe",
        "web-models/win-unpacked/resources/runtime/manifest.json",
        "web-models/licenses/codex-chatgpt-web/LICENSE", "web-models/integration-build.json",
        "notices/UPPER/LICENSE", "notices/lower/license", "notices/epoch/LICENSE-APACHE",
    ]
    for name in names:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("fake test fixture " + name).encode())
    epoch = source / "notices/epoch/LICENSE-APACHE"
    os.utime(epoch, (0, 0))
    output = tmp_path / "SENTRA-Desktop-1.0.1-x64.msi"
    build.build_msi(source, output, "1.0.1")
    media = build.msi_distribution_files(output)
    from scripts.commander.msi_media_signing import require_inscribed_cabinets
    with pytest.raises(PermissionError, match="must be inscribed"):
        require_inscribed_cabinets(output)
    assert epoch.stat().st_mtime == 0, "normalization must never mutate the source"
    db = msilib.OpenDatabase(str(output), msilib.MSIDBOPEN_READONLY)
    ids = [row[0] for row in _rows(db, "SELECT `File` FROM `File`", ("str",))]
    assert len({name.casefold() for name in ids}) == len(names)
    for cab in (path for path in media if path.suffix == ".cab"):
        with cab.open("rb") as stream:
            header = stream.read(36)
            stream.seek(struct.unpack_from("<I", header, 16)[0])
            for _ in range(struct.unpack_from("<H", header, 28)[0]):
                fixed = stream.read(16)
                assert struct.unpack_from("<H", fixed, 10)[0] != 0, "CAB date must be valid DOS date"
                while stream.read(1) != b"\0":
                    pass
    del db
    image = tmp_path / "image"
    checked = subprocess.run([
        str(Path(os.environ["SystemRoot"]) / "System32/msiexec.exe"),
        "/a", str(output), "/qn", "/norestart", "TARGETDIR=" + str(image),
        "/L*v", str(tmp_path / "production-builder-admin.log"),
    ], creationflags=subprocess.CREATE_NO_WINDOW, timeout=180, check=False)
    assert checked.returncode == 0
    installed = image / "SENTRA/Commander"
    assert {name: (installed / name).read_bytes() for name in names} == {
        name: (source / name).read_bytes() for name in names}
    # A second build in the same process must retain standard directory IDs.
    repeated = tmp_path / "second/SENTRA-Desktop-1.0.1-x64.msi"
    build.build_msi(source, repeated, "1.0.1")
    assert build.msi_distribution_files(repeated)
    db = msilib.OpenDatabase(str(repeated), msilib.MSIDBOPEN_READONLY)
    directories = {r[0] for r in _rows(db, "SELECT `Directory` FROM `Directory`", ("str",))}
    assert {"TARGETDIR", "INSTALLDIR", "SENTRAMenu"} <= directories
