"""Cloud-side device management and remote invocation service."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .store import RemoteStore


class RemoteGatewayService:
    def __init__(self, store: RemoteStore, *, poll_interval_s: float = 0.1) -> None:
        self.store = store
        self.poll_interval_s = max(0.02, float(poll_interval_s))

    def start_pairing(
        self,
        user_id: str,
        name: str,
        platform: str,
        allowed_tools: list[str],
        ttl_s: int = 300,
    ) -> dict[str, Any]:
        return self.store.create_pairing(user_id, name, platform, allowed_tools, ttl_s=ttl_s)

    def list_devices(self, user_id: str) -> dict[str, Any]:
        return {"devices": self.store.list_devices(user_id)}

    def ping(self, user_id: str, device_id: str) -> dict[str, Any]:
        return self.store.get_device(user_id, device_id)

    def who_am_i(self, user_id: str, scopes: list[str] | None = None) -> dict[str, Any]:
        return {
            "subject": user_id,
            "scopes": list(scopes or []),
            "devices": self.store.list_devices(user_id),
        }

    def set_permissions(self, user_id: str, device_id: str, allowed_tools: list[str]) -> dict[str, Any]:
        return self.store.set_device_tools(user_id, device_id, allowed_tools)

    def disconnect(self, user_id: str, device_id: str) -> dict[str, Any]:
        self.store.revoke_device(user_id, device_id)
        return {"device_id": device_id, "status": "REVOKED"}

    def submit(
        self,
        user_id: str,
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: int = 180,
    ) -> dict[str, Any]:
        job_id = self.store.submit_job(user_id, device_id, tool, arguments, timeout_s=timeout_s)
        return {"job_id": job_id, "state": "QUEUED"}

    def result(self, user_id: str, job_id: str) -> dict[str, Any]:
        return self.store.job_result(user_id, job_id)

    def cancel(self, user_id: str, job_id: str) -> dict[str, Any]:
        self.store.cancel_job(user_id, job_id)
        return self.store.job_result(user_id, job_id)

    def invoke(
        self,
        user_id: str,
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: int = 180,
        wait_s: float | None = None,
    ) -> dict[str, Any]:
        job_id = self.store.submit_job(user_id, device_id, tool, arguments, timeout_s=timeout_s)
        deadline = time.monotonic() + (float(wait_s) if wait_s is not None else min(timeout_s + 5, 3605))
        while time.monotonic() < deadline:
            state = self.store.job_result(user_id, job_id)
            if state["state"] in {"COMPLETED", "FAILED", "UNCERTAIN", "CANCELLED"}:
                return state
            time.sleep(self.poll_interval_s)
        return {"job_id": job_id, "state": "PENDING", "message": "job continues remotely"}

    def shutdown_agent(self, user_id: str, device_id: str, *, timeout_s: int = 30) -> dict[str, Any]:
        return self.invoke(
            user_id,
            device_id,
            "system.shutdown_agent",
            {},
            timeout_s=timeout_s,
            wait_s=timeout_s + 2,
        )
