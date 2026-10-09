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
from sentra_remote.updater import _safe_extract, is_newer_version, prepare_update, verify_authenticode


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


def test_verify_authenticode_quotes_powershell_literal_paths(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    def fake_run(args, **_kwargs):
        seen.append(str(args[-1]))
        return type("Result", (), {
            "stdout": '{"Status":"Valid","Thumbprint":"ABC123"}'
        })()

    monkeypatch.setattr("sentra_remote.updater.subprocess.run", fake_run)
    verify_authenticode(tmp_path / "O'Brien" / "sentra.exe", "ABC123")

    assert seen
    assert "O''Brien" in seen[0]
    assert "-LiteralPath '" in seen[0]


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


def test_python_lock_is_hash_pinned_and_matches_local_artifacts_when_available() -> None:
    from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename

    entries: dict[tuple[str, str], str] = {}
    for raw in (PROJECT_ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)==([^\\s]+) --hash=sha256:([0-9a-f]{64})",
            line,
        )
        assert match, f"unhashed or malformed lock entry: {line}"
        key = (canonicalize_name(match.group(1)), match.group(2))
        assert key not in entries
        entries[key] = match.group(3)

    assert len(entries) >= 70

    artifact_dir = PROJECT_ROOT / ".tmp" / "python-lock-artifacts"
    if not artifact_dir.is_dir():
        return

    artifacts: dict[tuple[str, str], Path] = {}
    for artifact in artifact_dir.iterdir():
        if artifact.suffix == ".whl":
            name, version, _build, _tags = parse_wheel_filename(artifact.name)
        elif artifact.name.endswith((".tar.gz", ".zip")):
            name, version = parse_sdist_filename(artifact.name)
        else:
            continue
        key = (canonicalize_name(str(name)), str(version))
        assert key not in artifacts, f"multiple selected artifacts for {key}"
        artifacts[key] = artifact

    assert set(artifacts) == set(entries)
    for key, artifact in artifacts.items():
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == entries[key], artifact.name


def test_release_workflow_uses_clean_declared_build_surface() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "release-commander.yml").read_text(encoding="utf-8")
    builder = (PROJECT_ROOT / "scripts" / "commander" / "build_windows.py").read_text(encoding="utf-8")
    assert "python -m pip install --require-hashes -r requirements.lock.txt" in workflow
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


@pytest.mark.skipif(os.name != "nt", reason="MSI identifier rules are Windows-specific")
def test_msi_identifier_generation_is_bounded_and_collision_resistant() -> None:
    from scripts.commander.build_msi import (
        MSI_IDENTIFIER_MAX,
        _component_id,
        _directory_id,
    )

    shared_tail = ("node_modules", "zod", "src", "v4", "mini")
    first = Path("web-models", "win-unpacked", "resources", "runtime", "app", *shared_tail)
    second = Path("web-models", "win-unpacked", "resources", "runtime", "other", *shared_tail)

    identifiers = [
        _component_id(first),
        _component_id(second),
        _directory_id(first),
        _directory_id(second),
    ]

    assert all(len(identifier) <= MSI_IDENTIFIER_MAX for identifier in identifiers)
    assert len(set(identifiers)) == len(identifiers)
    assert _component_id(first) == identifiers[0]
    assert _directory_id(first) == identifiers[2]


def test_web_models_build_times_out_and_terminates_tree(monkeypatch, tmp_path: Path) -> None:
    from scripts.commander import build_windows

    class FakeProcess:
        pid = 5151
        def __init__(self):
            self.wait_calls = 0
            self.killed = False
        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(["powershell"], timeout)
            return -9
        def poll(self):
            return None
        def kill(self):
            self.killed = True

    proc = FakeProcess()
    monkeypatch.setattr(build_windows.shutil, "which", lambda name: "powershell.exe" if name == "powershell" else None)
    monkeypatch.setattr(
        build_windows,
        "BUILD_STATUS_PATH",
        tmp_path / ".tmp" / "web-models-build-status.json",
    )
    monkeypatch.setattr(build_windows.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        build_windows.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )

    with pytest.raises(RuntimeError, match="Web Models build timed out after 600s"):
        build_windows.build_web_models(tmp_path / "dist")

    assert proc.wait_calls >= 2
    assert build_windows.WEB_MODELS_TIMEOUT_S == 600


def test_windows_builder_avoids_per_binary_global_clean_and_isolates_cache(tmp_path: Path) -> None:
    from scripts.commander import build_windows

    args = build_windows._common(
        "sentra-test",
        tmp_path / "entry.py",
        tmp_path / "dist",
        tmp_path / "work",
        tmp_path / "spec",
    )
    assert "--clean" not in args
    assert args[:2] == ["--noconfirm", "--onefile"]


def test_windows_builder_fails_closed_and_terminates_pyinstaller_tree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scripts.commander import build_windows

    class FakeProcess:
        pid = 4242

        def __init__(self) -> None:
            self.wait_calls = 0
            self.killed = False

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(["pyinstaller"], timeout)
            return -9

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    proc = FakeProcess()
    taskkill_calls = []
    monkeypatch.setattr(
        build_windows,
        "BUILD_STATUS_PATH",
        tmp_path / ".tmp" / "pyinstaller-build-status.json",
    )

    popen_calls = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return proc

    monkeypatch.setattr(build_windows.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        build_windows.subprocess,
        "run",
        lambda *args, **kwargs: taskkill_calls.append(args[0])
        or subprocess.CompletedProcess(args[0], 0),
    )

    with pytest.raises(RuntimeError, match="PyInstaller timed out after 7s"):
        build_windows._run(["--name", "sentra-test"], timeout_s=7)

    if os.name == "nt":
        assert taskkill_calls == [["taskkill", "/PID", "4242", "/T", "/F"]]
    else:
        assert proc.killed is True
    assert proc.wait_calls >= 2
    assert build_windows.PYINSTALLER_TIMEOUT_S == 600
    assert build_windows.UPDATE_HELPER_TIMEOUT_S == 600
    assert popen_calls
    _, popen_kwargs = popen_calls[0]
    cache_dir = Path(popen_kwargs["env"]["PYINSTALLER_CONFIG_DIR"])
    assert cache_dir.name == "sentra-test"
    assert cache_dir.parent.name == "pyinstaller-config"
    assert cache_dir.is_relative_to(build_windows.LOCAL_BUILD_ROOT)


def test_payload_build_probes_update_helper_first(monkeypatch, tmp_path: Path) -> None:
    from scripts.commander import build_windows

    calls = []

    def fake_build(name, entry_name, dist, work, spec, **kwargs):
        calls.append((name, kwargs.get("timeout_s")))
        output = Path(dist)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{name}.exe").write_text(name, encoding="utf-8")

    monkeypatch.setattr(build_windows, "_build", fake_build)
    monkeypatch.setattr(build_windows, "_publish_payload", lambda staging, dist: None)

    build_windows.build_payload(
        tmp_path / "dist",
        tmp_path / "work",
        tmp_path / "spec",
    )

    assert calls[0] == ("sentra-update-helper", 600)
    assert [name for name, _ in calls].count("sentra-update-helper") == 1


def test_payload_publish_rolls_back_if_target_becomes_locked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.commander import build_windows

    dist = tmp_path / "dist"
    staging = tmp_path / "staging"
    dist.mkdir()
    staging.mkdir()
    for name in build_windows.PAYLOAD_NAMES:
        (dist / name).write_text("old-" + name, encoding="utf-8")
        (staging / name).write_text("new-" + name, encoding="utf-8")

    real_replace = build_windows.os.replace

    def guarded_replace(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        if (
            src_path.parent == staging
            and dst_path.name == "sentra-browser-relay.exe"
        ):
            raise PermissionError("simulated locked relay")
        return real_replace(src, dst)

    monkeypatch.setattr(build_windows.os, "replace", guarded_replace)

    with pytest.raises(RuntimeError, match="previous payload was restored"):
        build_windows._publish_payload(staging, dist)

    for name in build_windows.PAYLOAD_NAMES:
        assert (dist / name).read_text(encoding="utf-8") == "old-" + name


def test_payload_replaceability_preflight_preserves_dist_when_locked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.commander import build_windows

    dist = tmp_path / "dist"
    dist.mkdir()
    for name in build_windows.PAYLOAD_NAMES:
        (dist / name).write_text("old-" + name, encoding="utf-8")

    real_replace = build_windows.os.replace

    def guarded_replace(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        if (
            src_path.name == "sentra-browser-relay.exe"
            and ".sentra-build-probe-" in dst_path.name
        ):
            raise PermissionError("simulated locked relay")
        return real_replace(src, dst)

    monkeypatch.setattr(build_windows.os, "replace", guarded_replace)

    with pytest.raises(RuntimeError, match="running SENTRA executable"):
        build_windows._assert_payload_replaceable(dist)

    for name in build_windows.PAYLOAD_NAMES:
        assert (dist / name).read_text(encoding="utf-8") == "old-" + name


def test_clean_build_outputs_preserves_last_published_dist(tmp_path: Path) -> None:
    from scripts.commander import build_windows

    dist = tmp_path / "dist"
    work = tmp_path / "work"
    spec = tmp_path / "spec"
    dist.mkdir()
    work.mkdir()
    spec.mkdir()
    published = dist / "sentra-agent.exe"
    published.write_text("published", encoding="utf-8")
    (work / "temp.txt").write_text("work", encoding="utf-8")
    (spec / "temp.spec").write_text("spec", encoding="utf-8")

    build_windows._clean_build_outputs(dist, work, spec, "all")

    assert published.read_text(encoding="utf-8") == "published"
    assert not work.exists()
    assert not spec.exists()


def test_build_status_is_persisted_outside_private_lock(tmp_path: Path, monkeypatch) -> None:
    from scripts.commander import build_windows

    status_path = tmp_path / ".tmp" / "build-windows-status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(
        json.dumps({
            "state": "FAILED",
            "finished_at": 122.0,
            "duration_s": 99.0,
            "error": "stale failure",
            "reason": "stale reason",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_windows, "BUILD_STATUS_PATH", status_path)

    build_windows._update_build_status(
        state="RUNNING",
        phase="payload",
        step="sentra-mcp",
        started_at=123.0,
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["state"] == "RUNNING"
    assert payload["phase"] == "payload"
    assert payload["step"] == "sentra-mcp"
    assert payload["pid"] == os.getpid()
    assert payload["updated_at"] >= 123.0
    assert payload["finished_at"] is None
    assert payload["duration_s"] is None
    assert payload["error"] is None
    assert payload["reason"] is None


def test_windows_build_lock_rejects_concurrent_invocation(tmp_path: Path) -> None:
    from scripts.commander import build_windows

    lock_path = tmp_path / ".sentra" / "build-windows.lock"
    with build_windows._BuildLock(lock_path):
        with pytest.raises(RuntimeError, match="another SENTRA Windows build is already running"):
            with build_windows._BuildLock(lock_path):
                pass


def test_clean_build_outputs_removes_only_stale_staging_and_transient_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts.commander import build_windows

    local_build = tmp_path / "local-build"
    local_build.mkdir()
    monkeypatch.setattr(build_windows, "LOCAL_BUILD_ROOT", local_build)

    stale_local = local_build / "payload-99999999"
    stale_local.mkdir()
    live_local = local_build / f"payload-{os.getpid()}"
    live_local.mkdir()

    dist = tmp_path / "dist"
    work = tmp_path / "build"
    spec = tmp_path / "spec"
    dist.mkdir()
    work.mkdir()
    spec.mkdir()
    for name in build_windows.PAYLOAD_NAMES:
        (dist / name).write_text("published", encoding="utf-8")
    stale = tmp_path / "dist.payload-staging-123"
    stale.mkdir()
    (stale / "partial.exe").write_text("partial", encoding="utf-8")

    build_windows._clean_build_outputs(dist, work, spec, "payload")

    assert dist.is_dir()
    for name in build_windows.PAYLOAD_NAMES:
        assert (dist / name).read_text(encoding="utf-8") == "published"
    assert not work.exists()
    assert not spec.exists()
    assert not stale.exists()
    assert not stale_local.exists()
    assert live_local.is_dir()

def test_sentra_cli_is_part_of_windows_release_payload() -> None:
    from scripts.commander import build_windows
    from sentra_remote.installer import PRODUCTS

    root = Path(__file__).resolve().parents[2]
    assert "sentra-cli.exe" in build_windows.PAYLOAD_NAMES
    assert "sentra-cli.exe" in build_windows.EXPECTED
    assert "sentra-cli.exe" in PRODUCTS

    entry = root / "scripts" / "commander" / "cli_entry.py"
    assert entry.is_file()
    assert "sentra_cli.__main__" in entry.read_text(encoding="utf-8")

    msi_source = (
        root / "scripts" / "commander" / "build_msi.py"
    ).read_text(encoding="utf-8")
    assert '"sentra-cli.exe"' in msi_source

def test_cli_phase_builds_config_and_publishes_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts.commander import build_windows

    captured = {}
    def fake_build(name, entry_name, dist, work, spec, **kwargs):
        captured['name'] = name
        captured['entry'] = entry_name
        captured['extra'] = kwargs.get('extra') or []
        output = Path(dist)
        output.mkdir(parents=True, exist_ok=True)
        (output / 'sentra-cli.exe').write_bytes(b'new-cli')

    def fake_publish(staged, target):
        captured['staged'] = Path(staged)
        captured['target'] = Path(target)

    monkeypatch.setattr(build_windows, '_build', fake_build)
    monkeypatch.setattr(
        build_windows, '_publish_single_executable', fake_publish
    )
    monkeypatch.setattr(
        build_windows, 'LOCAL_BUILD_ROOT', tmp_path / 'local-build'
    )

    dist = tmp_path / 'dist'
    build_windows.build_cli(dist, tmp_path / 'work', tmp_path / 'spec')

    assert captured['name'] == 'sentra-cli'
    assert captured['entry'] == 'cli_entry.py'
    add_data = ' '.join(map(str, captured['extra']))
    assert '--add-data' in captured['extra']
    assert 'config.yaml' in add_data
    assert captured['target'] == dist / 'sentra-cli.exe'


def test_single_executable_publish_replaces_target(tmp_path: Path) -> None:
    from scripts.commander import build_windows

    staged = tmp_path / 'staged.exe'
    target = tmp_path / 'dist' / 'sentra-cli.exe'
    target.parent.mkdir()
    staged.write_bytes(b'new')
    target.write_bytes(b'old')

    build_windows._publish_single_executable(staged, target)

    assert target.read_bytes() == b'new'
    assert not list(target.parent.glob('.sentra-cli.exe.*'))

def test_release_assets_lock_and_isolated_staging_contract(tmp_path: Path) -> None:
    from scripts.commander import release_assets

    lock_path = tmp_path / ".sentra" / "release-assets.lock"
    with release_assets._BuildLock(
        lock_path,
        description="release asset build",
    ):
        with pytest.raises(
            RuntimeError,
            match="another SENTRA release asset build is already running",
        ):
            with release_assets._BuildLock(
                lock_path,
                description="release asset build",
            ):
                pass

    source = Path(release_assets.__file__).read_text(encoding="utf-8")
    assert 'release-assets.lock' in source
    assert 'sentra-release-staging-' in source
    assert 'sentra-release-artifacts-' in source

def test_msi_registers_sentra_install_dir_on_user_path() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "commander"
        / "build_msi.py"
    ).read_text(encoding="utf-8")
    assert 'add_data(db, "Environment"' in source
    assert '"SENTRA_User_Path"' in source
    assert '"=-Path"' in source
    assert '"[~];[INSTALLDIR]"' in source
