"""Runtime bridge from paired Remote Agents into OMA scheduler bindings."""
from __future__ import annotations

from typing import Any

from sentra_mcp.config import MCPConfig
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.resource_projection import RemoteResourceProjection
from sentra_remote.gateway import RemoteGatewayService
from sentra_remote.store import RemoteStore


class RemoteSchedulerSession:
    """Own the read/dispatch services used by one OMA CLI process.

    Device eligibility remains fail-closed in RemoteResourceProjection:
    ONLINE + compatible contract + explicit candidate-generation permission.
    """

    def __init__(
        self,
        principal: str,
        *,
        workspace: str | None = None,
        provider: str | None = None,
        config: MCPConfig | None = None,
    ) -> None:
        self.principal = str(principal or "").strip()
        self.workspace = str(workspace or "").strip() or None
        self.provider = str(provider or "").strip() or None
        if not self.principal:
            raise ValueError("remote principal is required")
        if len(self.principal) > 512:
            raise ValueError("remote principal is too long")
        if self.workspace is not None and len(self.workspace) > 256:
            raise ValueError("remote workspace alias is too long")

        self.config = config or MCPConfig.from_env()
        self.store = RemoteStore(self.config.remote_store_path)
        self.durable = DurableRunService(self.config.resolved_state_root)
        self.gateway = RemoteGatewayService(
            self.store,
            durable=self.durable,
        )
        self.projection = RemoteResourceProjection(self.gateway)
        self._closed = False

    def bindings(self) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("remote scheduler session is closed")
        return self.projection.scheduler_bindings(
            self.principal,
            workspace=self.workspace,
            provider=self.provider,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.store.close()
        finally:
            self.durable.close()

    def __enter__(self) -> "RemoteSchedulerSession":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
