from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest
import yaml

from sentra_mcp.config import PROJECT_ROOT
from sentra_mcp.models import SERVER_VERSION
from sentra_remote.updater import _safe_extract, is_newer_version, prepare_update


def test_server_json_version_schema_and_description() -> None:
    data = json.loads((PROJECT_ROOT / "server.json").read_text(encoding="utf-8"))
    assert data["version"] == SERVER_VERSION
    assert data["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert len(data["description"]) <= 100
    assert re.fullmatch(r"[A-Za-z0-9.-]+/[A-Za-z0-9._-]+", data["name"])


def test_registry_renderer_adds_repository_and_remote(tmp_path: Path) -> None:
    output = tmp_path / "server.release.json"
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "commander" / "render_server_json.py"),
            "--input",
            str(PROJECT_ROOT / "server.json"),
            "--output",
            str(output),
            "--name",
            "io.github.example/sentra-commander",
            "--version",
            SERVER_VERSION,
            "--remote-url",
            "https://mcp.example.test/mcp",
            "--repository-url",
            "https://github.com/example/sentra",
        ],
        check=True,
        cwd=PROJECT_ROOT,
    )
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["version"] == SERVER_VERSION
    assert data["repository"] == {
        "url": "https://github.com/example/sentra",
        "source": "github",
    }
    assert data["remotes"] == [
        {"type": "streamable-http", "url": "https://mcp.example.test/mcp"}
    ]


def test_release_and_compose_yaml_parse_and_cloud_mode() -> None:
    desktop_workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "release-commander.yml").read_text(encoding="utf-8")
    )
    registry_workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "release-mcp-registry.yml").read_text(encoding="utf-8")
    )
    assert isinstance(desktop_workflow, dict)
    assert "windows-release" in desktop_workflow["jobs"]
    assert isinstance(registry_workflow, dict)
    assert "validate-and-publish-registry" in registry_workflow["jobs"]

    compose = yaml.safe_load(
        (PROJECT_ROOT / "deploy" / "commander" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    cloud_command = compose["services"]["cloud-mcp"]["command"]
    assert "--mode" in cloud_command
    assert cloud_command[cloud_command.index("--mode") + 1] == "cloud"
    assert compose["services"]["cloud-mcp"]["ports"] == ["127.0.0.1:8000:8000"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell syntax validation is Windows-specific")
def test_windows_installer_scripts_parse() -> None:
    for relative in ("installer/windows/install.ps1", "installer/windows/uninstall.ps1"):
        script = PROJECT_ROOT / relative
        command = (
            "$tokens=$null;$errors=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{str(script).replace("'", "''")}',"
            "[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], check=True)


def test_semver_update_ordering() -> None:
    assert is_newer_version("3.0.1", "3.0.0") is True
    assert is_newer_version("4.0.0", "3.9.9") is True
    assert is_newer_version("3.0.0", "3.0.0") is False
    assert is_newer_version("2.9.9", "3.0.0") is False
    assert is_newer_version("3.0.0", "3.0.0-rc.1") is True
    with pytest.raises(ValueError):
        is_newer_version("not-a-version", "3.0.0")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return


def _serve_directory(path: Path):
    handler = functools.partial(_QuietHandler, directory=str(path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _make_update_fixture(root: Path, *, unsafe: bool = False) -> tuple[Path, str]:
    package = root / "package.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if unsafe:
            archive.writestr("../escape.txt", "blocked")
        else:
            archive.writestr("install.ps1", "Write-Host 'ok'\n")
            archive.writestr("sentra-agent.exe", b"fake-exe")
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    return package, digest


def test_prepare_update_verifies_hash_and_extracts(tmp_path: Path) -> None:
    package, digest = _make_update_fixture(tmp_path)
    manifest = {
        "version": "3.0.1",
        "url": "",
        "sha256": digest,
        "signer_thumbprint": "",
    }
    manifest_path = tmp_path / "manifest.json"
    server, thread = _serve_directory(tmp_path)
    try:
        manifest["url"] = f"http://127.0.0.1:{server.server_port}/{package.name}"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        prepared = prepare_update(
            f"http://127.0.0.1:{server.server_port}/{manifest_path.name}",
            tmp_path / "work",
            require_signature=False,
        )
        assert prepared["version"] == "3.0.1"
        assert Path(prepared["installer"]).is_file()
        assert (Path(prepared["package_root"]) / "sentra-agent.exe").is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_prepare_update_rejects_bad_hash_and_unsigned_auto_update(tmp_path: Path) -> None:
    package, digest = _make_update_fixture(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    server, thread = _serve_directory(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        manifest_path.write_text(json.dumps({
            "version": "3.0.1",
            "url": f"{base}/{package.name}",
            "sha256": "0" * 64,
            "signer_thumbprint": "",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="sha256 mismatch"):
            prepare_update(f"{base}/{manifest_path.name}", tmp_path / "bad-hash")

        manifest_path.write_text(json.dumps({
            "version": "3.0.1",
            "url": f"{base}/{package.name}",
            "sha256": digest,
            "signer_thumbprint": "",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="requires an Authenticode"):
            prepare_update(
                f"{base}/{manifest_path.name}",
                tmp_path / "unsigned",
                require_signature=True,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_update_zip_traversal_is_blocked(tmp_path: Path) -> None:
    archive, _ = _make_update_fixture(tmp_path, unsafe=True)
    destination = tmp_path / "extract"
    destination.mkdir()
    with pytest.raises(ValueError, match="unsafe path"):
        _safe_extract(archive, destination)
    assert not (tmp_path / "escape.txt").exists()



@pytest.mark.skipif(os.name != "nt", reason="Windows installer roundtrip is Windows-specific")
def test_windows_installer_no_startup_roundtrip(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    install_dir = tmp_path / "installed"
    profile = tmp_path / "profile"
    bundle.mkdir()
    profile.mkdir()
    for name in ("sentra-agent.exe", "sentra-tray.exe", "sentra-diagnostics.exe"):
        (bundle / name).write_bytes(b"MZ-test-binary")
    for name in ("install.ps1", "uninstall.ps1"):
        (bundle / name).write_bytes((PROJECT_ROOT / "installer" / "windows" / name).read_bytes())

    env = os.environ.copy()
    env["USERPROFILE"] = str(profile)
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(bundle / "install.ps1"),
            "-InstallDir", str(install_dir),
            "-NoStartup",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )
    for name in ("sentra-agent.exe", "sentra-tray.exe", "sentra-diagnostics.exe"):
        assert (install_dir / name).is_file()

    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(bundle / "uninstall.ps1"),
            "-InstallDir", str(install_dir),
            "-NoStartupCleanup",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )
    assert not install_dir.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows startup registration is Windows-specific")
def test_windows_startup_registration_and_cleanup(tmp_path: Path) -> None:
    import uuid

    bundle = tmp_path / "bundle"
    install_dir = tmp_path / "installed"
    bundle.mkdir()
    for name in ("sentra-agent.exe", "sentra-tray.exe", "sentra-diagnostics.exe"):
        (bundle / name).write_bytes(b"MZ-test-binary")
    for name in ("install.ps1", "uninstall.ps1"):
        (bundle / name).write_bytes((PROJECT_ROOT / "installer" / "windows" / name).read_bytes())

    suffix = uuid.uuid4().hex[:10]
    task_name = f"SENTRA Commander E2E {suffix}"
    startup_file = f"SENTRA-Commander-E2E-{suffix}.cmd"
    startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_path = startup_dir / startup_file

    try:
        subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(bundle / "install.ps1"),
                "-InstallDir", str(install_dir),
                "-NoLaunch",
                "-TaskName", task_name,
                "-StartupFileName", startup_file,
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )
        task_probe = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                f"$t=Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue;"
                "if($t){exit 0}else{exit 1}",
            ],
            check=False,
        )
        assert task_probe.returncode == 0 or startup_path.is_file()

        subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(bundle / "uninstall.ps1"),
                "-InstallDir", str(install_dir),
                "-KeepConfig",
                "-TaskName", task_name,
                "-StartupFileName", startup_file,
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )
        assert not install_dir.exists()
        task_probe = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                f"$t=Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue;"
                "if($t){exit 1}else{exit 0}",
            ],
            check=False,
        )
        assert task_probe.returncode == 0
        assert not startup_path.exists()
    finally:
        subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                f"Unregister-ScheduledTask -TaskName '{task_name}' -Confirm:$false -ErrorAction SilentlyContinue",
            ],
            check=False,
        )
        startup_path.unlink(missing_ok=True)


def test_release_workflow_uses_clean_declared_build_surface() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "release-commander.yml").read_text(encoding="utf-8")
    builder = (PROJECT_ROOT / "scripts" / "commander" / "build_windows.py").read_text(encoding="utf-8")
    assert "python -m pip install -r requirements.txt -r requirements-commander.txt" in workflow
    assert "python -B -m pytest tests -q" in workflow
    assert "python scripts/commander/build_windows.py" in workflow
    assert "scripts/commander/release_assets.py" in workflow
    assert "SENTRA-Setup-" in workflow
    assert "SENTRA-Desktop-*-x64.msi" in workflow
    assert "SENTRA_SIGNER_THUMBPRINT" in workflow
    assert "Stable release requires WINDOWS_CERTIFICATE_B64" in workflow
    assert "784ab8da7b5a88f0109f1fd8aaf0a1c86067430b896dddf307ef7e3cc49fa1a5" in workflow
    assert "WINDOWS_CERTIFICATE_B64" in workflow
    assert '"--collect-all", "playwright"' in builder
    assert '"--hidden-import", "pyarrow.parquet"' in builder
    assert "collect-all pyarrow" not in builder
    assert "collect-all mcp" not in builder
    for module in ("torch", "scipy", "pandas", "sklearn", "pygame"):
        assert f'"{module}"' in builder
