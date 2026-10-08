"""Build Windows SENTRA Desktop executables and self-contained setup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "").strip()
LOCAL_BUILD_ROOT = (
    Path(_LOCALAPPDATA) / "SENTRA" / "Build" / "commander"
    if _LOCALAPPDATA
    else ROOT / ".tmp" / "local-build" / "commander"
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BUILD_STATUS_PATH = ROOT / ".tmp" / "build-windows-status.json"


def _source_fingerprint() -> dict[str, str]:
    """Record product inputs only, excluding private state and generated caches."""
    folders = (
        "browser", "integrations", "native_bridge", "orchestrator", "repository",
        "sentra_core", "sentra_mcp", "sentra_model_gateway", "sentra_remote",
        "sentra_cli", "sentra_canvas", "workspace", "scripts/commander", "edge_extension",
    )
    extensions = {".py", ".js", ".css", ".html", ".json", ".ps1", ".cmd", ".yaml", ".ico"}
    files = {ROOT / name for name in ("main.py", "sentra_version.py", "config.yaml", "requirements.lock.txt")}
    for folder in folders:
        files.update(path for path in (ROOT / folder).rglob("*")
                     if path.is_file() and path.suffix.lower() in extensions
                     and "__pycache__" not in path.parts)
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files) if path.is_file()}


def _write_build_provenance(dist: Path, phase: str, expected: tuple[str, ...], sources: dict[str, str]) -> None:
    current = _source_fingerprint()
    if current != sources:
        changed = sorted(name for name in set(current) | set(sources) if current.get(name) != sources.get(name))
        raise RuntimeError("product source changed during build; rebuild before release: " + ", ".join(changed[:10]))
    result = {
        "schema_version": 1, "phase": phase, "python": sys.version.split()[0],
        "sources": sources,
        "executables": {name: {"sha256": hashlib.sha256((dist / name).read_bytes()).hexdigest(),
                               "bytes": (dist / name).stat().st_size} for name in expected},
    }
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


from scripts.commander.extension_identity import stamp_extension_identity


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
UPDATE_HELPER_TIMEOUT_S = 600
WEB_MODELS_TIMEOUT_S = 600


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
    if mcp_payload:
        prefix += ["--collect-all", "playwright", "--hidden-import", "pyarrow.parquet"]
    if extra:
        prefix += extra
    args[0:0] = prefix
    _run(args, timeout_s=timeout_s)


PAYLOAD_NAMES = (
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


def build_payload(dist: Path, work: Path, spec: Path) -> None:
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
    stamp_extension_identity(ROOT / "edge_extension")
    missing = [name for name in PAYLOAD_NAMES if not (dist / name).is_file()]
    if missing:
        raise RuntimeError("installer payload missing: " + ", ".join(missing))
    sources = _source_fingerprint()
    proofs = []
    for path in dist.glob("build-provenance-*.json"):
        try:
            proof = json.loads(path.read_text(encoding="utf-8"))
            if proof.get("sources") == sources:
                proofs.append(proof.get("executables", {}))
        except (OSError, ValueError, TypeError):
            continue
    for name in PAYLOAD_NAMES:
        digest = hashlib.sha256((dist / name).read_bytes()).hexdigest()
        if not any(proof.get(name, {}).get("sha256") == digest for proof in proofs):
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
    installer_extra: list[str] = []
    for name in PAYLOAD_NAMES:
        installer_extra += ["--add-data", f"{dist / name}{os.pathsep}payload"]
    installer_extra += [
        "--add-data", f"{ROOT / 'edge_extension'}{os.pathsep}edge_extension",
        "--add-data", f"{ROOT / 'docs'}{os.pathsep}docs",
        "--add-data", f"{dist / 'web-models'}{os.pathsep}payload/web-models",
    ]
    _build(
        "SENTRA-Setup",
        "installer_entry.py",
        dist, work, spec,
        windowed=True,
        extra=installer_extra,
    )


def build(dist: Path, work: Path, spec: Path, sources: dict[str, str] | None = None) -> None:
    sources = _source_fingerprint() if sources is None else sources
    build_web_models(dist)
    build_payload(dist, work, spec)
    _write_build_provenance(dist, "payload", PAYLOAD_NAMES, sources)
    build_installer(dist, work, spec)


EXPECTED = (
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
    parser.add_argument(
        "--phase",
        choices=("all", "payload", "cli", "canvas", "mcp", "helper", "human", "installer"),
        default="all",
    )
    args = parser.parse_args()
    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    spec = Path(args.spec).resolve()
    with _BuildLock(ROOT / ".sentra" / "build-windows.lock"):
        # Identity stamping is an intentional input mutation, before the snapshot.
        if args.phase in {"all", "installer"}:
            stamp_extension_identity(ROOT / "edge_extension")
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
