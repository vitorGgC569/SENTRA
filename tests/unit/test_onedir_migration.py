from pathlib import Path
from unittest.mock import Mock
import json
import zipfile

import pytest

from sentra_remote.onedir import support_name, support_inventory, copy_support
from scripts.commander.onedir import publish_component


def bundle(root, data=b"new"):
    root.mkdir(parents=True)
    (root / "demo.exe").write_bytes(data)
    runtime = root / support_name("demo.exe")
    runtime.mkdir()
    (runtime / "python312.dll").write_bytes(data + b"-python")
    (runtime / "driver.dat").write_bytes(data + b"-driver")
    return root


def test_locked_executable_rolls_back_executable_and_runtime_as_one_component(tmp_path, monkeypatch):
    source, target = bundle(tmp_path / "new"), bundle(tmp_path / "old", b"old")
    before = support_inventory(target, ("demo.exe",))
    import scripts.commander.onedir as module
    replace = module.os.replace
    def locked(origin, destination):
        if Path(origin) == source / "demo.exe":
            raise PermissionError("simulated Windows executable lock")
        return replace(origin, destination)
    monkeypatch.setattr(module.os, "replace", locked)
    with pytest.raises(PermissionError):
        publish_component(source, target, "demo.exe")
    assert (target / "demo.exe").read_bytes() == b"old"
    assert support_inventory(target, ("demo.exe",)) == before


def test_build_cannot_publish_into_installed_application(tmp_path):
    source, target = bundle(tmp_path / "new"), bundle(tmp_path / "installed", b"installed")
    (target / ".sentra-install.json").write_text("{}")
    with pytest.raises(PermissionError, match="installed SENTRA"):
        publish_component(source, target, "demo.exe")
    assert (target / "demo.exe").read_bytes() == b"installed"


def test_manifest_covers_installed_dependency_bytes_and_detects_tampering(tmp_path):
    from sentra_remote.installer_preflight import write_payload_manifest, inspect_payload
    source = bundle(tmp_path / "payload")
    extension, docs = tmp_path / "extension", tmp_path / "docs"
    extension.mkdir(); docs.mkdir()
    manifest = write_payload_manifest(source, extension, docs, "1.0.3", ("demo.exe",))
    value = json.loads(manifest.read_text())
    assert "payload/_runtime_demo/python312.dll" in value["files"]
    (source / "_runtime_demo/driver.dat").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        inspect_payload(source, extension, docs, ("demo.exe",), version="1.0.3")


def test_native_setup_update_arguments_preserve_spaces_and_handoff(tmp_path, monkeypatch):
    from sentra_remote import installer_engine
    monkeypatch.setattr(installer_engine, "original_filename", lambda _: "SENTRA-Inno-Setup.exe")
    command = installer_engine.install_command(tmp_path / "Setup.exe", ["--silent", "--upgrade", "--no-git",
        "--no-launch", "--install-dir", "C:/App With Spaces/SENTRA", "--offline-handoff", "C:/State/my handoff.json"])
    assert "/VERYSILENT" in command and "/NO-LAUNCH" in command
    assert "/DIR=C:/App With Spaces/SENTRA" in command
    assert "/SENTRA-HANDOFF=C:/State/my handoff.json" in command
    assert "--silent" not in command
    monkeypatch.setattr(installer_engine, "original_filename", lambda _: "")
    assert installer_engine.install_command(Path("old.exe"), ["--silent"]) == ["old.exe", "--silent"]


def test_inno_compiler_version_uses_version_command_not_help_banner(tmp_path, monkeypatch):
    from scripts.commander import inno_setup
    calls = []
    def compile_fixture(command, **kwargs):
        calls.append(command)
        if command[-1] == "--version":
            return Mock(returncode=0, stdout="7.1.0\n", stderr="")
        (tmp_path / "output/SENTRA-Setup.exe").write_bytes(b"compile fixture; never executable")
        return Mock(returncode=0)
    monkeypatch.setattr(inno_setup.subprocess, "run", compile_fixture)
    result = inno_setup.build_inno(tmp_path / "bundle", tmp_path / "output", "1.0.3", compiler=Path("ISCC.exe"))
    assert result.is_file() and calls[0] == ["ISCC.exe", "--version"]
    assert json.loads((tmp_path / "output/setup-engine.json").read_text())["engine_version"] == "7.1.0"


@pytest.mark.parametrize("version,code", [("7.1.1\n", 0), ("Inno Setup 7\n", 0), ("7.1.0\n", 1)])
def test_inno_rejects_wrong_or_unavailable_compiler_before_compilation(tmp_path, monkeypatch, version, code):
    from scripts.commander import inno_setup
    run = Mock(return_value=Mock(returncode=code, stdout=version, stderr=""))
    monkeypatch.setattr(inno_setup.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="compiler version mismatch"):
        inno_setup.build_inno(tmp_path / "bundle", tmp_path / "output", "1.0.3", compiler=Path("ISCC.exe"))
    assert run.call_count == 1 and not (tmp_path / "output").exists()


def test_update_archive_contains_helper_support_files(tmp_path):
    from scripts.commander.release_assets import build_update_zip
    stage = tmp_path / "stage"; stage.mkdir()
    for name in ("SENTRA-Setup.exe", "sentra-update-helper.exe", "tunnel-client-v0.0.14-windows-amd64.zip"):
        (stage / name).write_bytes(b"fixture")
    runtime = stage / support_name("sentra-update-helper.exe"); runtime.mkdir()
    (runtime / "python312.dll").write_bytes(b"python")
    with zipfile.ZipFile(build_update_zip(stage, tmp_path / "update.zip")) as archive:
        assert "_runtime_sentra-update-helper/python312.dll" in archive.namelist()


def test_native_installer_local_completion_does_not_require_web_account(tmp_path, monkeypatch):
    from sentra_remote import installer
    operation = Mock(return_value={"tunnel_required": False, "connect_verify": {"core_ready": True,
        "status": {"mcp": {"ok": True}, "tunnel": {"ok": False}}, "chatgpt_onboarding": {"ready": False}}})
    monkeypatch.setattr(installer, "install", operation)
    assert installer.main(["--silent", "--local-only", "--install-dir", str(tmp_path), "--state-dir", str(tmp_path / "state"), "--no-launch"]) == 0
    assert operation.call_args.kwargs["local_only"] is True
    receipt = json.loads((tmp_path / "state/installer-last-run.json").read_text())
    assert receipt["ready"] is True and receipt["account_authorization_verified"] is False


@pytest.mark.skipif(__import__("os").name != "nt", reason="Win32 long paths")
def test_dependency_copy_and_manifest_keep_long_playwright_paths(tmp_path):
    from sentra_remote.windows_paths import filesystem_path
    source = bundle(tmp_path / "source")
    relative = Path("_runtime_demo/playwright/driver/package")
    relative = relative.joinpath(*["deep-driver-segment-123456" for _ in range(7)], "fixture.js")
    deep = Path(filesystem_path(source / relative))
    deep.parent.mkdir(parents=True)
    deep.write_bytes(b"deep-playwright-resource")
    target = tmp_path / "installed"
    assert len(str(target / relative)) > 260
    assert relative.as_posix() in copy_support(source, target, "demo.exe")
    assert Path(filesystem_path(target / relative)).read_bytes() == b"deep-playwright-resource"
    assert support_inventory(source, ("demo.exe",)) == support_inventory(target, ("demo.exe",))
