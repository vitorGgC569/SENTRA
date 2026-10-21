import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import zipfile

import pytest

from scripts.commander import stage_codex_registration as stage
from sentra_remote import codex_registration_runtime as runtime, codex_setup, installer


@pytest.fixture
def component(tmp_path, monkeypatch):
    data = {"codex.exe": b"unit fixture executable", "LICENSE": b"license", "NOTICE": b"notice"}
    pins = {name: hashlib.sha256(value).hexdigest() for name, value in data.items()}
    monkeypatch.setattr(runtime, "FILES", pins)
    monkeypatch.setattr(stage, "FILES", pins)
    folder = tmp_path / "registration"
    folder.mkdir()
    for name, value in data.items():
        (folder / name).write_bytes(value)
    (folder / "provenance.json").write_text(json.dumps(runtime.provenance()))
    return folder, data


def test_bundled_registration_precedes_external_cli(component, monkeypatch):
    folder, _ = component
    lookup = Mock(side_effect=AssertionError("must use offline component"))
    monkeypatch.setattr(codex_setup.shutil, "which", lookup)
    assert codex_setup.find_codex(folder).samefile(folder / "codex.exe")
    lookup.assert_not_called()


def test_missing_installed_component_does_not_use_external_cli(tmp_path, monkeypatch):
    fallback = Mock(side_effect=AssertionError("missing component must require repair"))
    monkeypatch.setattr(codex_setup.shutil, "which", fallback)
    result = codex_setup.configure_codex(tmp_path / "state", 8123,
                                        registration_root=tmp_path / "missing")
    assert not result["ready"]
    fallback.assert_not_called()


@pytest.mark.parametrize("change", ["binary", "license", "provenance", "missing", "extra"])
def test_tampered_component_never_falls_back_or_runs(component, monkeypatch, change):
    folder, _ = component
    if change in {"binary", "license"}:
        (folder / ("codex.exe" if change == "binary" else "LICENSE")).write_bytes(b"changed")
    elif change == "provenance":
        (folder / "provenance.json").write_text('{}')
    elif change == "missing":
        (folder / "NOTICE").unlink()
    else:
        (folder / "unexpected.dll").write_bytes(b"unapproved")
    command, fallback = Mock(), Mock()
    monkeypatch.setattr(codex_setup, "_command", command)
    monkeypatch.setattr(codex_setup.shutil, "which", fallback)
    result = codex_setup.configure_codex(folder.parent / "state", 8123, registration_root=folder)
    assert not result["installed"] and not result["ready"]
    command.assert_not_called()
    fallback.assert_not_called()


def test_archive_mismatch_preserves_existing_component(component, tmp_path):
    folder, _ = component
    previous = (folder / "codex.exe").read_bytes()
    archive = tmp_path / "unapproved.zip"
    archive.write_bytes(b"unapproved")
    with pytest.raises(ValueError, match="checksum"):
        stage.stage_registration_runtime(archive, folder)
    assert (folder / "codex.exe").read_bytes() == previous


def test_offline_stage_extracts_only_pinned_member(component, tmp_path, monkeypatch):
    folder, data = component
    archive = tmp_path / "official-fixture.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(stage.ARCHIVE_MEMBER, data["codex.exe"])
        package.writestr("../../escape.exe", b"must never extract")
        package.writestr("unneeded-helper.exe", b"not used for registration")
    monkeypatch.setattr(stage, "ARCHIVE_SHA256", runtime.file_sha256(archive))
    monkeypatch.setattr(stage, "ROOT", tmp_path)
    legal = tmp_path / "sentra_remote/provider_notices/codex-registration"
    legal.mkdir(parents=True)
    for name in ("LICENSE", "NOTICE"):
        (legal / name).write_bytes(data[name])
    target = tmp_path / "staged"
    executable = stage.stage_registration_runtime(archive, target)
    assert executable.read_bytes() == data["codex.exe"]
    assert {path.name for path in target.iterdir()} == {*runtime.FILES, "provenance.json"}
    assert not (tmp_path / "escape.exe").exists()
    assert not list(tmp_path.glob("codex-registration-*"))


def test_copy_records_component_as_owned_install_files(component, tmp_path, monkeypatch):
    folder, _ = component
    source, extension, docs = (tmp_path / name for name in ("payload", "extension", "docs"))
    required = [source / "sentra-cli.exe", extension / "manifest.json",
        source / "web-models/win-unpacked/Codex Web GPT.exe",
        source / "web-models/win-unpacked/resources/runtime/manifest.json",
        source / "web-models/licenses/codex-chatgpt-web/LICENSE",
        source / "web-models/integration-build.json", docs / "START_HERE.md",
        docs / "SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md"]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unit fixture")
    import shutil
    shutil.copytree(folder, source / "prerequisites/codex-registration")
    monkeypatch.setattr(installer, "PRODUCTS", ("sentra-cli.exe",))
    monkeypatch.setattr(installer, "payload_root", lambda: source)
    monkeypatch.setattr(installer, "extension_source", lambda: extension)
    monkeypatch.setattr(installer, "docs_source", lambda: docs)
    target = tmp_path / "installed"
    owned = installer._copy_product_files(target)
    runtime.validate_registration_runtime(target / "runtime/codex-registration")
    assert {"runtime/codex-registration/" + name for name in (*runtime.FILES, "provenance.json")} <= set(owned)
