"""Front 5 and 7 check against a temporary Canvas. No physical deletion.

Writes nothing under the repository .sentra or .oma directories. Does not
start VirtualBox, restart the relay, or remove a Dot, VM, VDI or conversation.
"""
from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _release(control, owner, run_ids, agent_ids):
    for agent_id in agent_ids:
        for grant in control.authorization.list_grants(
                owner, principal_type="agent", principal_id=agent_id)["items"]:
            if not control.authorization.info(grant["grant_id"], owner)["revoked"]:
                control.authorization_revoke(grant["grant_id"], owner)
    for run_id in set(run_ids):
        offset = 0
        while True:
            page = control.list_work_items(owner, run_id=run_id, limit=1000, offset=offset)
            for item in page["items"]:
                if item.get("assignee_agent_id") in agent_ids and not item.get("terminal"):
                    control.transition_work_item(item["work_item_id"], owner, "CANCELLED")
            offset = page["page"]["next_offset"]
            if offset is None:
                break


def run(root: Path) -> dict:
    from sentra_canvas.service import Canvas
    from sentra_canvas.shell_dot_lifecycle import DOT_LIFECYCLE_ACTIONS
    from sentra_canvas.shell_dot_retirement import DotRetirement
    from sentra_runtime.uncertain_recovery import UncertainRecovery

    project_dir = root / "project"
    project_dir.mkdir()
    app = Canvas(project_dir, principal="pylon-e2e", state_dir=root / "state" / "canvas")
    app.model_catalog = lambda: {"models": ["sentra/test-one"]}
    try:
        project = app.create_workspace("PylonE2E")["id"]
        runtime = app._runtime()
        opened = runtime.run(project)
        if opened["state"] != "RUNNING":
            runtime.durable.transition_run(opened["run_id"], runtime.owner, "RUNNING")
        home = app.shell_bridge({"action": "home", "project_id": project})["value"]
        space_id = home["space"]["space_id"]
        owner = runtime.owner
        control = app._shell_service()

        def bridge(action, **fields):
            payload = {"action": action, "project_id": project, "space_id": space_id,
                "request_key": "e2e-" + uuid.uuid4().hex}
            payload.update(fields)
            result = app.shell_bridge(payload)
            if result.get("ok") is False:
                raise RuntimeError(result)
            return result["value"]

        root_dot = bridge("dot_create", name="PylonE2ERoot", role="specialist", model="sentra/test-one")
        child = bridge("dot_create", name="PylonE2EChild", role="specialist", model="sentra/test-one",
            canvas_root_dot_id=root_dot["dot_id"])
        retirement = DotRetirement(app, control, owner)
        agents = {root_dot["agent_id"], child["agent_id"]}
        priors = {agent_id: control.durable.agent_info(agent_id, owner)["desired_state"] for agent_id in agents}
        paused = bridge("dot_pause_family", dot_id=root_dot["dot_id"], confirm_name=root_dot["name"],
            request_key="e2e-pause-family")
        resumed = bridge("dot_resume_family", dot_id=root_dot["dot_id"], confirm_name=root_dot["name"],
            request_key="e2e-resume-family")
        _release(control, owner, {root_dot["run_id"], child["run_id"]}, agents)
        ready = bridge("dot_remove_preflight", dot_id=root_dot["dot_id"])
        if not ready["archive_ready"]:
            raise RuntimeError({"archive_blockers": ready["archive_blockers"]})
        archived = bridge("dot_archive_local", dot_id=root_dot["dot_id"], confirm_name=root_dot["name"],
            snapshot=ready["snapshot"], request_key="e2e-archive-family")
        flags = retirement.archived(project, space_id)
        restored = bridge("dot_restore_local", dot_id=root_dot["dot_id"], request_key="e2e-restore-family")
        blocked = bridge("dot_delete_request", dot_id=root_dot["dot_id"], confirm_name=root_dot["name"],
            confirm_phrase="EXCLUIR DOT", request_key="e2e-delete-request")
        operation_id = "e2e-uncertain-" + uuid.uuid4().hex
        created = control.durable.create_operation(root_dot["run_id"], owner, kind="pylon.e2e",
            operation_id=operation_id, idempotency_key=operation_id, cleanup_policy="manual",
            initial_state="RUNNING")
        control.durable.update_operation(created["operation_id"], owner, state="UNCERTAIN")
        before = control.durable.operation_status(operation_id, owner)
        plan = UncertainRecovery("canvas_closed").reconcile_durable(
            control, owner, root_dot["run_id"],
            work_items=({"id": "e2e-review", "state": "IN_REVIEW"},),
        )
        after = control.durable.operation_status(operation_id, owner)
        dots = bridge("dot_list")["items"]
        dot_ids = {item["dot_id"] for item in dots}
        ok = (
            paused["status"] == "paused"
            and resumed["status"] == "resumed"
            and archived["status"] == "archived_local"
            and archived["dot_deleted"] is False
            and flags.get(root_dot["dot_id"]) is True
            and flags.get(child["dot_id"]) is True
            and restored["status"] == "restored_local"
            and blocked["physical_effect_performed"] is False
            and blocked["dot_deleted"] is False
            and child["dot_id"] in blocked["would_orphan_if_root_removed_alone"]
            and after["state"] == "UNCERTAIN"
            and after["updated_at"] == before["updated_at"]
            and plan["effects_executed"] == 0
            and paused["effects_executed"] == 0
            and blocked["effects_executed"] == 0
            and str(paused.get("receipt_id") or "").startswith("dot-family-")
            and plan["may_resend"] is False
            and plan["promoted_work_items"] == 0
            and {root_dot["dot_id"], child["dot_id"]} <= dot_ids
            and all(control.durable.agent_info(agent_id, owner)["desired_state"] == priors[agent_id]
                for agent_id in agents)
        )
        return {
            "ok": ok,
            "pause_receipt": paused["receipt_id"],
            "resume_receipt": resumed["receipt_id"],
            "archive_receipt": archived["receipt_id"],
            "restore_receipt": restored["receipt_id"],
            "deletion_receipt": blocked["receipt_id"],
            "deletion_status": blocked["status"],
            "recovery_incident": plan["incident"],
            "recovery_digest": plan["digest"],
            "recovery_effects_executed": plan["effects_executed"],
            "uncertain_operation_state": after["state"],
            "family_dot_ids": archived["family_dot_ids"],
            "shell_pause_wired": "dot_pause_family" in DOT_LIFECYCLE_ACTIONS
                and paused.get("status") == "paused"
                and str(paused.get("receipt_id") or "").startswith("dot-family-"),
            "physical_deletion_executed": False,
            "vm_or_vdi_touched": False,
            "conversation_deleted": False,
        }
    finally:
        try:
            app._runtime().durable.close()
        except Exception:
            pass
        app.shutdown()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pylon-frentes-", ignore_cleanup_errors=True) as temporary:
        try:
            report = run(Path(temporary))
        except Exception as exc:
            report = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:500],
                "physical_deletion_executed": False, "vm_or_vdi_touched": False}
    json.dump(report, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
