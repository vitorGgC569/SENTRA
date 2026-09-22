"""Real OS/container isolation for persistent SENTRA process sessions."""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from workspace.docker_runner import IMAGE_ID, LOCAL_ENDPOINT, docker_executable
from workspace.sandbox import WorkspaceSandbox

_IMAGE_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:/@-]{0,250}")


@dataclass(slots=True)
class PreparedProcess:
    argv: tuple[str, ...]
    host_cwd: Path
    container_name: str | None = None
    image_id: str | None = None
    snapshot: WorkspaceSandbox | None = None
    mode: str = "unrestricted"
    source_readonly: bool = False
    network: str = "host"


class DockerProcessSandbox:
    """Prepare docker CLI argv with a fail-closed local-only daemon boundary."""

    def __init__(
        self,
        *,
        image: str,
        cpus: float = 2.0,
        memory_mb: int = 2048,
        pids_limit: int = 256,
    ) -> None:
        if not _IMAGE_RE.fullmatch(image):
            raise ValueError("invalid operator-owned Docker image")
        self.image = image
        self.cpus = max(0.25, min(float(cpus), 16.0))
        self.memory_mb = max(128, min(int(memory_mb), 32768))
        self.pids_limit = max(16, min(int(pids_limit), 4096))
        self.docker = docker_executable()
        self.prefix = [self.docker, "--host", LOCAL_ENDPOINT]

    def _checked(self, args: Sequence[str], timeout: float = 20) -> str:
        try:
            result = subprocess.run(
                [*self.prefix, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("DOCKER_UNAVAILABLE: local Docker daemon timed out") from exc
        if result.returncode != 0:
            raise RuntimeError("DOCKER_UNAVAILABLE: " + result.stderr[-2000:].strip())
        return result.stdout

    def status(self) -> dict[str, object]:
        try:
            raw = self._checked(["info", "--format", "{{json .}}"], 10)
            info = json.loads(raw)
            secure = (
                info.get("OSType") == "linux"
                and bool(info.get("MemoryLimit"))
                and bool(info.get("CpuCfsQuota"))
                and bool(info.get("PidsLimit"))
                and any("name=seccomp" in str(item) for item in info.get("SecurityOptions", []))
            )
            return {
                "available": bool(secure),
                "docker": self.docker,
                "endpoint": LOCAL_ENDPOINT,
                "os_type": info.get("OSType"),
                "security_options": info.get("SecurityOptions", []),
            }
        except Exception as exc:
            return {
                "available": False,
                "docker": self.docker,
                "endpoint": LOCAL_ENDPOINT,
                "error": str(exc)[:1000],
            }

    def _prepare_image(self) -> str:
        info_raw = self._checked(["info", "--format", "{{json .}}"], 10)
        info = json.loads(info_raw)
        if (
            info.get("OSType") != "linux"
            or not all(info.get(key) for key in ("MemoryLimit", "CpuCfsQuota", "PidsLimit"))
            or not any("name=seccomp" in str(item) for item in info.get("SecurityOptions", []))
        ):
            raise RuntimeError(
                "Docker sandbox requires Linux containers, seccomp and enforced resource limits"
            )
        data = json.loads(self._checked(["image", "inspect", self.image], 15))[0]
        image_id = str(data.get("Id") or "")
        config = data.get("Config") or {}
        if data.get("Os") != "linux" or not IMAGE_ID.fullmatch(image_id):
            raise RuntimeError("invalid Linux sandbox image")
        if config.get("Volumes") or config.get("Healthcheck"):
            raise RuntimeError("sandbox image must not define volumes or healthchecks")
        if (config.get("Labels") or {}).get("org.oma.sandbox") != "1":
            raise RuntimeError(
                "sandbox image is not trusted; build it with scripts/prepare_docker.py --build"
            )
        return image_id

    @staticmethod
    def _validate_mount_source(path: Path) -> None:
        raw = str(path)
        if any(char in raw for char in (",", "\n", "\r", '"')):
            raise ValueError("unsupported workspace path for Docker bind mount")

    def prepare(
        self,
        command: Sequence[str],
        *,
        workspace_root: Path,
        cwd: Path,
        writable: bool,
        copy_on_write: bool,
    ) -> PreparedProcess:
        if not command:
            raise ValueError("sandbox command must not be empty")
        workspace_root = Path(workspace_root).resolve(strict=True)
        cwd = Path(cwd).resolve(strict=True)
        try:
            cwd_rel = cwd.relative_to(workspace_root).as_posix()
        except ValueError as exc:
            raise PermissionError("sandbox cwd must remain inside the selected workspace") from exc

        image_id = self._prepare_image()
        snapshot = WorkspaceSandbox(workspace_root) if copy_on_write else None
        if snapshot is not None:
            # The snapshot is disposable and contains only filtered workspace
            # files. Make it writable by the unprivileged container uid without
            # changing permissions on the real project.
            try:
                snapshot.root.chmod(0o777)
                for item in snapshot.root.rglob("*"):
                    item.chmod(0o777 if item.is_dir() else 0o666)
            except OSError:
                snapshot.close()
                raise
        source = snapshot.root if snapshot is not None else workspace_root
        self._validate_mount_source(source)

        # Disposable snapshots are owned by SENTRA and may be writable even when
        # the original grant is read+execute only; source files remain untouched.
        mount_readonly = not writable and snapshot is None
        name = "sentra-proc-" + uuid.uuid4().hex
        mount = f"type=bind,source={source},target=/workspace,bind-recursive=disabled"
        if mount_readonly:
            mount += ",readonly"

        workdir = "/workspace" if cwd_rel in {"", "."} else "/workspace/" + cwd_rel
        argv = [
            *self.prefix,
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--label",
            "org.sentra.process-sandbox=1",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--user",
            "65532:65532",
            "--cpus",
            str(self.cpus),
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--pids-limit",
            str(self.pids_limit),
            "--ulimit",
            "nofile=512:512",
            "--init",
            "--log-driver",
            "none",
            "--stop-timeout",
            "1",
            "--workdir",
            workdir,
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
            "--mount",
            mount,
            "--env",
            "HOME=/tmp",
            "--env",
            "TMPDIR=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint",
            "/usr/bin/env",
            image_id,
            "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "HOME=/tmp",
            "TMPDIR=/tmp",
            "PYTHONDONTWRITEBYTECODE=1",
            *[str(item) for item in command],
        ]
        return PreparedProcess(
            argv=tuple(argv),
            host_cwd=workspace_root,
            container_name=name,
            image_id=image_id,
            snapshot=snapshot,
            mode="sandbox" if copy_on_write else "workspace",
            source_readonly=mount_readonly,
            network="none",
        )

    def cleanup_container(self, name: str | None) -> None:
        if not name:
            return
        try:
            subprocess.run(
                [*self.prefix, "rm", "--force", name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                shell=False,
            )
        except Exception:
            pass
