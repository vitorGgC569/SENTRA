"""Build Windows SENTRA Desktop executables and self-contained setup."""
from __future__ import annotations

import argparse
from contextvars import ContextVar
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "").strip()
_BUILD_ROOT_OVERRIDE = os.environ.get("SENTRA_BUILD_ROOT", "").strip()
LOCAL_BUILD_ROOT = (
    Path(_BUILD_ROOT_OVERRIDE).expanduser().resolve() if _BUILD_ROOT_OVERRIDE else
    Path(_LOCALAPPDATA) / "SENTRA" / "Build" / "commander"
    if _LOCALAPPDATA
    else ROOT / ".tmp" / "local-build" / "commander"
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BUILD_STATUS_PATH = ROOT / ".tmp" / "build-windows-status.json"
_RUNTIME_BINDING = ContextVar('sentra_build_runtime_binding', default=None)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class _RuntimeBinding:
    """One final-build selection, shared across isolated payload output paths."""
    def __init__(self, staging, *, required=False):
        self.staging, self.required = Path(staging), required
        self.token = self.directory = None

    def __enter__(self):
        if not (self.staging / 'runtime-components.json').is_file():
            if self.required:
                raise RuntimeError('materialize integral runtime components before building release payload')
            self.token = _RUNTIME_BINDING.set(None)
            return self
        from scripts.commander.runtime_bindings import write_runtime_pins
        LOCAL_BUILD_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='runtime-binding-', dir=LOCAL_BUILD_ROOT))
        try:
            self.record = write_runtime_pins(self.staging, self.directory)
            self.record['staging'] = str(self.staging.resolve(strict=True))
        except BaseException:
            self._cleanup(); raise
        self.token = _RUNTIME_BINDING.set(self.record)
        return self

    def _cleanup(self):
        if self.directory is not None:
            (self.directory / 'sentra-runtime-pins.json').unlink(missing_ok=True)
            self.directory.rmdir()

    def __exit__(self, *_):
        if self.token is not None:
            _RUNTIME_BINDING.reset(self.token)
        self._cleanup()


def _source_fingerprint(root: Path | None = None) -> dict[str, str]:
    """Record product inputs only, excluding private state and generated caches."""
    root = ROOT if root is None else Path(root)
    folders = (
        "browser", "integrations", "native_bridge", "orchestrator", "repository",
        "sentra_core", "sentra_mcp", "sentra_model_gateway", "sentra_remote",
        "sentra_cli", "sentra_canvas", "sentra_runtime", "sentra_executors", "sentra_code_mode",
        "sentra_interop", "sentra_collab", "sentra_quality", "sentra_connectors", "workspace",
        "sentra_federation", "sentra_marketplace", "memory", "local_model", "skills/optional_connectors",
        "scripts/commander", "scripts/integrations", "edge_extension", "sentra_electron",
    )
    # React desktop sources are JSX today; TS/TSX/SVG inputs must also invalidate
    # an old payload proof when the UI source changes without a bundle rebuild.
    # The pinned Web Models patch is a product input just like its PowerShell
    # builder; both must invalidate provenance before a new Setup is accepted.
    # Packaged license/notice text is part of the distributed artifact too.
    extensions = {".py", ".js", ".jsx", ".cjs", ".ts", ".tsx", ".svg", ".css", ".html", ".json", ".ps1", ".cmd", ".yaml", ".yml", ".ico", ".png", ".patch", ".txt", ".md", ".c", ".cs", ".h", ".go", ".mod", ".sum", ".sh", ".wasm", ".rs", ".toml", ".lock", ".mjs", ".xpi"}
    files = {root / name for name in (
        "main.py", "sentra_version.py", "config.yaml", "requirements.lock.txt", "LICENSE",
        "README.md", "SECURITY.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md",
        # These extensionless notices are mandatory inputs of mobile staging
        # and the terminal engine seal, including in isolated source snapshots.
        "vendor/orca/LICENSE", "integrations/orca-terminal/vendor/orca/LICENSE",
        # These generated, sealed inputs are shipped by stage_terminal_runtime.
        # Arbitrary dist/cache trees stay excluded from the snapshot.
        "integrations/orca-terminal/dist/engine.cjs",
        "integrations/orca-terminal/dist/manifest.json",
    )}
    # The Setup bundles this onboarding guide, while the vendored xterm
    # licenses have no suffix and would otherwise be missed by the scan.
    files.update(root / name for name in (
        "docs/SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md",
        "sentra_canvas/static/vendor/addon-fit-LICENSE",
        "sentra_canvas/static/vendor/xterm-LICENSE",
    ))
    # Brand PNGs are packaged inputs; excluding them would let an outdated
    # payload proof pass after a logo change without rebuilding the EXEs.
    files.update(root / name for name in (
        "sentra_canvas/assets/SENTRA-LOGO.png",
        "sentra_canvas/static/sentra-logo.png",
    ))
    # The Setup embeds the ENTIRE docs/ tree via --add-data, not just the
    # onboarding guide. Track nested screenshots, videos, JSON and every
    # other distributed file regardless of suffix to prevent stale proofs.
    # These data trees are passed whole to PyInstaller/staging. Track every
    # byte, including extensionless legal files, fonts and media, rather than
    # only the suffixes used for source modules below.
    data_trees = (
        "docs", "sentra_canvas/assets", "sentra_canvas/static",
        # The desktop source seal covers every src/public byte, including
        # extensionless upstream licenses and future font/media formats.
        "sentra_canvas/desktop_ui/src", "sentra_canvas/desktop_ui/public", "sentra_remote/human_ui",
        "sentra_remote/provider_notices", "edge_extension",
        "sentra_code_mode/guest/licenses",
    )
    for name in data_trees:
        files.update(path for path in (root / name).rglob("*") if path.is_file())
    for folder in folders:
        files.update(path for path in (root / folder).rglob("*")
                     if path.is_file() and path.suffix.lower() in extensions
                     and not {"__pycache__", "node_modules", ".tmp", "dist", "build"}.intersection(path.relative_to(root).parts))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files) if path.is_file()}


def _write_build_provenance(dist: Path, phase: str, expected: tuple[str, ...], sources: dict[str, str]) -> None:
    current = _source_fingerprint()
    if current != sources:
        changed = sorted(name for name in set(current) | set(sources) if current.get(name) != sources.get(name))
        raise RuntimeError("product source changed during build; rebuild before release: " + ", ".join(changed[:10]))
    result = {
        "schema_version": 1, "phase": phase, "python": sys.version.split()[0],
        "sources": sources,
        "executables": {name: {"sha256": _file_sha256(dist / name),
                               "bytes": (dist / name).stat().st_size} for name in expected},
    }
    binding = _RUNTIME_BINDING.get()
    if binding is not None:
        if hashlib.sha256(Path(binding['path']).read_bytes()).hexdigest() != binding['sha256']:
            raise PermissionError('embedded runtime pin input changed during build')
        from scripts.commander.runtime_bindings import runtime_pins
        current = (json.dumps(runtime_pins(Path(binding['staging'])), sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
        if hashlib.sha256(current).hexdigest() != binding['sha256']:
            raise PermissionError('selected runtime components changed during build')
        result['runtime_pins_sha256'] = binding['sha256']
    seal = ROOT / "source-snapshot.json"
    if seal.is_file():
        from scripts.commander.source_snapshot import verify_source_snapshot
        verify_source_snapshot(ROOT)
        result["source_snapshot_sha256"] = hashlib.sha256(seal.read_bytes()).hexdigest()
    path = dist / ("build-provenance-" + phase + ".json")
    staged = path.with_suffix(".tmp")
    staged.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.replace(staged, path)


def _update_build_status(**changes: object) -> None:
    BUILD_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(BUILD_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if changes.get("state") == "RUNNING":
        payload["finished_at"] = None
        payload["duration_s"] = None
        payload["error"] = None
        if "reason" not in changes:
            payload["reason"] = None
    payload.update(changes)
    payload["pid"] = os.getpid()
    payload["updated_at"] = time.time()
    temp = BUILD_STATUS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(BUILD_STATUS_PATH)


from scripts.commander.extension_identity import stage_extension_source


class _BuildLock:
    """OS-backed cross-process lock for Windows payload/release builds."""

    def __init__(self, path: Path, description: str = "Windows build") -> None:
        self.path = Path(path)
        self.description = str(description or "Windows build").strip()
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError(
                f"another SENTRA {self.description} is already running"
            ) from exc

        handle.seek(1)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self.handle = handle
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        handle = self.handle
        self.handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


DEFAULT_EXCLUDES = (
    "torch", "torchvision", "torchaudio", "scipy", "pandas", "numba",
    "sklearn", "matplotlib", "numpy", "pygame",
)


def _common(name: str, entry: Path, dist: Path, work: Path, spec: Path) -> list[str]:
    # The build already clears work/spec outputs once per phase. Re-running
    # PyInstaller's global --clean for every executable causes repeated cache
    # churn and can stall later Windows builds under endpoint scanning.
    args = [
        "--noconfirm", "--onefile",
        "--name", name,
        "--distpath", str(dist),
        "--workpath", str(work / name),
        "--specpath", str(spec),
        "--paths", str(ROOT),
    ]
    for module in DEFAULT_EXCLUDES:
        args += ["--exclude-module", module]
    args.append(str(entry))
    return args


PYINSTALLER_TIMEOUT_S = 600
SETUP_TIMEOUT_S = 1800  # Integral offline payloads exceed the small-EXE budget.
UPDATE_HELPER_TIMEOUT_S = 600
WEB_MODELS_TIMEOUT_S = 600


def _run_gui_check(command: list[str], label: str, *, frozen_required: bool) -> None:
    checks = LOCAL_BUILD_ROOT / "gui-checks"
    checks.mkdir(parents=True, exist_ok=True)
    report = checks / (label + ".json")
    report.unlink(missing_ok=True)
    args = [*command, "--gui-check", "--gui-check-report", str(report)] if frozen_required else [*command, "--report", str(report)]
    proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = proc.wait(timeout=180)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        raise RuntimeError("GUI runtime check timed out: " + label) from None
    result = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    required = ("ok", "tk_window_created", "ttk_widgets_created", "window_destroyed")
    if code != 0 or not all(result.get(key) is True for key in required) or (frozen_required and result.get("frozen") is not True):
        raise RuntimeError("GUI runtime is incomplete; Tcl/Tk window check failed: " + label)


def _verify_build_gui_runtime() -> None:
    _run_gui_check([sys.executable, "-m", "sentra_remote.gui_runtime"], "build-python", frozen_required=False)


def _verify_frozen_gui(executable: Path) -> None:
    _run_gui_check([str(executable)], executable.stem, frozen_required=True)


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            proc.kill()
    else:
        proc.kill()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=15)


def _run(args: list[str], *, timeout_s: int = PYINSTALLER_TIMEOUT_S) -> None:
    command = [sys.executable, "-m", "PyInstaller", *args]
    try:
        name = str(args[args.index("--name") + 1])
    except (ValueError, IndexError):
        name = "default"
    _update_build_status(state="RUNNING", step=name)
    cache_dir = LOCAL_BUILD_ROOT / "pyinstaller-config" / name
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(cache_dir)
    proc = subprocess.Popen(command, cwd=ROOT, env=env)
    try:
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(proc)
        raise RuntimeError(
            f"PyInstaller timed out after {timeout_s}s: "
            f"{' '.join(command[:4])}"
        ) from exc
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)

def _build(
    name: str,
    entry_name: str,
    dist: Path,
    work: Path,
    spec: Path,
    *,
    windowed: bool = False,
    mcp_payload: bool = False,
    extra: list[str] | None = None,
    timeout_s: int = PYINSTALLER_TIMEOUT_S,
) -> None:
    args = _common(name, ROOT / "scripts" / "commander" / entry_name, dist, work, spec)
    prefix: list[str] = []
    if windowed:
        prefix.append("--noconsole")
    if name in {"sentra-canvas", "sentra-desktop", "sentra-human", "SENTRA-Setup"}:
        icon_name = "SENTRA-DOT.ico"
        icon = ROOT / "sentra_canvas" / "assets" / icon_name
        if not icon.is_file():
            raise FileNotFoundError("official SENTRA icon is missing: " + str(icon))
        prefix += ["--icon", str(icon)]
        # The native WebView2 HWND and the system tray also need image bytes
        # at runtime; setting only the executable icon is not sufficient.
        prefix += ["--add-data", f"{ROOT / 'sentra_canvas' / 'assets'}{os.pathsep}sentra_canvas/assets"]
        if name == "SENTRA-Setup":
            prefix += ["--add-data", f"{ROOT / 'sentra_canvas/desktop_ui/src/assets/opendots/blue.png'}{os.pathsep}sentra_canvas/assets"]
    if mcp_payload:
        prefix += ["--collect-all", "playwright", "--hidden-import", "pyarrow.parquet"]
    elif name == "SENTRA-Setup":
        # Setup owns DOM enrollment, including the driver, on clean machines.
        prefix += ["--collect-all", "playwright"]
    if mcp_payload or name in {'sentra-canvas', 'sentra-cli', 'sentra-update-helper'}:
        from scripts.commander.runtime_dependencies import require_wasmtime_pin
        require_wasmtime_pin()
        prefix += ['--collect-all', 'wasmtime']
    if extra:
        prefix += extra
    binding = _RUNTIME_BINDING.get()
    if binding is not None:
        resource = Path(binding['path'])
        if hashlib.sha256(resource.read_bytes()).hexdigest() != binding['sha256']:
            raise PermissionError('embedded runtime pin input changed before build')
        prefix += ['--add-data', f'{resource}{os.pathsep}.']
    args[0:0] = prefix
    _run(args, timeout_s=timeout_s)
    if binding is not None and hashlib.sha256(Path(binding['path']).read_bytes()).hexdigest() != binding['sha256']:
        raise PermissionError('embedded runtime pin input changed during build')


PAYLOAD_NAMES = (
    "sentra-launcher.exe",
    "sentra-agent.exe", "sentra-mcp.exe", "sentra-browser-relay.exe",
    "sentra-desktop.exe", "sentra-human.exe", "sentra-human-worker.exe",
    "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe", "sentra-cli.exe", "sentra-canvas.exe", "sentra.exe",
)


def build_web_models(dist: Path) -> None:
    _update_build_status(state="RUNNING", step="web-models")
    script = ROOT / "scripts" / "integrations" / "Build-CodexChatGPTWebRuntime.ps1"
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("PowerShell is required to build the Web Models payload")
    command = [
        shell,
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-Dist", str(dist),
    ]
    proc = subprocess.Popen(command, cwd=ROOT)
    try:
        returncode = proc.wait(timeout=WEB_MODELS_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(proc)
        raise RuntimeError(
            f"Web Models build timed out after {WEB_MODELS_TIMEOUT_S}s"
        ) from exc
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)


def _assert_payload_replaceable(dist: Path) -> None:
    """Fail before mutation when a running Windows payload would block replacement."""
    dist.mkdir(parents=True, exist_ok=True)
    probes: list[tuple[Path, Path]] = []
    try:
        for name in PAYLOAD_NAMES:
            target = dist / name
            if not target.exists():
                continue
            probe = dist / f".{name}.sentra-build-probe-{os.getpid()}"
            os.replace(target, probe)
            probes.append((target, probe))
            os.replace(probe, target)
            probes.pop()
    except OSError as exc:
        for target, probe in reversed(probes):
            if probe.exists() and not target.exists():
                try:
                    os.replace(probe, target)
                except OSError:
                    pass
        raise RuntimeError(
            "payload publish blocked by a running SENTRA executable; "
            "stop SENTRA services and retry the build"
        ) from exc


def _publish_payload(staging: Path, dist: Path) -> None:
    """Publish a complete payload only after every executable was built.

    Windows keeps running executables locked. Building directly into dist can
    therefore leave a mixed-version payload when PyInstaller reaches a locked
    file midway through the build. Preflight every existing target first, then
    publish with rollback so dist is either the old complete set or the new one.
    """
    dist.mkdir(parents=True, exist_ok=True)
    missing = [
        name for name in PAYLOAD_NAMES
        if not (staging / name).is_file() or (staging / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError("staged payload missing: " + ", ".join(missing))

    _assert_payload_replaceable(dist)

    backup = dist.with_name(dist.name + f".payload-backup-{os.getpid()}")
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)
    moved_old: list[str] = []
    published: list[str] = []
    try:
        for name in PAYLOAD_NAMES:
            target = dist / name
            staged = staging / name
            previous = backup / name
            if target.exists():
                os.replace(target, previous)
                moved_old.append(name)
            os.replace(staged, target)
            published.append(name)
    except OSError as exc:
        rollback_errors: list[str] = []
        for name in reversed(published):
            target = dist / name
            try:
                if target.exists():
                    target.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"{name}: {rollback_exc}")
        for name in moved_old:
            previous = backup / name
            target = dist / name
            if previous.exists():
                try:
                    os.replace(previous, target)
                except OSError as rollback_exc:
                    rollback_errors.append(f"{name}: {rollback_exc}")
        detail = (
            "; rollback incomplete: " + " | ".join(rollback_errors)
            if rollback_errors else ""
        )
        raise RuntimeError(
            "payload publish failed; previous payload was restored" + detail
        ) from exc
    else:
        shutil.rmtree(backup, ignore_errors=True)


def _publish_single_executable(staged: Path, target: Path) -> None:
    """Atomically replace one Windows executable with rollback."""
    if not staged.is_file() or staged.stat().st_size == 0:
        raise RuntimeError(f"staged executable missing: {staged}")
    target.parent.mkdir(parents=True, exist_ok=True)

    probe = target.with_name(
        f".{target.name}.sentra-build-probe-{os.getpid()}"
    )
    if target.exists():
        try:
            os.replace(target, probe)
            os.replace(probe, target)
        except OSError as exc:
            if probe.exists() and not target.exists():
                try:
                    os.replace(probe, target)
                except OSError:
                    pass
            raise RuntimeError(
                f"{target.name} publish blocked by a running executable"
            ) from exc

    publish_staging = target.with_name(
        f".{target.name}.staging-{os.getpid()}"
    )
    backup = target.with_name(
        f".{target.name}.backup-{os.getpid()}"
    )
    publish_staging.unlink(missing_ok=True)
    backup.unlink(missing_ok=True)
    shutil.copy2(staged, publish_staging)
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(publish_staging, target)
    except OSError as exc:
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        if moved_old and backup.exists():
            try:
                os.replace(backup, target)
            except OSError as rollback_exc:
                raise RuntimeError(
                    f"{target.name} publish failed and rollback failed: "
                    f"{rollback_exc}"
                ) from exc
        raise RuntimeError(
            f"{target.name} publish failed; previous executable was restored"
        ) from exc
    finally:
        publish_staging.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)


def _pid_is_running(pid: int) -> bool:
    """Best-effort process liveness check used only for stale-build cleanup."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(
                0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
                False,
                pid,
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except (AttributeError, OSError, TypeError, ValueError):
            # Fail closed: unknown liveness must not delete another build.
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _staging_owner_is_live(path: Path) -> bool:
    prefix = "payload-"
    if not path.name.startswith(prefix):
        return False
    suffix = path.name[len(prefix):]
    if not suffix.isdigit():
        return False
    return _pid_is_running(int(suffix))


def _clean_build_outputs(dist: Path, work: Path, spec: Path, phase: str) -> None:
    """Clean transient state without deleting a live build's staging tree."""
    if phase in {"all", "payload"}:
        _assert_payload_replaceable(dist)
    for path in (work, spec):
        shutil.rmtree(path, ignore_errors=True)
    for stale in dist.parent.glob(dist.name + ".payload-staging-*"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
    if LOCAL_BUILD_ROOT.is_dir():
        for stale in LOCAL_BUILD_ROOT.glob("payload-*"):
            if stale.is_dir() and not _staging_owner_is_live(stale):
                shutil.rmtree(stale, ignore_errors=True)


def build_launcher(dist: Path) -> None:
    """Compile the repository launcher. Release bytes stay unbound from this checkout."""
    from scripts.commander.build_desktop_launcher import build_desktop_launcher

    dist.mkdir(parents=True, exist_ok=True)
    build_desktop_launcher(dist / "sentra-launcher.exe")


def build_payload(dist: Path, work: Path, spec: Path) -> None:
    from scripts.commander.build_canvas import validate_canvas_inputs
    validate_canvas_inputs()
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)

    build_staging = LOCAL_BUILD_ROOT / f"payload-{os.getpid()}"
    publish_staging = dist.with_name(dist.name + f".payload-staging-{os.getpid()}")
    shutil.rmtree(build_staging, ignore_errors=True)
    shutil.rmtree(publish_staging, ignore_errors=True)
    build_staging.mkdir(parents=True, exist_ok=True)
    try:
        # Build the tiny updater first. If endpoint security or PyInstaller
        # cannot start it, fail in minutes rather than after ten large payloads.
        _build(
            "sentra-update-helper",
            "update_helper_entry.py",
            build_staging,
            work,
            spec,
            timeout_s=UPDATE_HELPER_TIMEOUT_S,
        )
        _build("sentra-agent", "agent_entry.py", build_staging, work, spec, mcp_payload=True)
        _build("sentra-mcp", "mcp_entry.py", build_staging, work, spec, mcp_payload=True)
        _build("sentra-browser-relay", "browser_relay_entry.py", build_staging, work, spec)
        _build("sentra-desktop", "desktop_entry.py", build_staging, work, spec, windowed=True, mcp_payload=True)
        _build(
            "sentra-human", "human_entry.py", build_staging, work, spec, windowed=True,
            extra=[
                "--collect-all", "webview",
                "--add-data", f"{ROOT / 'sentra_remote' / 'human_ui'}{os.pathsep}human_ui",
            ],
        )
        _build("sentra-human-worker", "human_worker_entry.py", build_staging, work, spec, mcp_payload=True)
        _build("sentra-diagnostics", "diagnostics_entry.py", build_staging, work, spec)
        _build("sentra-admin", "admin_entry.py", build_staging, work, spec)
        _build(
            "sentra-oma", "oma_entry.py", build_staging, work, spec, mcp_payload=True,
            extra=["--add-data", f"{ROOT / 'config.yaml'}{os.pathsep}."],
        )
        _build(
            "sentra-cli",
            "cli_entry.py",
            build_staging,
            work,
            spec,
            extra=[
                "--add-data",
                f"{ROOT / 'config.yaml'}{os.pathsep}.",
            ],
        )
        _build("sentra", "sentra_entry.py", build_staging, work, spec, mcp_payload=True)
        from scripts.commander.build_canvas import build_canvas
        build_canvas(build_staging, work, spec)
        from scripts.commander.build_desktop_launcher import build_desktop_launcher
        build_desktop_launcher(build_staging / "sentra-launcher.exe")

        _verify_frozen_gui(build_staging / "sentra-desktop.exe")

        # Copy only finalized one-file executables back into the OneDrive tree.
        # The heavy PyInstaller work/cache stays under LOCALAPPDATA.
        publish_staging.mkdir(parents=True, exist_ok=True)
        for name in PAYLOAD_NAMES:
            source = build_staging / name
            if not source.is_file() or source.stat().st_size == 0:
                raise RuntimeError(f"local staged payload missing: {source}")
            shutil.copy2(source, publish_staging / name)
        _publish_payload(publish_staging, dist)
    finally:
        shutil.rmtree(build_staging, ignore_errors=True)
        shutil.rmtree(publish_staging, ignore_errors=True)


def build_cli(dist: Path, work: Path, spec: Path) -> None:
    """Build and atomically publish only sentra-cli.exe."""
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)

    build_staging = LOCAL_BUILD_ROOT / f"cli-{os.getpid()}"
    shutil.rmtree(build_staging, ignore_errors=True)
    build_staging.mkdir(parents=True, exist_ok=True)
    try:
        _build(
            "sentra-cli",
            "cli_entry.py",
            build_staging,
            work,
            spec,
            extra=[
                "--add-data",
                f"{ROOT / 'config.yaml'}{os.pathsep}.",
            ],
        )
        _publish_single_executable(
            build_staging / "sentra-cli.exe",
            dist / "sentra-cli.exe",
        )
    finally:
        shutil.rmtree(build_staging, ignore_errors=True)


def build_human(dist: Path, work: Path, spec: Path) -> None:
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)
    _build(
        "sentra-human", "human_entry.py", dist, work, spec, windowed=True,
        extra=[
            "--collect-all", "webview",
            "--add-data", f"{ROOT / 'sentra_remote' / 'human_ui'}{os.pathsep}human_ui",
        ],
    )
    _build("sentra-human-worker", "human_worker_entry.py", dist, work, spec, mcp_payload=True)


def build_installer(dist: Path, work: Path, spec: Path) -> None:
    missing = [name for name in PAYLOAD_NAMES if not (dist / name).is_file()]
    if missing:
        raise RuntimeError("installer payload missing: " + ", ".join(missing))
    sources = _source_fingerprint()
    proofs = []
    for path in dist.glob("build-provenance-*.json"):
        try:
            proof = json.loads(path.read_text(encoding="utf-8"))
            if proof.get("sources") == sources:
                proofs.append(proof)
        except (OSError, ValueError, TypeError):
            continue
    for name in PAYLOAD_NAMES:
        digest = _file_sha256(dist / name)
        if not any(proof.get('executables', {}).get(name, {}).get("sha256") == digest for proof in proofs):
            raise RuntimeError("stale or unverified installer payload: " + name + "; rebuild payload")
    web_models = dist / "web-models" / "win-unpacked"
    if not (web_models / "Codex Web GPT.exe").is_file() or not (web_models / "resources" / "runtime" / "manifest.json").is_file():
        raise RuntimeError("packaged Electron Web Models payload is missing")
    build_state_path = dist / "web-models" / "integration-build.json"
    if not build_state_path.is_file():
        raise RuntimeError("Web Models integration build metadata is missing")
    build_state = json.loads(build_state_path.read_text(encoding="utf-8-sig"))
    patch = ROOT / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch"
    patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
    if str(build_state.get("patch_sha256") or "").lower() != patch_hash:
        raise RuntimeError("Web Models payload was built from a stale SENTRA upstream patch")
    if not (dist / 'runtime-components.json').is_file() or not (dist / 'runtime').is_dir():
        raise RuntimeError('materialized QuickJS/HCS/RustDesk release components required; stage via release_components in final phase')
    binding = _RUNTIME_BINDING.get()
    if binding is None:
        raise RuntimeError('integral Setup requires build-embedded runtime pins; rebuild payload with --runtime-components')
    from scripts.commander.runtime_bindings import runtime_pins
    current_pins = (json.dumps(runtime_pins(dist), sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if hashlib.sha256(current_pins).hexdigest() != binding['sha256']:
        raise PermissionError('Setup runtime components differ from embedded payload pins')
    for name in PAYLOAD_NAMES:
        if name == 'sentra-launcher.exe':
            continue  # C# launcher delegates to the pinned Python executables.
        digest = _file_sha256(dist / name)
        if not any(proof.get('runtime_pins_sha256') == binding['sha256'] and
                   proof.get('executables', {}).get(name, {}).get('sha256') == digest for proof in proofs):
            raise RuntimeError('payload lacks current embedded runtime pins: ' + name)
    from sentra_remote.codex_registration_runtime import validate_registration_runtime
    validate_registration_runtime(dist / 'prerequisites/codex-registration')
    from sentra_remote.enrollment_extension import stage_extensions
    stage_extensions(ROOT / 'sentra_remote/enrollment_extension', dist / 'prerequisites/browser-enrollment')
    # Reject incomplete or stale binaries before staging assets or downloading.
    import tempfile
    work.mkdir(parents=True, exist_ok=True)
    extension_parent = Path(tempfile.mkdtemp(prefix='sentra-extension-release-', dir=work))
    staged_extension = extension_parent / 'edge_extension'
    stage_extension_source(ROOT / 'edge_extension', staged_extension)
    from scripts.commander.runtime_dependencies import stage_wasmtime_notices
    runtime_legal = extension_parent / 'wasmtime'
    stage_wasmtime_notices(runtime_legal)
    packaged_docs = extension_parent / "docs"
    shutil.copytree(ROOT / "docs", packaged_docs)
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", packaged_docs / "THIRD_PARTY_NOTICES.md")
    shutil.copytree(ROOT / "sentra_remote/provider_notices", packaged_docs / "provider_notices", dirs_exist_ok=True)
    shutil.copytree(runtime_legal, packaged_docs / "wasmtime", dirs_exist_ok=True)
    # Electron is a second *display*, not a parallel executor or MCP server.
    # If the pinned runtime was installed during build preparation, stage the
    # complete, versioned optional component; never download at packaging time.
    electron_source = ROOT / "sentra_electron"
    electron_payload = dist / "sentra-electron"
    if not (electron_source / "node_modules" / "electron" / "dist" / "electron.exe").is_file():
        raise RuntimeError("SENTRA Electron runtime missing: npm ci --prefix sentra_electron")
    from scripts.commander.stage_electron import stage_electron_surface, validate_electron_payload
    stage_electron_surface(electron_source, electron_payload)
    validate_electron_payload(electron_payload)
    from scripts.commander.stage_mobile import stage_mobile_runtime
    mobile_payload = dist / 'sentra-mobile'
    node = shutil.which('node')
    if not node:raise RuntimeError('Node 24 is required to stage the standalone mobile gateway')
    stage_mobile_runtime(mobile_payload, Path(node))
    from scripts.commander.stage_terminal import stage_terminal_runtime
    terminal_payload = dist / 'sentra-terminal'
    stage_terminal_runtime(terminal_payload)
    installer_extra: list[str] = [
        "--add-data", f"{electron_payload}{os.pathsep}payload/sentra-electron",
        "--add-data", f"{mobile_payload}{os.pathsep}payload/sentra-mobile",
        "--add-data", f"{terminal_payload}{os.pathsep}payload/sentra-terminal",
    ]
    installer_extra += ['--add-data', f"{dist / 'runtime'}{os.pathsep}payload/runtime",
                        '--add-data', f"{dist / 'runtime-components.json'}{os.pathsep}payload"]
    for name in PAYLOAD_NAMES:
        installer_extra += ["--add-data", f"{dist / name}{os.pathsep}payload"]
    installer_extra += [
        "--add-data", f"{staged_extension}{os.pathsep}edge_extension",
        "--add-data", f"{packaged_docs}{os.pathsep}docs",
        "--add-data", f"{dist / 'web-models'}{os.pathsep}payload/web-models",
    ]
    for name in ('opendots', 'guacamole'):
        legal = ROOT / 'sentra_canvas/desktop_ui/src/assets' / name
        required = ('LICENSE', 'PROVENANCE.json', 'NOTICE') if name == 'guacamole' else ('LICENSE', 'PROVENANCE.json')
        for filename in required:
            if not (legal / filename).is_file():
                raise FileNotFoundError('integral Setup legal asset missing: ' + name + '/' + filename)
            (packaged_docs / name).mkdir(parents=True, exist_ok=True)
            shutil.copy2(legal / filename, packaged_docs / name / filename)
    # Client installation is offline: fetch the pinned dependency on the build
    # machine and embed its original verified archive in Setup.
    from sentra_remote.installer import prepare_tunnel_archive
    from sentra_remote.installer_preflight import write_payload_manifest
    from sentra_version import PRODUCT_VERSION
    archive = prepare_tunnel_archive(work / "downloads")
    prerequisites = dist / "prerequisites"
    prerequisites.mkdir(exist_ok=True)
    if archive.resolve() != (prerequisites / "tunnel-client.zip").resolve():
        shutil.copy2(archive, prerequisites / "tunnel-client.zip")
    manifest = write_payload_manifest(dist, staged_extension, packaged_docs, PRODUCT_VERSION, PAYLOAD_NAMES)
    installer_extra += ["--add-data", f"{prerequisites}{os.pathsep}payload/prerequisites",
                        "--add-data", f"{manifest}{os.pathsep}payload"]
    _build(
        "SENTRA-Setup",
        "installer_entry.py",
        dist, work, spec,
        windowed=True,
        extra=installer_extra,
        timeout_s=SETUP_TIMEOUT_S,
    )
    _verify_frozen_gui(dist / "SENTRA-Setup.exe")


def build(dist: Path, work: Path, spec: Path, sources: dict[str, str] | None = None) -> None:
    sources = _source_fingerprint() if sources is None else sources
    build_web_models(dist)
    build_payload(dist, work, spec)
    _write_build_provenance(dist, "payload", PAYLOAD_NAMES, sources)
    build_installer(dist, work, spec)


EXPECTED = (
    "sentra-launcher.exe",
    "sentra-agent.exe", "sentra-mcp.exe", "sentra-browser-relay.exe",
    "sentra-desktop.exe", "sentra-human.exe", "sentra-human-worker.exe",
    "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe", "sentra-cli.exe", "sentra-canvas.exe", "sentra.exe",
    "SENTRA-Setup.exe",
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--work", default=str(LOCAL_BUILD_ROOT / "work"))
    parser.add_argument("--spec", default=str(LOCAL_BUILD_ROOT / "spec"))
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument('--runtime-components', help='Host-selected materialized staging root; defaults to dist when present')
    parser.add_argument(
        "--phase",
        choices=("all", "payload", "launcher", "cli", "canvas", "mcp", "helper", "human", "installer", "runtime-probe"),
        default="all",
    )
    args = parser.parse_args()
    if args.phase in {"all", "payload", "installer"}:
        _verify_build_gui_runtime()
    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    spec = Path(args.spec).resolve()
    with _BuildLock(ROOT / ".sentra" / "build-windows.lock"), _RuntimeBinding(
            args.runtime_components or dist, required=args.phase in {'all', 'payload', 'installer', 'runtime-probe'}):
        if (ROOT / "source-snapshot.json").is_file():
            from scripts.commander.source_snapshot import verify_source_snapshot
            verify_source_snapshot(ROOT)
        # Extension identity is materialized only in an isolated Setup staging
        # directory; live extension/preview inputs remain unchanged.
        sources = _source_fingerprint()
        started_at = time.time()
        _update_build_status(
            state="RUNNING",
            phase=args.phase,
            step="starting",
            started_at=started_at,
            finished_at=None,
            duration_s=None,
            error=None,
            reason=None,
            dist=str(dist),
        )
        try:
            if args.clean_output:
                # Preserve the last published distribution until every replacement is
                # ready. Only transient work/spec trees are removed up front.
                _clean_build_outputs(dist, work, spec, args.phase)
            if args.phase == "all":
                build(dist, work, spec, sources)
                expected = EXPECTED
            elif args.phase == "payload":
                build_payload(dist, work, spec)
                expected = PAYLOAD_NAMES
            elif args.phase == "launcher":
                build_launcher(dist)
                expected = ("sentra-launcher.exe",)
            elif args.phase == "cli":
                build_cli(dist, work, spec)
                expected = ("sentra-cli.exe",)
            elif args.phase == "canvas":
                from scripts.commander.build_canvas import build_canvas
                build_canvas(dist, work, spec)
                expected = ("sentra-canvas.exe",)
            elif args.phase == "mcp":
                _build("sentra-mcp","mcp_entry.py",dist,work,spec,mcp_payload=True)
                expected = ("sentra-mcp.exe",)
            elif args.phase == "helper":
                _build("sentra-update-helper", "update_helper_entry.py", dist, work, spec,
                       timeout_s=UPDATE_HELPER_TIMEOUT_S)
                expected = ("sentra-update-helper.exe",)
            elif args.phase == "human":
                build_human(dist, work, spec)
                expected = ("sentra-human.exe", "sentra-human-worker.exe")
            elif args.phase == 'runtime-probe':
                from scripts.commander.runtime_dependencies import require_wasmtime_pin
                require_wasmtime_pin()
                _build('sentra-runtime-probe', 'runtime_probe_entry.py', dist, work, spec,
                    extra=['--collect-all', 'wasmtime'])
                expected = ('sentra-runtime-probe.exe',)
            else:
                build_installer(dist, work, spec)
                expected = ("SENTRA-Setup.exe",)
            for name in expected:
                target = dist / name
                if not target.is_file() or target.stat().st_size == 0:
                    raise RuntimeError(f"missing release executable: {target}")
                print(f"{name}: {target.stat().st_size} bytes")
            _write_build_provenance(dist, args.phase, expected, sources)
        except BaseException as exc:
            state = "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED"
            _update_build_status(
                state=state,
                step="terminated",
                finished_at=time.time(),
                duration_s=max(0.0, time.time() - started_at),
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
            raise
        else:
            _update_build_status(
                state="SUCCEEDED",
                step="complete",
                finished_at=time.time(),
                duration_s=max(0.0, time.time() - started_at),
                error=None,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
