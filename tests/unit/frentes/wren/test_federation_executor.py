"""Hermetic federation executor. Arithmetic is a result; anything else is not."""
from __future__ import annotations

import hashlib
import json

import pytest

from sentra_federation.errors import FederationDenied
from sentra_federation.executor import (
    assert_unresolved_receipt,
    execute_delegation,
    resolve_hermetic_arithmetic,
    result_document,
    verify_result_receipt,
)
from sentra_mcp.services.control_plane import ControlPlaneService

NUMERIC = "Calcule 17 * 19 e entregue o resultado numerico."
SCOPE = {"kind": "project", "project_id": "project-wren"}


def _delegate(control, artifact_dir, objective, intent_id):
    return execute_delegation(
        control, owner="owner-dot", intent_id=intent_id, objective=objective,
        scope=SCOPE, grant_id="grant-dot", peer="peer-1", artifact_dir=artifact_dir,
    )


def test_delimited_arithmetic_is_the_deliverable_and_an_echo_is_not(tmp_path):
    assert resolve_hermetic_arithmetic(NUMERIC) == "323"
    assert resolve_hermetic_arithmetic("17 * 19") == "323"
    assert resolve_hermetic_arithmetic("8 / 2") == "4"
    assert resolve_hermetic_arithmetic("(20 + 3) * 4 - 10") == "82"
    for refused in (
        "Write the project brief",
        "record only",
        "Calcule 17 * 19 e tambem 2 + 2",
        "section 17 * 19",
        "17,000 * 2",
        "8 / 3",
        "1 / 0",
        "2 ** 80",
        "__import__('os').system('echo hi')",
        "os.system('calc')",
        NUMERIC + "\nimport socket",
    ):
        assert resolve_hermetic_arithmetic(refused) is None

    control = ControlPlaneService.from_store(tmp_path / "control")
    try:
        ready = _delegate(control, tmp_path / "artifacts", NUMERIC, "intent-" + "ab" * 16)
        assert ready["result_ready"] is True and ready["passed"] is True
        assert ready["executed"] is False and ready["automatic_resend"] is False
        parsed = json.loads(ready["result_document"])
        assert parsed["result"]["deliverable"] == "323"
        assert parsed["result"]["deliverable"] != parsed["task"]
        assert verify_result_receipt(ready, objective=NUMERIC, scope=SCOPE) == ready["artifact_sha256"]
        item = control.work_item_info(ready["work_item_id"], "owner-dot")
        assert item["state"] == "IN_REVIEW"
        assert item["execution_state"]["quality_gate"]["passed"] is True
        again = _delegate(control, tmp_path / "artifacts", NUMERIC, ready["intent_id"])
        assert again["artifact_sha256"] == ready["artifact_sha256"]
        assert list((tmp_path / "artifacts").glob("*.json")) == [tmp_path / "artifacts" / f"{ready['intent_id']}.json"]
        assert control.durable.list_operations(ready["run_id"], "owner-dot")["page"]["total"] == 1

        echoed = json.loads(ready["result_document"])
        echoed["result"]["deliverable"] = echoed["task"]
        echoed_document = json.dumps(echoed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        forged = dict(ready, result_document=echoed_document)
        forged["artifact_sha256"] = hashlib.sha256(echoed_document.encode("utf-8")).hexdigest()
        with pytest.raises(FederationDenied, match="echoes the task"):
            verify_result_receipt(forged, objective=NUMERIC, scope=SCOPE)
        with pytest.raises(FederationDenied):
            result_document(
                project_id="project-wren", task=NUMERIC,
                work_item_id=ready["work_item_id"], deliverable=NUMERIC,
            )
    finally:
        control.durable.close()


def test_assert_unresolved_receipt_rejects_a_forged_delivery(tmp_path):
    control = ControlPlaneService.from_store(tmp_path / "control")
    try:
        unresolved = _delegate(
            control, tmp_path / "artifacts", "Write the project brief", "intent-" + "aa" * 16,
        )
        assert assert_unresolved_receipt(unresolved, objective="Write the project brief") is unresolved
        forged = dict(unresolved)
        forged["result_ready"] = True
        forged["passed"] = True
        forged["work_item_state"] = "IN_REVIEW"
        forged["result_document"] = json.dumps({"result": {"deliverable": "323"}}, sort_keys=True)
        with pytest.raises(FederationDenied, match="claimed a delivery"):
            assert_unresolved_receipt(forged, objective="Write the project brief")
        with pytest.raises(FederationDenied, match="echoed a deliverable"):
            bad = dict(unresolved, result_document="{}", artifact_id="artifact-x", artifact_sha256="0" * 64)
            assert_unresolved_receipt(bad, objective="Write the project brief")
    finally:
        control.durable.close()


def test_other_objectives_fail_the_gate_and_uncertain_work_is_not_repeated(tmp_path):
    control = ControlPlaneService.from_store(tmp_path / "control")
    try:
        unresolved = _delegate(control, tmp_path / "artifacts", "Write the project brief", "intent-" + "cd" * 16)
        assert unresolved["result_ready"] is False
        assert unresolved["passed"] is False
        assert unresolved["executed"] is False
        assert unresolved["automatic_resend"] is False
        assert unresolved["work_item_state"] == "REPAIRING"
        assert "result_document" not in unresolved
        assert not (tmp_path / "artifacts" / f"{unresolved['intent_id']}.json").exists()
        item = control.work_item_info(unresolved["work_item_id"], "owner-dot")
        assert item["state"] == "REPAIRING"
        assert item["execution_state"]["quality_gate"]["passed"] is False
        with pytest.raises(FederationDenied, match="not ready"):
            verify_result_receipt(unresolved, objective="Write the project brief", scope=SCOPE)
        repeated = _delegate(control, tmp_path / "artifacts", "Write the project brief", unresolved["intent_id"])
        assert repeated == unresolved
        assert control.durable.list_operations(unresolved["run_id"], "owner-dot")["page"]["total"] == 1
        assert control.work_item_info(unresolved["work_item_id"], "owner-dot")["state"] == "REPAIRING"

        unsafe = _delegate(control, tmp_path / "artifacts", "2 ** 80", "intent-" + "ef" * 16)
        assert unsafe["passed"] is False and unsafe["result_ready"] is False
        division = _delegate(control, tmp_path / "artifacts", "1 / 0", "intent-" + "11" * 16)
        assert division["passed"] is False and division.get("result_document") is None

        owner = "owner-dot"
        intent_id = "intent-" + "22" * 16
        run = control.durable.create_run(
            owner, workspace="project-wren",
            idempotency_key="federation:owner-dot:project-wren",
            required_capabilities=["federation.delegate"],
        )
        operation = control.durable.create_operation(
            run["run_id"], owner, kind="federation.delegate",
            idempotency_key=intent_id, initial_state="QUEUED",
        )
        operation = control.durable.update_operation(operation["operation_id"], owner, state="STARTING")
        control.durable.update_operation(operation["operation_id"], owner, state="UNCERTAIN")
        with pytest.raises(FederationDenied, match="not restarted"):
            _delegate(control, tmp_path / "artifacts", NUMERIC, intent_id)
        assert control.durable.operation_status(operation["operation_id"], owner)["state"] == "UNCERTAIN"
        assert list(control.list_work_items(owner, run_id=run["run_id"])["items"])  # prior items only
        created = control.list_work_items(owner, run_id=run["run_id"])["items"]
        assert all(item["external_key"] != intent_id for item in created)
    finally:
        control.durable.close()
