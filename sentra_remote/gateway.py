from __future__ import annotations

import time
import uuid
from typing import Any

from sentra_mcp.errors import SentraSemanticError
from .store import RemoteStore


_REMOTE_TERMINAL = {"COMPLETED", "FAILED", "UNCERTAIN", "CANCELLED"}
_DURABLE_TERMINAL = {"SUCCEEDED", "FAILED", "UNCERTAIN", "CANCELLED"}


class RemoteGatewayService:
    def __init__(
        self,
        store: RemoteStore,
        *,
        durable: Any | None = None,
        poll_interval_s: float = 0.1,
    ) -> None:
        self.store = store
        self.durable = durable
        self.poll_interval_s = max(0.02, float(poll_interval_s))

    def start_pairing(
        self,
        user_id: str,
        name: str,
        platform: str,
        allowed_tools: list[str],
        ttl_s: int = 300,
    ) -> dict[str, Any]:
        return self.store.create_pairing(
            user_id, name, platform, allowed_tools, ttl_s=ttl_s
        )

    def list_devices(self, user_id: str) -> dict[str, Any]:
        items = self.store.list_devices(user_id)
        return {
            "items": items,
            "devices": items,
            "page": {
                "offset": 0,
                "limit": len(items),
                "returned": len(items),
                "total": len(items),
                "next_offset": None,
            },
        }

    def ping(self, user_id: str, device_id: str) -> dict[str, Any]:
        return self.store.get_device(user_id, device_id)

    def who_am_i(
        self,
        user_id: str,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        devices = self.store.list_devices(user_id)
        return {
            "subject": user_id,
            "scopes": list(scopes or []),
            "devices": devices,
        }

    def set_permissions(
        self,
        user_id: str,
        device_id: str,
        allowed_tools: list[str],
    ) -> dict[str, Any]:
        return self.store.set_device_tools(user_id, device_id, allowed_tools)

    def disconnect(self, user_id: str, device_id: str) -> dict[str, Any]:
        self.store.revoke_device(user_id, device_id)
        return {"device_id": device_id, "status": "REVOKED"}

    def _device_contract(
        self,
        user_id: str,
        device_id: str,
        *,
        tool: str | None = None,
    ) -> dict[str, Any]:
        """Fail closed when a remote target cannot prove its loaded contract/build."""
        device = self.store.get_device(user_id, device_id)
        compatibility = dict(device.get("compatibility") or {})
        if not compatibility.get("compatible", False):
            reasons = list(compatibility.get("reasons") or [])
            first = reasons[0] if reasons else {
                "code": "REMOTE_AGENT_STALE",
                "message": "remote agent contract identity is unavailable",
            }
            raise SentraSemanticError(
                str(first.get("code") or "REMOTE_AGENT_STALE"),
                str(first.get("message") or "remote agent contract identity is incompatible"),
                category="contract",
                retryable=str(first.get("code") or "") == "REMOTE_AGENT_STALE",
                details={"device_id": device_id, "reasons": reasons},
            )

        server = dict(compatibility.get("server") or {})
        contract = dict(compatibility.get("contract") or {})
        tool_names = {
            str(name)
            for name in (contract.get("tool_names") or [])
            if str(name)
        }
        if tool and tool != "system.shutdown_agent" and tool not in tool_names:
            raise SentraSemanticError(
                "CAPABILITY_MISSING",
                "remote agent does not advertise the requested tool",
                category="contract",
                retryable=False,
                details={"device_id": device_id, "tool": tool},
            )
        return {
            "device_id": device_id,
            "status": device.get("status"),
            "protocol_version": server.get("protocol_version"),
            "capability_version": server.get("capability_version"),
            "build_id": server.get("build_id"),
            "fingerprint": server.get("fingerprint"),
            "source_hash": server.get("source_hash"),
            "executable_sha256": server.get("executable_sha256"),
            "schema_hash": contract.get("schema_hash"),
            "tool_count": contract.get("tool_count"),
            "tool_verified": tool is None or tool == "system.shutdown_agent" or tool in tool_names,
        }

    def _begin_operation(
        self,
        user_id: str,
        device_id: str,
        tool: str,
        *,
        run_id: str | None,
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if self.durable is None:
            return None, None
        if run_id:
            run = self.durable.run_status(run_id, user_id)
        else:
            run = self.durable.ensure_implicit_run(
                user_id, workspace=f"remote:{device_id}"
            )
        rid = str(run["run_id"])
        key = str(idempotency_key or "").strip() or (
            f"remote:{device_id}:{tool}:{uuid.uuid4().hex}"
        )
        operation = self.durable.create_operation(
            rid,
            user_id,
            kind=f"remote.{tool}",
            idempotency_key=key,
        )
        oid = str(operation["operation_id"])
        context = {
            "run_id": rid,
            "operation_id": oid,
            "idempotency_key": key,
            "owner": user_id,
            "device_id": device_id,
            "tool": tool,
        }
        if operation.get("idempotent_replay"):
            existing = self.store.job_for_operation(user_id, oid)
            if existing is not None:
                projected = self._project_remote(user_id, existing)
                projected["idempotent_replay"] = True
                return None, projected
            if operation["state"] not in _DURABLE_TERMINAL:
                try:
                    operation = self.durable.update_operation(
                        oid,
                        user_id,
                        state="UNCERTAIN",
                        progress={
                            "stage": "UNCERTAIN",
                            "reason": "operation exists but remote job is absent",
                        },
                        event_type="REMOTE_JOB_CORRELATION_LOST",
                        error={
                            "code": "REMOTE_JOB_CORRELATION_LOST",
                            "message": (
                                "durable operation exists but no persisted "
                                "remote job can prove whether submission occurred"
                            ),
                        },
                    )
                except Exception:
                    operation = self.durable.operation_status(oid, user_id)
            return None, {
                **context,
                "idempotent_replay": True,
                "operation": operation,
                "state": operation["state"],
                "semantic_status": (
                    operation["state"]
                    if operation["state"] in _DURABLE_TERMINAL
                    else "OPERATION_STILL_RUNNING"
                ),
            }
        self.durable.update_operation(
            oid,
            user_id,
            state="STARTING",
            progress={
                "stage": "SUBMITTING",
                "device_id": device_id,
                "tool": tool,
            },
            event_type="REMOTE_JOB_STARTING",
        )
        return context, None

    def _project_remote(
        self,
        user_id: str,
        remote: dict[str, Any],
    ) -> dict[str, Any]:
        data = dict(remote)
        oid = str(data.get("operation_id") or "")
        if self.durable is None or not oid:
            return data

        remote_state = str(data.get("state") or "")
        mapped = {
            "QUEUED": "WAITING_EXTERNAL",
            "LEASED": "RUNNING",
            "COMPLETED": "SUCCEEDED",
            "FAILED": "FAILED",
            "UNCERTAIN": "UNCERTAIN",
            "CANCELLED": "CANCELLED",
        }.get(remote_state)
        if mapped is None:
            return data

        try:
            current = self.durable.operation_status(oid, user_id)
            if current["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                readiness = (
                    "PRODUCT_READY"
                    if mapped == "SUCCEEDED"
                    else "TRANSPORT_CONNECTED"
                    if remote_state == "LEASED"
                    else None
                )
                error = None
                if mapped in {"FAILED", "UNCERTAIN"}:
                    error = {
                        "code": (
                            "REMOTE_JOB_UNCERTAIN"
                            if mapped == "UNCERTAIN"
                            else "REMOTE_JOB_FAILED"
                        ),
                        "message": str(data.get("error") or "")[:1000],
                    }
                self.durable.update_operation(
                    oid,
                    user_id,
                    state=mapped,
                    readiness=readiness,
                    progress={
                        "stage": remote_state,
                        "job_id": data.get("job_id"),
                        "device_id": data.get("device_id"),
                        "phase": data.get("phase"),
                        "requeues": data.get("requeues"),
                    },
                    event_type=f"REMOTE_JOB_{remote_state}",
                    result=data if mapped == "SUCCEEDED" else None,
                    error=error,
                )
        except Exception:
            pass

        if remote_state not in _REMOTE_TERMINAL:
            data["semantic_status"] = "OPERATION_STILL_RUNNING"
        return data

    def submit(
        self,
        user_id: str,
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: int = 180,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] | None = None
        try:
            contract = self._device_contract(user_id, device_id, tool=tool)
            context, replay = self._begin_operation(
                user_id,
                device_id,
                tool,
                run_id=run_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return replay
            job_id = self.store.submit_job(
                user_id,
                device_id,
                tool,
                arguments,
                timeout_s=timeout_s,
                run_id=context["run_id"] if context else None,
                operation_id=context["operation_id"] if context else None,
                idempotency_key=context["idempotency_key"] if context else idempotency_key,
                require_compatible_agent=True,
            )
            if context is not None and self.durable is not None:
                self.durable.update_operation(
                    context["operation_id"],
                    user_id,
                    state="WAITING_EXTERNAL",
                    progress={
                        "stage": "QUEUED",
                        "job_id": job_id,
                        "device_id": device_id,
                        "tool": tool,
                        "target_contract": contract,
                    },
                    event_type="REMOTE_JOB_QUEUED",
                )
            return self._project_remote(
                user_id,
                self.store.job_result(user_id, job_id),
            )
        except Exception as exc:
            if context is not None and self.durable is not None:
                try:
                    self.durable.update_operation(
                        context["operation_id"],
                        user_id,
                        state="FAILED",
                        event_type="REMOTE_JOB_SUBMIT_FAILED",
                        error={
                            "code": "REMOTE_JOB_SUBMIT_FAILED",
                            "message": str(exc)[:1000],
                        },
                    )
                except Exception:
                    pass
            raise

    def result(self, user_id: str, job_id: str) -> dict[str, Any]:
        return self._project_remote(
            user_id,
            self.store.job_result(user_id, job_id),
        )

    def cancel(self, user_id: str, job_id: str) -> dict[str, Any]:
        self.store.cancel_job(user_id, job_id)
        return self.result(user_id, job_id)

    def invoke(
        self,
        user_id: str,
        device_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        timeout_s: int = 180,
        wait_s: float | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        submitted = self.submit(
            user_id,
            device_id,
            tool,
            arguments,
            timeout_s=timeout_s,
            run_id=run_id,
            idempotency_key=idempotency_key,
        )
        job_id = submitted.get("job_id")
        if not job_id:
            return submitted
        if str(submitted.get("state") or "") in _REMOTE_TERMINAL:
            return submitted

        requested_wait = 25.0 if wait_s is None else float(wait_s)
        if requested_wait <= 0:
            requested_wait = 0.01
        window = min(requested_wait, 25.0)
        deadline = time.monotonic() + window
        last = submitted
        while time.monotonic() < deadline:
            state = self.result(user_id, str(job_id))
            last = state
            if state["state"] in _REMOTE_TERMINAL:
                return state
            time.sleep(
                min(
                    self.poll_interval_s,
                    max(0.01, deadline - time.monotonic()),
                )
            )

        pending = dict(last)
        pending["remote_state"] = pending.get("state")
        pending["state"] = "PENDING"
        pending["wait_timed_out"] = True
        pending["semantic_status"] = "OPERATION_STILL_RUNNING"
        pending["message"] = "job continues remotely"
        pending["next_poll_after_ms"] = 250
        return pending

    def shutdown_agent(
        self,
        user_id: str,
        device_id: str,
        *,
        timeout_s: int = 30,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.invoke(
            user_id,
            device_id,
            "system.shutdown_agent",
            {},
            timeout_s=timeout_s,
            wait_s=min(timeout_s + 2, 25),
            run_id=run_id,
            idempotency_key=idempotency_key,
        )
