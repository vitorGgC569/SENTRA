"""Docker-isolated, one-shot MCPB stdio effect, called ONLY by the central facade.

No user-supplied Docker executable/image/flags, ambient network or workspace
mount. Every tool call is a *single* centrally reserved and fenced operation.
The subprocess is never cached or shared between WorkItems.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping, Any

from sentra_interop.central import CentralInteropAdapter
from sentra_interop.mcp_stdio import MCPStdioClient, MAX_FRAME, _minimal_windows_runtime_env
from sentra_runtime.contracts import Machine, Capability, OperationRequest
from sentra_runtime.effect_boundary import CentralEffectContext

_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOOL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_ALLOWED_DOCKER = (
    Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe") if os.name == "nt"
    else Path("/usr/bin/docker")
)
_MAX_ARGS = 16_384


def _trusted_image() -> str:
    # Configured by the SENTRA *host operator*, never by a chat, MCP input,
    # plugin manifest or HTTP request. A mutable Docker tag is forbidden.
    image = os.environ.get("SENTRA_MCPB_SANDBOX_IMAGE_ID", "")
    if not _SHA.fullmatch(image):
        raise PermissionError("MCPB sandbox requires a pinned local Docker image ID")
    return image


def _trusted_docker() -> str:
    path = _ALLOWED_DOCKER
    if (not path.is_file() or path.is_symlink()
            or not path.resolve(strict=True).is_file()):
        raise PermissionError("trusted Docker CLI binary unavailable")
    return str(path)


def _docker_argv(spec: Mapping[str, Any], image_id: str, container_name: str) -> tuple[str, ...]:
    # No user-controlled flags, host credentials, Docker socket or network.
    path = Path(spec["cwd"]).resolve(strict=True)
    entry = Path(spec["args"][1]).resolve(strict=True)
    if not entry.is_relative_to(path) or not entry.is_file():
        raise PermissionError("MCPB entry point no longer confined")
    relative = entry.relative_to(path).as_posix()
    return (
        "run", "--rm", "-i", "--pull=never",
        "--name", container_name, "--network=none", "--read-only",
        "--user", "65534:65534", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=16",
        "--memory=128m", "--cpus=0.5",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
        "--mount", f"type=bind,source={path},target=/bundle,readonly",
        "--workdir", "/bundle", image_id, "python3", "-u", "/bundle/" + relative,
    )


async def _ensure_container_gone(docker: str, name: str, cwd: str) -> None:
    """Explicitly reap an owned Docker container after stdio closes.

    On an unavailable daemon, mark operation UNCERTAIN rather than pretend
    a Windows Docker CLI exit proves the container has terminated.
    """
    async def command(*args):
        child = await asyncio.create_subprocess_exec(
            docker, *args, cwd=cwd, env=_minimal_windows_runtime_env(),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(child.communicate(), timeout=4)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()
            raise RuntimeError("MCPB Docker cleanup timed out")
        return child.returncode, out

    query = ("container", "ls", "--all", "--filter", f"name=^/{name}$",
             "--format", "{{.Names}}")
    rc, out = await command(*query)
    if rc != 0:
        raise RuntimeError("MCPB Docker cleanup status unavailable")
    if name in out.decode("utf-8", errors="replace").splitlines():
        await command("container", "rm", "--force", name)
        rc, out = await command(*query)
        if rc != 0 or name in out.decode("utf-8", errors="replace").splitlines():
            raise RuntimeError("MCPB Docker container still running or unreconciled")


async def _isolated_effect(
    *, docker: str, spec: Mapping[str, Any], image_id: str, request: OperationRequest,
    gate, context: CentralEffectContext, allowed_tool: str, revalidate,
) -> dict:
    # Effect entered under central physical lock, durable lease and live grant.
    await revalidate()
    context.checkpoint()
    op_digest = hashlib.sha256(request.operation_id.encode()).hexdigest()[:32]
    # Salted per attempt; a collision cannot force us to remove another container.
    import secrets
    name = "sentra-mcpb-" + op_digest[:14] + "-" + secrets.token_hex(5)
    argv = _docker_argv(spec, image_id, name)
    await revalidate()
    context.checkpoint()
    proc = await asyncio.create_subprocess_exec(
        docker, *argv, cwd=str(Path(spec["cwd"]).resolve()),
        env=_minimal_windows_runtime_env(),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=MAX_FRAME + 1,
    )
    client = MCPStdioClient(proc, gate, server_id=spec["server_id"])
    try:
        await client.initialize(timeout=4)
        await revalidate()
        context.checkpoint()
        listing = OperationRequest(
            request.operation_id + "-discovery", request.principal_id,
            request.machine_id, "mcp:list", request.work_item_id,
            request.idempotency_key + "-discovery",
            {"server_id": spec["server_id"]},
        )
        tools = await client.list_tools(listing, timeout=4)
        if allowed_tool not in tools:
            raise PermissionError("MCPB tool not in observed sandbox MCP inventory")
        await revalidate()
        context.checkpoint()
        response = await asyncio.wait_for(client.call_tool_authorized(
            request, allowed_tool, request.arguments["arguments"]), timeout=8)
        await revalidate()
        context.checkpoint()
        data = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(data) > 16_384:
            raise ValueError("MCPB tool reply exceeds public response budget")
        return dict(response)
    finally:
        # Never retain an ungoverned server between Operations. --rm removes
        # normal Docker runs; unexpected host crashes still require reconciliation.
        try:
            await asyncio.shield(client.close())
        finally:
            await asyncio.shield(_ensure_container_gone(docker, name, str(spec["cwd"])))


async def execute_bundle_tool(
    control, *, owner: str, workspace: str, package_sha256: str,
    run_id: str, work_item_id: str, agent_id: str, tool_name: str,
    arguments: Mapping[str, Any], operation_id: str, idempotency_key: str,
):
    """Call only from the trusted ControlPlaneService (not arbitrary plugin code)."""
    if (not isinstance(tool_name, str) or not _TOOL.fullmatch(tool_name)
            or not isinstance(arguments, Mapping) or not isinstance(operation_id, str)
            or not operation_id or not isinstance(idempotency_key, str) or not idempotency_key):
        raise ValueError("invalid MCPB tool call identity")
    encoded = json.dumps(dict(arguments), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > _MAX_ARGS:
        raise ValueError("MCPB arguments oversized")
    # Check mcp:launch using the existing central WorkItem and plugin provenance.
    spec = control.bundle_activation_plan(owner, workspace, package_sha256,
        run_id=run_id, work_item_id=work_item_id, agent_id=agent_id)
    image_id, docker = _trusted_image(), _trusted_docker()
    # A grant to discover is separate from a grant to execute a named tool.
    tool_cap = "mcp:" + tool_name
    machine = Machine(spec["machine_id"], "mcpb", owner, (
        Capability("mcp:launch", "MCPB launch"),
        Capability("mcp:list", "MCPB tool discovery"),
        Capability(tool_cap, "MCPB named tool"),
    ))
    adapter = CentralInteropAdapter(control=control, run_id=run_id,
                                    owner=owner, machine=machine)
    gate = adapter.protocol_gate()
    request = OperationRequest(operation_id, agent_id, machine.machine_id,
        tool_cap, work_item_id, idempotency_key,
        {"server_id": spec["server_id"], "tool_name": tool_name,
         "arguments": json.loads(encoded)})
    # No Docker process is created if any of these independently scoped
    # grants is absent. Also revalidate inside the physical boundary.
    discover = OperationRequest(operation_id + "-discovery", agent_id,
        machine.machine_id, "mcp:list", work_item_id, idempotency_key + "-discovery",
        {"server_id": spec["server_id"]})
    if not (await gate.decision(discover)).allowed:
        raise PermissionError("MCPB tool discovery grant denied")
    if not (await gate.decision(request)).allowed:
        raise PermissionError("MCPB named tool grant denied")

    async def effect():
        # Check registration, immutable entry point, and launch grant again
        # immediately before creating the isolated server subprocess.
        renewed = control.bundle_activation_plan(owner, workspace, package_sha256,
            run_id=run_id, work_item_id=work_item_id, agent_id=agent_id)
        if renewed["entry_sha256"] != spec["entry_sha256"] or renewed["args"] != spec["args"]:
            raise PermissionError("MCPB artifact changed between admission and effect")
        context = gate.physical_context(request)
        async def revalidate():
            # A revocation of launch OR discovery OR tool capability must
            # interrupt the compound operation before the next MCP effect.
            current = control.bundle_activation_plan(owner, workspace, package_sha256,
                run_id=run_id, work_item_id=work_item_id, agent_id=agent_id)
            if current["entry_sha256"] != spec["entry_sha256"]:
                raise PermissionError("MCPB provenance revoked or mutated")
            if not (await gate.decision(discover)).allowed:
                raise PermissionError("MCPB discovery grant revoked")
            if not (await gate.decision(request)).allowed:
                raise PermissionError("MCPB tool grant revoked")
            context.checkpoint()
        # The enclosing gate.execute owns the lease. The MCP server lifecycle,
        # including initialize, discovery and call, remains inside its lock.
        return await _isolated_effect(
            docker=docker, spec=renewed, image_id=image_id, request=request,
            gate=gate, context=context, allowed_tool=tool_name,
            revalidate=revalidate)
    return await gate.execute(request, effect, timeout=18)
