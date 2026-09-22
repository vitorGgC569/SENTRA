"""Persistent, owner-isolated subprocess management for SENTRA MCP."""
from __future__ import annotations

import ntpath
import os
import posixpath
import shlex
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Sequence

from workspace.paths import PathAccessError, resolve_workspace_path

from ..audit import AuditLogger
from ..config import MCPConfig
from .process_sandbox import DockerProcessSandbox, PreparedProcess
from .workspaces import WorkspaceRegistry

_SENSITIVE_ENV_PARTS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "COOKIE")
_SENSITIVE_PYTHON_ENV = {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}
_TERMINATE_GRACE_SECONDS = 0.5
_MODE_LEVEL = {"sandbox": 0, "workspace": 1, "unrestricted": 2}


@dataclass(slots=True)
class _ProcessRecord:
    session_id: str
    owner: str
    argv: tuple[str, ...]
    launch_argv: tuple[str, ...]
    process: subprocess.Popen[bytes]
    created_at: str
    cwd: str
    mode: str
    workspace: str
    workspace_alias: str
    container_name: str | None = None
    image_id: str | None = None
    source_readonly: bool = False
    network: str = "host"
    snapshot: object | None = None
    sandbox_backend: DockerProcessSandbox | None = None
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    retained_bytes: int = 0
    output_truncated: bool = False
    timed_out: bool = False
    tree_closed: bool = False
    resources_closed: bool = False
    process_group_id: int | None = None
    readers: list[threading.Thread] = field(default_factory=list)
    timer: threading.Timer | None = None
    termination_lock: threading.Lock = field(default_factory=threading.Lock)


class ProcessService:
    """Manage persistent host or Docker-isolated child processes."""

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger | None = None,
        workspaces: WorkspaceRegistry | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.workspaces = workspaces
        self._lock = threading.RLock()
        self._sessions: dict[str, _ProcessRecord] = {}
        self._pids: dict[int, _ProcessRecord] = {}
        self._closed = False

    def update_config(self, config: MCPConfig) -> None:
        self.config = config

    @staticmethod
    def _require_owner(owner: str) -> str:
        normalized = owner.strip()
        if not normalized:
            raise ValueError("owner must be a non-empty string")
        return normalized

    @staticmethod
    def _command_names(value: str) -> set[str]:
        normalized = value.casefold()
        return {
            normalized,
            os.path.basename(value).casefold(),
            ntpath.basename(value).casefold(),
            posixpath.basename(value).casefold(),
        }

    def _parse_command(self, command: str | Sequence[str]) -> tuple[str, ...]:
        if isinstance(command, str):
            if "\x00" in command:
                raise ValueError("command contains a null byte")
            try:
                parts = shlex.split(command, posix=os.name != "nt")
            except ValueError as exc:
                raise ValueError("command could not be tokenized") from exc
            if os.name == "nt":
                parts = [
                    part[1:-1]
                    if len(part) >= 2 and part[0] == part[-1] == '"'
                    else part
                    for part in parts
                ]
        else:
            if isinstance(command, (bytes, bytearray)):
                raise ValueError("command must be a string or argv sequence")
            parts = [str(part) for part in command]

        if not parts or not parts[0].strip():
            raise ValueError("command must not be empty")
        if any("\x00" in part for part in parts):
            raise ValueError("command contains a null byte")

        executable_names = self._command_names(parts[0])
        blocked_names: set[str] = set()
        for blocked in self.config.blocked_commands:
            blocked_names.update(self._command_names(blocked))
        if executable_names & blocked_names:
            raise PermissionError("command is blocked by policy")
        return tuple(parts)

    def _select_mode(self, requested: str | None) -> str:
        mode = (requested or self.config.process_mode).strip().lower()
        if mode not in _MODE_LEVEL:
            raise ValueError("mode must be sandbox, workspace or unrestricted")
        ceiling = self.config.process_mode
        if _MODE_LEVEL[mode] > _MODE_LEVEL[ceiling]:
            raise PermissionError(
                f"process mode '{mode}' exceeds configured privilege ceiling '{ceiling}'"
            )
        return mode

    def _legacy_workspace(self) -> dict[str, object]:
        root = Path(self.config.allowed_roots[0]).resolve()
        return {
            "id": "root:0",
            "alias": "sentra",
            "path": str(root),
            "permissions": ["execute", "read", "write"],
        }

    def _resolve_workspace(
        self,
        workspace: str | None,
        owner: str,
    ) -> dict[str, object]:
        if self.workspaces is None:
            if workspace not in (None, "", "root:0", "sentra", str(self.config.allowed_roots[0])):
                raise PermissionError("workspace is not allowlisted")
            return self._legacy_workspace()
        return self.workspaces.resolve(workspace, owner, "execute")

    @staticmethod
    def _resolve_cwd_in_workspace(
        root: Path,
        cwd: str | None,
    ) -> Path:
        if cwd is None:
            target = root
        else:
            if not isinstance(cwd, str) or not cwd.strip() or "\x00" in cwd:
                raise ValueError("cwd must be a non-empty path string")
            candidate = Path(cwd)
            if candidate.is_absolute():
                try:
                    relative = candidate.resolve().relative_to(root)
                except ValueError as exc:
                    raise PathAccessError("cwd is outside selected workspace") from exc
                target = resolve_workspace_path(root, relative.as_posix() or ".")
            else:
                target = resolve_workspace_path(root, cwd)
        if not target.is_dir():
            raise NotADirectoryError("cwd is not a directory")
        return target

    @staticmethod
    def _sanitized_environment() -> dict[str, str]:
        clean: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if upper in _SENSITIVE_PYTHON_ENV:
                continue
            if any(part in upper for part in _SENSITIVE_ENV_PARTS):
                continue
            clean[key] = value
        return clean

    def _sandbox_backend(self, image: str | None = None) -> DockerProcessSandbox:
        return DockerProcessSandbox(
            image=image or self.config.process_sandbox_image,
            cpus=self.config.process_sandbox_cpus,
            memory_mb=self.config.process_sandbox_memory_mb,
            pids_limit=self.config.process_sandbox_pids,
        )

    def sandbox_status(self, image: str | None = None) -> dict[str, object]:
        backend = self._sandbox_backend(image)
        status = backend.status()
        status.update({
            "configured_mode": self.config.process_mode,
            "image": image or self.config.process_sandbox_image,
            "privilege_order": ["sandbox", "workspace", "unrestricted"],
        })
        return status

    def _prepare_process(
        self,
        argv: tuple[str, ...],
        owner: str,
        *,
        cwd: str | None,
        workspace: str | None,
        mode: str,
        image: str | None,
    ) -> tuple[PreparedProcess, dict[str, object]]:
        view = self._resolve_workspace(workspace, owner)
        root = Path(str(view["path"])).resolve()
        cwd_path = self._resolve_cwd_in_workspace(root, cwd)

        if mode == "unrestricted":
            prepared = PreparedProcess(
                argv=argv,
                host_cwd=cwd_path,
                mode="unrestricted",
                source_readonly=False,
                network="host",
            )
        else:
            backend = self._sandbox_backend(image)
            writable = "write" in set(view.get("permissions") or [])
            prepared = backend.prepare(
                argv,
                workspace_root=root,
                cwd=cwd_path,
                writable=writable,
                copy_on_write=(mode == "sandbox"),
            )
        return prepared, view

    def _audit(self, action: str, outcome: str, details: dict[str, object]) -> None:
        if self.audit is None:
            return
        try:
            self.audit.emit(action, outcome, details)
        except OSError:
            pass

    def _active_count_locked(self) -> int:
        return sum(record.process.poll() is None for record in self._sessions.values())

    def _append_output(self, record: _ProcessRecord, target: bytearray, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            remaining = self.config.max_output_bytes - record.retained_bytes
            if remaining <= 0:
                record.output_truncated = True
                return
            kept = chunk[:remaining]
            target.extend(kept)
            record.retained_bytes += len(kept)
            if len(kept) != len(chunk):
                record.output_truncated = True

    def _reader(self, record: _ProcessRecord, stream: BinaryIO, target: bytearray) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                self._append_output(record, target, chunk)
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _cleanup_record_resources(self, record: _ProcessRecord) -> None:
        with record.termination_lock:
            if record.resources_closed:
                return
            if record.sandbox_backend is not None:
                record.sandbox_backend.cleanup_container(record.container_name)
            snapshot = record.snapshot
            if snapshot is not None:
                try:
                    snapshot.close()
                except Exception:
                    pass
            record.resources_closed = True

    def _watch(self, record: _ProcessRecord) -> None:
        record.process.wait()
        with self._lock:
            if record.timer is not None:
                record.timer.cancel()
        if os.name != "nt" and record.mode == "unrestricted":
            self._terminate_tree(record)
        self._cleanup_record_resources(record)

    def _start_background_workers(self, record: _ProcessRecord, timeout: float | None) -> None:
        assert record.process.stdout is not None
        assert record.process.stderr is not None
        for stream, target, name in (
            (record.process.stdout, record.stdout, "stdout"),
            (record.process.stderr, record.stderr, "stderr"),
        ):
            thread = threading.Thread(
                target=self._reader,
                args=(record, stream, target),
                name=f"sentra-{name}-{record.session_id}",
                daemon=True,
            )
            record.readers.append(thread)
            thread.start()

        if timeout is not None:
            timer = threading.Timer(timeout, self._timeout_session, args=(record.session_id,))
            timer.daemon = True
            record.timer = timer
            timer.start()

        watcher = threading.Thread(
            target=self._watch,
            args=(record,),
            name=f"sentra-watch-{record.session_id}",
            daemon=True,
        )
        watcher.start()

    def start_process(
        self,
        command: str | Sequence[str],
        owner: str,
        timeout: float | None = None,
        cwd: str | None = None,
        *,
        workspace: str | None = None,
        mode: str | None = None,
        image: str | None = None,
    ) -> dict[str, object]:
        """Start a managed process at or below the configured privilege ceiling."""
        normalized_owner = self._require_owner(owner)
        argv = self._parse_command(command)
        selected_mode = self._select_mode(mode)
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        prepared: PreparedProcess | None = None
        try:
            prepared, view = self._prepare_process(
                argv,
                normalized_owner,
                cwd=cwd,
                workspace=workspace,
                mode=selected_mode,
                image=image,
            )

            popen_kwargs: dict[str, object] = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True

            with self._lock:
                if self._closed:
                    raise RuntimeError("process service is shut down")
                if self._active_count_locked() >= self.config.max_processes:
                    raise RuntimeError("maximum managed process count reached")

                process = subprocess.Popen(
                    list(prepared.argv),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self._sanitized_environment(),
                    cwd=str(prepared.host_cwd),
                    bufsize=0,
                    shell=False,
                    **popen_kwargs,
                )
                record = _ProcessRecord(
                    session_id=str(uuid.uuid4()),
                    owner=normalized_owner,
                    argv=argv,
                    launch_argv=prepared.argv,
                    process=process,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    cwd=str(self._resolve_cwd_in_workspace(Path(str(view["path"])).resolve(), cwd)),
                    mode=selected_mode,
                    workspace=str(view["id"]),
                    workspace_alias=str(view["alias"]),
                    container_name=prepared.container_name,
                    image_id=prepared.image_id,
                    source_readonly=prepared.source_readonly,
                    network=prepared.network,
                    snapshot=prepared.snapshot,
                    sandbox_backend=self._sandbox_backend(image) if selected_mode != "unrestricted" else None,
                    process_group_id=process.pid if os.name != "nt" else None,
                )
                self._sessions[record.session_id] = record
                self._pids[process.pid] = record

            try:
                self._start_background_workers(record, timeout)
            except Exception:
                self._terminate_tree(record)
                self._cleanup_record_resources(record)
                with self._lock:
                    self._sessions.pop(record.session_id, None)
                    self._pids.pop(process.pid, None)
                raise

            self._audit(
                "process.start",
                "ok",
                {
                    "session_id": record.session_id,
                    "owner": normalized_owner,
                    "pid": process.pid,
                    "timeout": timeout,
                    "cwd": record.cwd,
                    "mode": selected_mode,
                    "workspace": record.workspace,
                    "workspace_alias": record.workspace_alias,
                    "container_name": record.container_name,
                    "image_id": record.image_id,
                    "network": record.network,
                    "source_readonly": record.source_readonly,
                },
            )
            return self._record_info(record)
        except Exception:
            if prepared is not None and prepared.snapshot is not None:
                try:
                    prepared.snapshot.close()
                except Exception:
                    pass
            raise

    def _owned_session(self, session_id: str, owner: str) -> _ProcessRecord:
        normalized_owner = self._require_owner(owner)
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise KeyError("unknown process session")
            if record.owner != normalized_owner:
                raise PermissionError("process session belongs to another owner")
            return record

    def _owned_pid(self, pid: int, owner: str) -> _ProcessRecord:
        normalized_owner = self._require_owner(owner)
        with self._lock:
            record = self._pids.get(pid)
            if record is None:
                raise PermissionError("pid is not a managed process")
            if record.owner != normalized_owner:
                raise PermissionError("managed process belongs to another owner")
            return record

    def _join_readers_if_complete(self, record: _ProcessRecord) -> None:
        if record.process.poll() is None:
            return
        for thread in record.readers:
            thread.join(timeout=0.25)

    def read_process_output(
        self,
        session_id: str,
        owner: str,
        offset: int = 0,
        length: int = 65536,
    ) -> dict[str, object]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if length <= 0:
            raise ValueError("length must be greater than zero")
        record = self._owned_session(session_id, owner)
        self._join_readers_if_complete(record)
        bounded_length = min(length, self.config.max_output_bytes)
        with self._lock:
            stdout_slice = bytes(record.stdout[offset : offset + bounded_length])
            stderr_slice = bytes(record.stderr[offset : offset + bounded_length])
            info = self._record_info_locked(record)
            info.update({
                "offset": offset,
                "length": bounded_length,
                "stdout": stdout_slice.decode("utf-8", errors="replace"),
                "stderr": stderr_slice.decode("utf-8", errors="replace"),
                "stdout_bytes": len(record.stdout),
                "stderr_bytes": len(record.stderr),
            })
            return info

    def interact_with_process(
        self,
        session_id: str,
        owner: str,
        stdin: str,
    ) -> dict[str, object]:
        record = self._owned_session(session_id, owner)
        if "\x00" in stdin:
            raise ValueError("stdin contains a null byte")
        data = stdin.encode("utf-8")
        if len(data) > self.config.max_write_bytes:
            raise ValueError("stdin exceeds configured write limit")
        with self._lock:
            if record.process.poll() is not None:
                raise RuntimeError("process is not running")
            stream = record.process.stdin
            if stream is None:
                raise RuntimeError("process stdin is unavailable")
            try:
                stream.write(data)
                stream.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError("process stdin is closed") from exc
        self._audit(
            "process.interact",
            "ok",
            {
                "session_id": session_id,
                "owner": record.owner,
                "pid": record.process.pid,
                "stdin_bytes": len(data),
            },
        )
        return self._record_info(record)

    def list_sessions(self, owner: str) -> list[dict[str, object]]:
        normalized_owner = self._require_owner(owner)
        with self._lock:
            records = [
                record
                for record in self._sessions.values()
                if record.owner == normalized_owner
            ]
            return [self._record_info_locked(record) for record in records]

    def list_processes(self, owner: str) -> list[dict[str, object]]:
        return self.list_sessions(owner)

    def _record_info_locked(self, record: _ProcessRecord) -> dict[str, object]:
        returncode = record.process.poll()
        return {
            "session_id": record.session_id,
            "owner": record.owner,
            "pid": record.process.pid,
            "executable": os.path.basename(record.argv[0]),
            "created_at": record.created_at,
            "cwd": record.cwd,
            "running": returncode is None,
            "returncode": returncode,
            "timed_out": record.timed_out,
            "output_truncated": record.output_truncated,
            "mode": record.mode,
            "workspace": record.workspace,
            "workspace_alias": record.workspace_alias,
            "container_name": record.container_name,
            "image_id": record.image_id,
            "network": record.network,
            "source_readonly": record.source_readonly,
        }

    def _record_info(self, record: _ProcessRecord) -> dict[str, object]:
        with self._lock:
            return self._record_info_locked(record)

    def _timeout_session(self, session_id: str) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None or record.process.poll() is not None:
                return
            record.timed_out = True
        self._terminate_tree(record)
        self._cleanup_record_resources(record)
        self._audit(
            "process.timeout",
            "ok",
            {
                "session_id": session_id,
                "owner": record.owner,
                "pid": record.process.pid,
            },
        )

    @staticmethod
    def _kill_host_tree(process: subprocess.Popen[bytes], pgid: int | None) -> None:
        if os.name == "nt":
            if process.poll() is not None:
                return
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5,
                    shell=False,
                )
            except subprocess.TimeoutExpired:
                process.kill()
            try:
                process.wait(timeout=_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_TERMINATE_GRACE_SECONDS)
            return

        if pgid is None:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=_TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()

    def _terminate_tree(self, record: _ProcessRecord) -> None:
        with record.termination_lock:
            if record.tree_closed:
                return
            if record.sandbox_backend is not None:
                record.sandbox_backend.cleanup_container(record.container_name)
            self._kill_host_tree(record.process, record.process_group_id)
            record.tree_closed = True

    def terminate_session(self, session_id: str, owner: str) -> dict[str, object]:
        record = self._owned_session(session_id, owner)
        self._terminate_tree(record)
        self._join_readers_if_complete(record)
        self._cleanup_record_resources(record)
        self._audit(
            "process.terminate",
            "ok",
            {
                "session_id": session_id,
                "owner": record.owner,
                "pid": record.process.pid,
            },
        )
        return self._record_info(record)

    def kill_process(self, pid: int, owner: str) -> dict[str, object]:
        record = self._owned_pid(pid, owner)
        self._terminate_tree(record)
        self._join_readers_if_complete(record)
        self._cleanup_record_resources(record)
        self._audit(
            "process.kill",
            "ok",
            {
                "session_id": record.session_id,
                "owner": record.owner,
                "pid": pid,
            },
        )
        return self._record_info(record)

    def cleanup(self) -> None:
        with self._lock:
            records = list(self._sessions.values())
        for record in records:
            was_running = record.process.poll() is None
            self._terminate_tree(record)
            self._cleanup_record_resources(record)
            if was_running:
                self._audit(
                    "process.cleanup",
                    "ok",
                    {
                        "session_id": record.session_id,
                        "owner": record.owner,
                        "pid": record.process.pid,
                    },
                )

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.cleanup()
