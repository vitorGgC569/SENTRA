from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from sentra_mcp.services.durable import DurableRunService, DurableStateConflict
from sentra_mcp.services.task_ledger import DurableTaskLedger


class DurableResourceLeaseManager:
    """Cross-process/cross-Run resource leases for OMA task scheduling.

    PriorityTaskQueue remains the fast in-process admission layer. This manager
    adds the durable authority boundary: resources are namespaced by project
    workspace and fenced through DurableRunService.
    """

    def __init__(
        self,
        state_root: Path | str,
        *,
        workspace: Path | str,
        logical_run_id: str,
        owner: str | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.logical_run_id = str(logical_run_id)
        workspace_key = hashlib.sha256(
            str(self.workspace).encode("utf-8")
        ).hexdigest()[:24]
        self.workspace_key = workspace_key
        self.owner = str(owner or f"oma:{workspace_key}")
        self.durable = DurableRunService(Path(state_root))
        self.task_ledger = DurableTaskLedger(Path(state_root))
        stable = hashlib.sha256(
            (str(self.workspace) + "\0" + self.logical_run_id).encode("utf-8")
        ).hexdigest()[:32]
        run = self.durable.create_run(
            self.owner,
            workspace=str(self.workspace),
            idempotency_key=f"oma-resource-run:{stable}",
            required_capabilities=[],
        )
        self.durable_run_id = str(run["run_id"])

    def _resource_key(self, logical_resource: str) -> str:
        logical = str(logical_resource or "").strip().replace("\\", "/").lower()
        digest = hashlib.sha256(logical.encode("utf-8")).hexdigest()[:32]
        prefix = logical.split(":", 1)[0][:24] if ":" in logical else "resource"
        return f"oma:{self.workspace_key}:{prefix}:{digest}"

    @staticmethod
    def _operation_id(task: Any) -> str:
        raw = f"{getattr(task, 'run_id', '')}\0{getattr(task, 'id', '')}"
        return "oma-task-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _ttl_for(task: Any) -> float:
        timeout = float(getattr(task, "timeout_s", 900.0) or 900.0)
        heartbeat = float(getattr(task, "heartbeat_timeout_s", 120.0) or 120.0)
        return min(3600.0, max(60.0, timeout + heartbeat + 30.0))

    def acquire(self, task: Any, resources: Iterable[str]) -> list[dict[str, Any]] | None:
        acquired: list[dict[str, Any]] = []
        operation_id = self._operation_id(task)
        ttl_s = self._ttl_for(task)
        try:
            for logical in sorted({str(item) for item in resources if str(item)}):
                lease = self.durable.acquire_lease(
                    self.durable_run_id,
                    self.owner,
                    self._resource_key(logical),
                    operation_id=operation_id,
                    ttl_s=ttl_s,
                )
                acquired.append({
                    **lease,
                    "logical_resource": logical,
                })
        except DurableStateConflict:
            self.release(acquired)
            return None
        except Exception:
            self.release(acquired)
            raise
        return acquired

    def renew(self, leases: Iterable[dict[str, Any]], task: Any) -> list[dict[str, Any]]:
        renewed: list[dict[str, Any]] = []
        ttl_s = self._ttl_for(task)
        for item in leases:
            result = self.durable.renew_lease(
                str(item["resource_key"]),
                self.owner,
                int(item["fencing_token"]),
                ttl_s=ttl_s,
            )
            renewed.append({
                **item,
                **result,
            })
        return renewed

    def release(self, leases: Iterable[dict[str, Any]]) -> None:
        for item in reversed(list(leases)):
            try:
                self.durable.release_lease(
                    str(item["resource_key"]),
                    self.owner,
                    int(item["fencing_token"]),
                )
            except Exception:
                # Release is best-effort here; TTL/fencing remains the final
                # authority if a process dies between task settlement and cleanup.
                continue

    def sync_task(self, task: Any, *, recovery: bool = False) -> dict[str, Any]:
        payload = task.to_dict() if hasattr(task, "to_dict") else dict(task)
        return self.task_ledger.sync(
            self.durable_run_id,
            self.owner,
            payload,
            recovery=bool(recovery),
        )

    def task_info(self, task_id: str) -> dict[str, Any]:
        return self.task_ledger.task_info(
            self.durable_run_id, self.owner, str(task_id)
        )

    def list_tasks(self, *, states: list[str] | None = None) -> dict[str, Any]:
        return self.task_ledger.list_tasks(
            self.durable_run_id, self.owner, states=states
        )

    def admit_after_incident(
        self,
        task: Any,
        resources: Iterable[str],
        *,
        incident: str,
        operation_state: str | None = None,
    ) -> dict[str, Any]:
        """Decide whether a later admission could acquire. This method never does.

        After crash, canvas close, relay loss or reboot, QUEUED is not proof
        that the effect is unstarted. Only an explicit NOT_STARTED or ABSENT
        state, with no may_have_started flag, is eligible. Eligibility is not
        an acquire.
        """
        if incident not in {"crash", "canvas_closed", "relay_down", "reboot"}:
            raise ValueError("incident must be crash, canvas_closed, relay_down or reboot")
        logical = sorted({str(item) for item in resources if str(item)})
        meta = getattr(task, "metadata", None)
        if not isinstance(meta, dict):
            meta = {}
        state = operation_state if operation_state is not None else meta.get("effect_state")
        unstarted = state in {None, "", "NOT_STARTED", "ABSENT"} and meta.get("may_have_started") is not True
        settled = state in {"SUCCEEDED", "FAILED", "CANCELLED"}
        return {
            "incident": incident,
            "operation_state": state,
            "may_acquire": bool(unstarted and not settled),
            "may_release": False,
            "acquired": False,
            "released": False,
            "automatic_retry": False,
            "effects_executed": 0,
            "resource_count": len(logical),
        }

    def close(self) -> None:
        self.durable.close()
