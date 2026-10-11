"""Offline, immutable wheelhouse preflight for sandbox-only MCPB dependencies.

No resolver, host pip, repository/network pull, shell or script execution.
The plan is INERT; only the coordinator's centrally fenced Docker operation
may install preverified pure-Python wheels in its throwaway isolated tmpfs.
"""
from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from pathlib import Path

_LOCK = re.compile(r"([a-z0-9][a-z0-9_.-]{0,99})==([0-9]+(?:\.[0-9]+){1,3}) --hash=sha256:([0-9a-f]{64})\Z", re.I)
_WHEEL = re.compile(r"([a-z0-9][a-z0-9_.-]{0,99})-([0-9]+(?:\.[0-9]+){1,3})-py3-none-any\.whl\Z", re.I)
_MAX_WHEELS = 32
_MAX_PACKAGE = 4 * 1024 * 1024
_MAX_ALL = 8 * 1024 * 1024


class OfflineDependencyDenied(PermissionError):
    pass


def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def preflight_offline_wheels(catalog, owner, workspace, package_sha256, governance):
    spec = catalog.launch_spec(owner, workspace, package_sha256, governance)
    root = Path(spec["cwd"]).resolve(strict=True)
    lock = root / "requirements.lock"
    wheel_root = root / "wheels"
    if not lock.exists() and not wheel_root.exists():
        return {"package_sha256": package_sha256, "dependencies": [],
                "installed": False, "no_network": True, "requires_sandbox": True}
    if (not lock.is_file() or lock.is_symlink() or not wheel_root.is_dir()
            or wheel_root.is_symlink() or lock.stat().st_size > 8192):
        raise OfflineDependencyDenied("offline MCPB wheelhouse requires bounded reviewed lock")
    lines = [part.strip() for part in lock.read_text(encoding="ascii").splitlines() if part.strip()]
    if not 1 <= len(lines) <= _MAX_WHEELS:
        raise OfflineDependencyDenied("offline MCPB dependency count outside bound")
    entries = {}
    for item in lines:
        parsed = _LOCK.fullmatch(item)
        if not parsed:
            raise OfflineDependencyDenied("dependency lock must pin version and SHA-256")
        name, version, digest = parsed.groups()
        key = (_normalized(name), version)
        if key in entries:
            raise OfflineDependencyDenied("duplicate offline MCPB distribution")
        entries[key] = digest
    total = 0
    found = set()
    inventory = list(wheel_root.iterdir())
    if len(inventory) != len(entries):
        raise OfflineDependencyDenied("wheelhouse inventory differs from lock")
    for wheel in inventory:
        if (wheel.is_symlink() or not wheel.is_file()
                or not wheel.resolve(strict=True).is_relative_to(root)
                or wheel.stat().st_size > _MAX_PACKAGE):
            raise OfflineDependencyDenied("unsafe or oversized MCPB wheel")
        parsed = _WHEEL.fullmatch(wheel.name)
        if not parsed:
            raise OfflineDependencyDenied("only pinned universal pure-Python wheels supported")
        name, version = parsed.groups()
        key = (_normalized(name), version)
        if key not in entries or key in found or _sha(wheel) != entries[key]:
            raise OfflineDependencyDenied("offline MCPB wheel hash/name/version mismatch")
        found.add(key)
        total += wheel.stat().st_size
        if total > _MAX_ALL:
            raise OfflineDependencyDenied("offline MCPB wheelhouse size bound exceeded")
        with zipfile.ZipFile(wheel) as archive:
            files = archive.infolist()
            if len(files) > 500:
                raise OfflineDependencyDenied("offline wheel contains too many entries")
            size = 0
            seen = set()
            wheel_info = False
            for entry in files:
                path = entry.filename
                parts = path.rstrip("/").split("/")
                if (not path or path.startswith("/") or "\\" in path
                        or any(x in ("", ".", "..") or x.startswith(".") for x in parts)
                        or path.casefold() in seen):
                    raise OfflineDependencyDenied("offline wheel archive traversal/collision")
                seen.add(path.casefold())
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK or entry.flag_bits & 1:
                    raise OfflineDependencyDenied("offline wheel link or encrypted content")
                if entry.is_dir():
                    continue
                size += entry.file_size
                if size > _MAX_PACKAGE:
                    raise OfflineDependencyDenied("offline wheel expanded content too large")
                if path.endswith(".dist-info/WHEEL"):
                    text = archive.read(entry).decode("utf-8")
                    if "Root-Is-Purelib: true" not in text and "Root-Is-Purelib: True" not in text:
                        raise OfflineDependencyDenied("offline wheel must be pure Python")
                    wheel_info = True
                elif not path.endswith((".py", ".pyi", ".txt", ".md", ".json",
                                        ".dist-info/METADATA", ".dist-info/RECORD")):
                    raise OfflineDependencyDenied("offline wheel includes unsupported executable payload")
                if ".data/" in path:
                    raise OfflineDependencyDenied("offline wheel data scripts unsupported")
            if not wheel_info:
                raise OfflineDependencyDenied("offline wheel lacks purelib declaration")
    return {"package_sha256": package_sha256,
            "dependencies": [{"name": name, "version": version, "sha256": digest}
                             for (name, version), digest in sorted(entries.items())],
            "wheels_sha256": hashlib.sha256(
                "\n".join(sorted(entries.values())).encode()).hexdigest(),
            "sandbox_command_candidate": [
                "python3", "-I", "-m", "pip", "install", "--no-index",
                "--require-hashes", "--no-deps", "--no-compile",
                "--no-cache-dir", "--disable-pip-version-check",
                "--only-binary=:all:", "--target=/tmp/sentra-deps",
                "--find-links=/bundle/wheels", "-r", "/bundle/requirements.lock"],
            "installed": False, "no_network": True, "requires_sandbox": True,
            "sandbox_image_must_pin_pip": True}


async def verify_offline_dependencies_in_docker(
    control, *, owner, workspace, package_sha256, run_id,
    work_item_id, agent_id, operation_id, idempotency_key,
):
    """Execute pinned pure wheels inside *owned* Docker under the real durable gate.

    It proves extraction/import in a throwaway isolated container, not a
    persistent dependency installation for later MCP tool calls. The central
    sandbox must incorporate the identical step inside its owned effect.
    """
    import asyncio
    import json
    from sentra_interop.central import CentralInteropAdapter
    from sentra_interop.mcp_stdio import _minimal_windows_runtime_env
    from sentra_runtime.contracts import Capability, Machine, OperationRequest
    from .mcpb_orphans import MCPBDockerOwnership
    from .mcpb_sandbox import _trusted_docker, _trusted_image

    plan = preflight_offline_wheels(
        control.bundle_catalog, owner, workspace, package_sha256, control.governance)
    if not plan["dependencies"]:
        raise OfflineDependencyDenied("no offline dependency wheelhouse to verify")
    spec = control.bundle_catalog.launch_spec(owner, workspace,
                                               package_sha256, control.governance)
    run = control.durable.run_status(run_id, owner)
    work = control.work_item_info(work_item_id, owner)
    if (Path(run["workspace"]).resolve() != Path(workspace).resolve()
            or work["run_id"] != run_id or work["assignee_agent_id"] != agent_id):
        raise OfflineDependencyDenied("offline install requires assigned WorkItem")
    control._agent_from_run(run, agent_id)
    machine = Machine("mcpb-offline-" + package_sha256[:32], "mcpb", owner, (
        Capability("mcp:deps-install", "Offline sandbox dependency admission"),))
    gate = CentralInteropAdapter(control=control, run_id=run_id,
                                 owner=owner, machine=machine).protocol_gate()
    request = OperationRequest(operation_id, agent_id, machine.machine_id,
        "mcp:deps-install", work_item_id, idempotency_key,
        {"package_sha256": package_sha256, "wheels_sha256": plan["wheels_sha256"]})
    if not (await gate.decision(request)).allowed:
        raise OfflineDependencyDenied("offline dependency WorkItem grant denied")
    docker, image = _trusted_docker(), _trusted_image()

    async def command(*args, timeout=8):
        child = await asyncio.create_subprocess_exec(
            docker, *args, cwd=spec["cwd"], env=_minimal_windows_runtime_env(),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(child.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()
            raise OfflineDependencyDenied("Docker offline verification timed out")
        if len(output) > 16_384 or child.returncode:
            raise OfflineDependencyDenied("isolated Docker command failed")
        return output.strip()

    async def effect():
        context = gate.physical_context(request)
        context.checkpoint()
        fresh = preflight_offline_wheels(
            control.bundle_catalog, owner, workspace, package_sha256, control.governance)
        if fresh["wheels_sha256"] != plan["wheels_sha256"]:
            raise OfflineDependencyDenied("offline wheelhouse changed before effect")
        ledger = MCPBDockerOwnership(control)
        claim = ledger.prepare(owner=owner, workspace=workspace,
            run_id=run_id, work_item_id=work_item_id,
            operation_id=operation_id, image_id=image)
        names = [name.replace("-", "_") for name in
                 (item["name"] for item in plan["dependencies"])]
        program = (
            "import json,importlib,os,sys,zipfile;"
            "dest='/tmp/sentra-deps';os.makedirs(dest);"
            "files=sorted(os.listdir('/bundle/wheels'));"
            "[zipfile.ZipFile('/bundle/wheels/'+f).extractall(dest) for f in files];"
            "sys.path.insert(0,dest);"
            "loaded=[importlib.import_module(n).__name__ for n in " +
            repr(names) + "];print(json.dumps({'installed_imports':loaded}))"
        )
        argv = ["create", "--pull=never", "--name", claim["container_name"],
                "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=16",
                "--memory=128m", "--cpus=0.5", "--user", "65534:65534",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
                "--mount", "type=bind,source=" + spec["cwd"] +
                           ",target=/bundle,readonly",
                "--workdir", "/bundle"]
        for k, v in claim["docker_labels"].items():
            argv += ["--label", k + "=" + v]
        argv += [image, "python3", "-I", "-c", program]
        context.checkpoint()
        container_id = (await command(*argv, timeout=10)).decode("ascii")
        # The container must be inspected before any start, never by name alone.
        observed = json.loads((await command(
            "inspect", container_id, timeout=6)).decode())[0]
        ledger.bind(owner, operation_id, observed)
        context.checkpoint()
        response = await command("start", "-a", container_id, timeout=12)
        proof = json.loads(response.decode("utf-8"))
        if proof != {"installed_imports": names}:
            raise OfflineDependencyDenied("offline sandbox imports did not match pinned lock")
        context.checkpoint()
        final = json.loads((await command("inspect", container_id)).decode())[0]
        if (final["Id"] != container_id or final["State"]["Running"]
                or final["State"]["ExitCode"] != 0):
            raise OfflineDependencyDenied("sandbox container exit not verified")
        # Exact-ID cleanup with fresh physical proof. Never remove by PID/name.
        await command("rm", container_id)
        # Negative inspect is expected after verified removal.
        child = await asyncio.create_subprocess_exec(
            docker, "inspect", container_id, cwd=spec["cwd"],
            env=_minimal_windows_runtime_env(), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(child.wait(), timeout=6)
        if child.returncode == 0:
            raise OfflineDependencyDenied("sandbox container still present")
        ledger.mark_cleaned(owner, operation_id, observed_absent=True)
        context.checkpoint()
        return {"installed_imports": names, "container_removed": True,
                "network": "none", "read_only_host": True,
                "persistent_install": False, "worker_started": False}

    return await gate.execute(request, effect, timeout=37)
