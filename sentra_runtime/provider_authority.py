"""Protected, operation-bound authority configuration for the trusted CLI child."""
import hashlib
import os
from pathlib import Path
import time

from sentra_core.conversations import _encode, _decode


ENVIRONMENT_KEY = "SENTRA_CONTROL_BINDING_FILE"


def prepare_provider_binding(control, *, state_root, owner, principal, conversation_id,
                             run_id, work_item_id, operation_id, project_id, ttl_seconds=3600):
    if control.store.backend == "sqlite":
        return {"environment": {}, "backend": "sqlite"}
    control.store.assert_principal(owner)
    if owner != "canvas:" + principal or type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 3600:
        raise PermissionError("trusted Canvas CLI provider binding required")
    run = control.durable.run_status(run_id, owner, include_details=False)
    work = control.work_item_info(work_item_id, owner)
    operation = control.durable.operation_status(operation_id, owner)
    actor = control.durable.agent_info(work["assignee_agent_id"],owner)
    if (run["state"] != "RUNNING" or work["run_id"] != run_id or work["state"] != "RUNNING"
            or work["metadata"].get("workspace_id") != project_id or operation["run_id"] != run_id
            or operation["state"] not in {"STARTING", "RUNNING"}
            or actor["run_id"] != run_id or actor["desired_state"] == "WAITING"):
        raise PermissionError("CLI provider is not bound to current native execution")
    progress = operation.get("progress",{})
    linked = progress.get("work_item_id") == work_item_id and progress.get("principal_id") == work["assignee_agent_id"]
    legacy_linked = (operation["kind"] == "canvas.agent_task" and progress.get("canvas_task_id") == work["metadata"].get("canvas_task_id")
                     and progress.get("agent_id") == work["assignee_agent_id"] and work["metadata"].get("operation_id") == operation_id)
    if not linked and not legacy_linked:
        raise PermissionError("CLI provider Operation is not bound to this WorkItem/assignee")
    root = Path(state_root).resolve()
    directory = root / "provider-authority"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = hashlib.sha256((owner + "\x00" + operation_id).encode()).hexdigest()
    path = directory / (identity + ".protected")
    value = {"version": 1, "backend": "postgres", "dsn": control.store._dsn,
        "tenant_id": control.store.tenant_id, "principal_id": control.store.principal_id,
        "principal": principal, "source_root": str(root), "owner": owner, "conversation_id": conversation_id,
        "project_id": project_id, "run_id": run_id, "work_item_id": work_item_id, "operation_id": operation_id,
        "agent_id": work["assignee_agent_id"], "authority_revision":control.store._selection_revision,
        "expires_at": time.time() + ttl_seconds}
    temporary = path.with_suffix(".pending")
    temporary.write_text(_encode(value), encoding="utf-8")
    temporary.replace(path)
    return {"environment": {ENVIRONMENT_KEY: str(path)}, "backend": "postgres", "operation_id": operation_id}


def load_provider_binding(state_root):
    selector = os.environ.get(ENVIRONMENT_KEY)
    if not selector:
        return None
    root = Path(state_root).resolve()
    path = Path(selector).resolve(strict=True)
    if path.parent != root / "provider-authority" or path.suffix != ".protected":
        raise PermissionError("CLI authority capsule outside the intended state root")
    value = _decode(path.read_text(encoding="utf-8"))
    if (value.get("version") != 1 or value.get("backend") != "postgres" or value.get("source_root") != str(root)
            or value.get("owner") != value.get("principal_id") or value.get("owner") != "canvas:" + value.get("principal", "")
            or type(value.get("expires_at")) not in {int, float} or value["expires_at"] < time.time()):
        raise PermissionError("CLI native authority capsule invalid or expired")
    return value
