"""Central MCPB transport facade: stdio/HTTP/OAuth-PKCE dispatch + lifecycle.

Owner: Pacto. Delegates every effect to the existing central authorities
(bundle catalog, PluginWorkerHost, MCPHttpRegistry, OAuthDPAPIVault,
MCPBSupervisionService, ToolExposureRegistry); this module mints no grants,
starts no subprocess and holds no second database. All mutations require an
active WorkItem binding plus explicit host approval callbacks.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable
from .pacto_authority import require_same_store

MCPB_LIFECYCLE_SIGNATURE = {
    "service": "sentra_mcp.services.mcpb_lifecycle.MCPBLifecycleService",
    "methods": {
        "transport_status": {
            "params": ["owner", "workspace", "server_id"],
            "returns": ["server_id", "registration", "http", "supervision",
                        "grants_created", "worker_started"],
            "effects": "none (read-only projection)",
        },
        "dispatch_tool": {
            "params": ["owner", "workspace", "server_id", "transport",
                       "run_id", "work_item_id", "agent_id", "tool_name",
                       "arguments", "operation_id", "idempotency_key"],
            "effects": "delegates to ControlPlaneService.bundle_call_tool (fenced sandbox stdio) or "
                       "MCPHttpRegistry.execute (http); OAuth bearer from the "
                       "central vault; one OperationRequest per call",
        },
        "restart_ticket": {
            "params": ["owner", "workspace", "server_id"],
            "returns": ["server_id", "ticket", "authorized_cleanup", "performed"],
            "effects": "none (fail-closed ticket for the coordinator's fenced effect)",
        },
        "sandbox_spec": {
            "params": ["owner", "workspace", "package_sha256"],
            "returns": "inert Docker/one-shot spec; requires durable admission",
            "effects": "none",
        },
        "uninstall": {
            "params": ["owner", "workspace", "package_sha256", "approved"],
            "effects": "delegates to MCPBBundleCatalog.uninstall (tombstone, archive kept)",
        },
        "collision_check": {
            "params": ["provider_id", "methods"],
            "returns": "ToolExposureRegistry.conflict_report incl. disabled providers",
            "effects": "none (read-only, no reservation)",
        },
    },
    "transports": ["mcp_stdio", "mcp_http_streamable", "oauth_pkce"],
    "invariants": [
        "name collisions denied even against disabled providers",
        "supervision sweep never performs rm; tickets carry exact IDs",
        "uninstall is a permanent tombstone, never a disk purge of audit bytes",
    ],
}


class MCPBLifecycleService:
    """Read-mostly lifecycle facade bound to one central ControlPlaneService.

    stdio dispatch continues through the governance-gated PluginWorkerHost
    (never a raw session ``_call``). Where Lume's session machinery is needed
    (``sentra_interop/mcp_session.py``: ``MCPProviderSession`` /
    ``MCPSDKProcessClient`` over the official SDK host), the HOST supplies
    that transport with the real central gate injected — raw ``_call`` never
    reaches the renderer and descriptor scripts are never authority.
    """

    def __init__(self, control):
        self.control = control
        self.store = control.store

    def _root(self, workspace) -> str:
        return str(Path(workspace).resolve(strict=True))

    def transport_status(self, owner, workspace, server_id) -> dict[str, Any]:
        root = self._root(workspace)
        registration = None
        try:
            for bundle in self.control.bundle_catalog.list(owner, root):
                record = self.control.bundle_catalog.registration(
                    owner, root, bundle["package_sha256"])
                if record and record["plugin_id"] == server_id:
                    registration = {"package_sha256": bundle["package_sha256"],
                                    "status": record["status"]}
                    break
        except Exception:
            registration = None
        http: dict[str, Any] | None = None
        try:
            row = self.control.mcp_http.get(owner, root, server_id)
            http = {"enabled": bool(row["enabled"]), "streamable": bool(row.get("streamable")),
                    "revision": row.get("revision")}
        except Exception:
            http = None
        try:
            supervision = self.control.mcpb_supervision.status(owner, root)
        except Exception:
            supervision = {"remote_liveness_proved": False}
        return {"server_id": server_id, "workspace": root,
                "registration": registration or "STAGED_OR_ABSENT",
                "http": http or "UNREGISTERED",
                "supervision": supervision,
                "grants_created": False, "worker_started": False}

    async def dispatch_tool(self, *, owner, workspace, server_id, transport,
                            run_id, work_item_id, agent_id, tool_name,
                            arguments, operation_id, idempotency_key,
                            vault=None, verify_host_consent: Callable | None = None):
        """Route one tool call through the existing transport authorities."""
        from .plugin_bundles import MCPBWorkItemLifecycle
        root = self._root(workspace)
        if transport not in ("mcp_stdio", "mcp_http_streamable"):
            raise ValueError("unknown MCPB transport")
        # Resolve the package bound to this server_id via staged bundles.
        package_sha256 = None
        for bundle in self.control.bundle_catalog.list(owner, root):
            record = self.control.bundle_catalog.registration(
                owner, root, bundle["package_sha256"])
            if record and record["plugin_id"] == server_id:
                package_sha256 = bundle["package_sha256"]
                break
        if package_sha256 is None:
            raise PermissionError("MCPB server is not registered in this workspace")
        lifecycle = MCPBWorkItemLifecycle(
            self.control, owner=owner, workspace=root,
            package_sha256=package_sha256, run_id=run_id,
            work_item_id=work_item_id, agent_id=agent_id)
        if transport == "mcp_http_streamable":
            if vault is None:
                raise PermissionError("central OAuth vault required for HTTP transport")
            require_same_store(self.control.store, vault.store)
            return await lifecycle.call_http_tool(
                self.control.mcp_http, vault, name=tool_name,
                arguments=arguments, operation_id=operation_id,
                idempotency_key=idempotency_key)
        # A plugin grant alone is not durable admission for an agent effect.
        # Reuse the actual sandbox stdio pipeline: launch/list/named-tool grants,
        # reservation before process creation, fencing and owned cleanup.
        return await self.control.bundle_call_tool(owner, root, package_sha256,
            run_id=run_id, work_item_id=work_item_id, agent_id=agent_id,
            tool_name=tool_name, arguments=dict(arguments or {}),
            operation_id=operation_id, idempotency_key=idempotency_key)

    def _stdio_workers(self, owner, server_id) -> list[dict[str, Any]]:
        with self.control.store.connect("plugin_worker") as db:
            rows = db.execute(
                "SELECT * FROM plugin_workers WHERE owner=? AND plugin_id=? AND state='READY'",
                (owner, server_id)).fetchall()
        return [dict(row) for row in rows]

    def restart_ticket(self, owner, workspace, server_id) -> dict[str, Any]:
        """Fail-closed restart ticket: never restarts here."""
        root = self._root(workspace)
        workers = self._stdio_workers(owner, server_id)
        live = [w for w in workers
                if self.control.plugin_host.health(w["plugin_worker_id"], owner).get("session_proven")]
        if live:
            return {"server_id": server_id, "ticket": None,
                    "reason": "worker still live; restart refused",
                    "authorized_cleanup": False, "performed": False}
        with self.control.store.connect("plugin_worker") as db:
            failed = db.execute(
                "SELECT plugin_worker_id FROM plugin_workers WHERE owner=? AND plugin_id=? "
                "AND state='FAILED' ORDER BY updated_at DESC LIMIT 1",
                (owner, server_id)).fetchone()
        if failed is None:
            return {"server_id": server_id, "ticket": None,
                    "reason": "no FAILED worker to restart",
                    "authorized_cleanup": False, "performed": False}
        return {"server_id": server_id,
                "ticket": {"failed_worker_id": failed["plugin_worker_id"],
                           "requires": "new durable Operation plugin:restart + host consent + "
                                       "stopped old session + sandbox mode",
                           "via": "PluginWorkerHost.restart_authorized"},
                "authorized_cleanup": False, "performed": False,
                "grants_created": False}

    def sandbox_spec(self, owner, workspace, package_sha256) -> dict[str, Any]:
        """Inert one-shot sandbox plan; launching needs durable admission."""
        from .mcpb_sandbox import _trusted_image  # validates operator-pinned image config
        try:
            _trusted_image()
            image_pinned = True
        except PermissionError:
            image_pinned = False
        spec = self.control.bundle_catalog.launch_spec(
            owner, self._root(workspace), package_sha256,
            self.control.governance)
        return {**spec, "sandbox_image_pinned": image_pinned,
                "network": "none", "one_shot": True, "grants_created": False}

    def uninstall(self, owner, workspace, package_sha256, *, approved=False) -> dict[str, Any]:
        if approved is not True:
            raise PermissionError("explicit operator approval required for MCPB uninstall")
        return self.control.bundle_catalog.uninstall(
            owner, self._root(workspace), package_sha256,
            self.control.governance, approved=True)

    def collision_check(self, provider_id, methods) -> dict[str, Any]:
        """Name-collision pre-check including disabled providers (read-only)."""
        return self.control.tool_exposure.conflict_report(provider_id, methods)
