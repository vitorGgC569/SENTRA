"""Host-owned Docker boundary. No model text becomes Docker flags or host argv.

Only a filtered, temporary source snapshot is mounted (read-only). Credentials,
the controller checkout, Docker socket and host environment are not mounted.
Containers are a risk reduction boundary, not proof against kernel exploits.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from .command_runner import CommandRunner
from .sandbox import WorkspaceSandbox

DEFAULT_IMAGE = "oma-sandbox:local"
LOCAL_ENDPOINT = ("npipe:////./pipe/dockerDesktopLinuxEngine" if os.name == "nt"
                  else "unix:///var/run/docker.sock")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
LINT_CODE = ("import ast,pathlib,sys; files=list(pathlib.Path('/workspace').rglob('*.py')); "
             "[ast.parse(p.read_bytes(),filename=str(p)) for p in files]; "
             "print('SYNTAX checked='+str(len(files))); sys.exit(0 if files else 1)")


def docker_executable():
    executable = shutil.which("docker")
    if executable:
        return executable
    windows = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    if windows.is_file():
        return str(windows)
    raise ValueError("Docker CLI not found; install/start Docker Desktop")


def settings(value=None):
    result = dict(value or {})
    unknown = set(result) - {"backend", "image"}
    if unknown:
        raise ValueError(f"unknown execution settings: {sorted(unknown)}")
    result.setdefault("backend", "host")
    if result["backend"] not in {"host", "docker"}:
        raise ValueError("execution backend must be host or docker")
    if result["backend"] == "docker":
        result.setdefault("image", DEFAULT_IMAGE)
        if not isinstance(result["image"], str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:/@-]{0,250}", result["image"]):
            raise ValueError("invalid operator-owned Docker image")
    return result


class DockerClient:
    def __init__(self):
        # Explicit local endpoint ignores DOCKER_HOST / context switches to remote machines.
        self.prefix = [docker_executable(), "--host", LOCAL_ENDPOINT]
        self.host = CommandRunner(Path(__file__).resolve().parent)

    async def call(self, args, timeout=20):
        return await self.host.run_argv(self.prefix + list(args), timeout)

    async def checked(self, args, timeout=20):
        result = await self.call(args, timeout)
        if not result["passed"]:
            raise ValueError("DOCKER_UNAVAILABLE: " + result["stderr"][-2000:])
        return result["stdout"]

    async def prepare(self, image):
        info = json.loads(await self.checked(["info", "--format", "{{json .}}"], 15))
        if (info.get("OSType") != "linux" or not all(info.get(k) for k in
                ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit"))
                or not any("name=seccomp" in item for item in info.get("SecurityOptions", []))):
            raise ValueError("Docker requires Linux containers, seccomp and enforced resource limits")
        data = json.loads(await self.checked(["image", "inspect", image]))[0]
        if data.get("Os") != "linux" or not IMAGE_ID.fullmatch(data.get("Id", "")):
            raise ValueError("invalid Linux sandbox image")
        # An image must not add implicit volumes, healthchecks, privileged startup
        # or secrets via its config. Use the operator-built minimal sandbox image.
        config = data.get("Config", {})
        if config.get("Volumes") or config.get("Healthcheck"):
            raise ValueError("sandbox image must not define volumes or healthchecks")
        if (config.get("Labels") or {}).get("org.oma.sandbox") != "1":
            raise ValueError("build the trusted image with scripts/prepare_docker.py --build")
        return data["Id"]


async def prepare_execution(value=None):
    result = settings(value)
    if result["backend"] == "docker":
        result["image"] = await DockerClient().prepare(result["image"])
    return result


def create_runner(root, profiles=None, execution=None):
    config = settings(execution)
    if config["backend"] == "host":
        return CommandRunner(root, profiles)
    return DockerCommandRunner(root, profiles, image=config["image"])


class DockerCommandRunner(CommandRunner):
    def __init__(self, cwd, profiles=None, *, image=DEFAULT_IMAGE):
        super().__init__(cwd, profiles)
        self.image = settings({"backend": "docker", "image": image})["image"]
        self.client = DockerClient()

    def resolve_command(self, command):
        from repository.parser import parse
        directive = parse(command) if isinstance(command, str) else None
        if directive and directive.operation == "LINT" and not directive.args and "LINT" not in self.profiles:
            return ["python", "-I", "-c", LINT_CODE]
        argv = super().resolve_command(command)
        # Profiles describe Linux/container argv. Default pytest paths and the
        # host Python executable must be translated before crossing the boundary.
        translated = []
        for arg in argv:
            if arg == sys.executable:
                translated.append("python")
            elif Path(arg).is_absolute():
                try:
                    translated.append("/workspace/" + Path(arg).relative_to(self.cwd).as_posix())
                except ValueError:
                    if os.name == "nt" and ":" in arg:
                        raise ValueError("host paths outside candidate cannot enter container profiles")
                    translated.append(arg)
            else:
                translated.append(arg)
        return translated

    def create_args(self, name, snapshot, argv):
        # Generated temp paths can still contain commas from a user profile name.
        # Reject rather than let Docker's CSV mount grammar reinterpret the path.
        if any(c in str(snapshot) for c in (",", "\n", "\r", '"')):
            raise ValueError("unsupported snapshot path for Docker mount")
        return ["create", "--name", name, "--label", "org.oma.sandbox=1", "--pull", "never",
                "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges=true", "--user", "65532:65532",
                "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
                "--pids-limit", "64", "--ulimit", "nofile=256:256", "--init",
                "--log-driver", "none", "--stop-timeout", "1", "--workdir", "/workspace",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
                "--mount", f"type=bind,source={snapshot},target=/workspace,readonly,bind-recursive=disabled",
                "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
                "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTEST_ADDOPTS=-p no:cacheprovider",
                # Clear image entrypoint; argv is passed after the immutable image ID.
                "--entrypoint", "/usr/bin/env", self.image, "-i",
                "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp", "TMPDIR=/tmp",
                "PYTHONDONTWRITEBYTECODE=1", "PYTEST_ADDOPTS=-p no:cacheprovider", *argv]

    async def run_argv(self, argv, timeout=120):
        if isinstance(argv, (str, bytes)) or not argv or timeout <= 0:
            raise ValueError("structured argv and positive timeout required")
        snapshot = None
        name = "oma-check-" + uuid.uuid4().hex
        attempted_create = False
        result = self._result(list(argv), False, -1)
        try:
            # No pulls/builds, no host fallback. Pin the actual local image ID.
            self.image = await self.client.prepare(self.image)
            snapshot = WorkspaceSandbox(self.cwd)
            # Linux host temp dirs default to 0700; only this filtered disposable
            # copy becomes readable by the unprivileged container user.
            snapshot.root.chmod(0o755)
            for path in snapshot.root.rglob("*"):
                path.chmod(0o755 if path.is_dir() else 0o644)
            args = self.create_args(name, snapshot.root, list(argv))
            attempted_create = True
            await self.client.checked(args)
            result = await self.client.call(["start", "--attach", name], timeout)
            state = json.loads(await self.client.checked(["inspect", "--format", "{{json .State}}", name]))
            result["passed"] = bool(result["passed"] and state.get("Status") == "exited"
                                    and state.get("ExitCode") == 0 and not state.get("OOMKilled"))
            result["container_state"] = state
        except asyncio.CancelledError:
            raise
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            result = self._result(list(argv), False, -1, stderr=f"SANDBOX_BLOCKED: {exc}")
        finally:
            if attempted_create:
                # Killing the Docker CLI does not kill a container. Always remove
                # this exact, run-owned name, including on timeout/cancellation.
                cleanup = await asyncio.shield(self.client.call(["rm", "--force", name], 15))
                result["cleanup_ok"] = cleanup["passed"]
                if not cleanup["passed"]:
                    result["passed"] = False
                    result["stderr"] += "\nCONTAINER_CLEANUP_FAILED: " + name
            if snapshot:
                snapshot.close()
        result.update(command=list(argv), execution_backend="docker", image_id=self.image,
                      container_name=name, network="none", source_readonly=True)
        return result
