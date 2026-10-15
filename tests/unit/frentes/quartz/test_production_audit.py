"""Production contract: Flint's admission is audited against the central receipt.

Importing the dispatcher does not change it. The temporary Control Plane does not
close fronts 13 or 16. The installer diagnosis reads the real Next script.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.dispatcher import central_effect_admission
from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceService
from sentra_quality.decision_receipt_audit import AuditRefusal, DecisionReceiptLedger
from sentra_quality.distribution_diagnosis import diagnose_installer, diagnose_tree
from sentra_quality.production_audit import (
    production_contract,
    record_fleet_admission,
    record_runner_final_answer,
)
from sentra_version import PRODUCT_VERSION

ROOT = Path(__file__).resolve().parents[4]
INSTALLER = ROOT / "installer" / "windows" / "install-next.ps1"


def _central(tmp_path):
    state = tmp_path / "control"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    owner = "owner-a"
    durable.create_run(owner, run_id="run-1", workspace="ws-1")
    governance.create_work_item("run-1", owner, objective="admit fleet", work_item_id="wi-1")
    grant = auth.grant(
        owner,
        principal_type="agent",
        principal_id="dot-a",
        capability="vm.import",
        scope_type="work_item",
        scope_id="wi-1",
    )
    reserved = durable.reserve_operation_intent(
        "run-1", owner,
        operation_id="op-import-1",
        idempotency_key="idem-fleet-1",
        intent_sha256="b" * 64,
        resource_key="resource-dot-a",
        operation_context={
            "work_item_id": "wi-1",
            "principal_id": "dot-a",
            "machine_id": "machine-1",
            "capability_id": "vm.import",
        },
    )
    authority = {
        "owner": owner,
        "run_id": "run-1",
        "work_item_id": "wi-1",
        "operation_id": "op-import-1",
        "grant_id": grant["grant_id"],
        "agent_id": "dot-a",
    }
    return auth, durable, governance, reserved, authority


def test_admission_is_fallback_and_runner_answer_uses_the_real_lease(tmp_path):
    auth, durable, governance, reserved, authority = _central(tmp_path)
    before = durable.operation_status("op-import-1", "owner-a")["state"]
    admitted = central_effect_admission(authority, root=tmp_path / "no-clis")
    ledger = DecisionReceiptLedger(tmp_path / "audit")
    fallback = record_fleet_admission(
        ledger, admitted, durable=durable, governance=governance, authorization=auth,
    )
    assert fallback["source"] == "deterministic_fallback"
    assert fallback["counts_as_model_decision"] is False
    assert fallback["sealed"] is False
    assert fallback["central_receipt_reached"] is False
    instruction = "inspect the project tree"
    output = "c" * 64
    sealed = record_runner_final_answer(
        ledger,
        {
            "tool": "sentra-cli",
            "effective_model": "sentra/chatgpt-web/gpt-6",
            "stdout_sha256": output,
            "live_model_verified": True,
            "evidence_source": "native_process",
            "verified": True,
            "execution_uncertain": False,
        },
        instruction=instruction,
        authority=authority,
        durable=durable,
        governance=governance,
        authorization=auth,
    )
    assert sealed["source"] == "model"
    assert sealed["counts_as_model_decision"] is True
    assert sealed["tool"] == "sentra-cli"
    assert sealed["model"] == "sentra/chatgpt-web/gpt-6"
    assert sealed["lease_resource_key"] == "resource-dot-a"
    assert sealed["fencing_token"] == reserved["fencing_token"]
    assert sealed["central_state"] == before == "STARTING"
    assert sealed["authorizes_effect"] is False
    assert sealed["homologated"] is False
    assert sealed["physical_proof"] is False
    view = ledger.read(sealed["chain_id"], owner="owner-a", dot_id="dot-a")
    decision = view["events"][0]
    assert decision["source"] == "model"
    assert decision["model"] == "sentra/chatgpt-web/gpt-6"
    assert decision["prompt_sha256"] != output
    tool = view["events"][1]
    assert tool["tool_name"] == "sentra-cli"
    assert tool["args_sha256"] == decision["prompt_sha256"]
    execution = next(event for event in view["events"] if event["stage"] == "execution")
    assert execution["lease_id"] == "resource-dot-a"
    assert execution["fencing_token"] == reserved["fencing_token"]
    assert not str(execution["lease_id"]).startswith("lease-")
    assert not str(execution["fence_token"]).startswith("fence-")
    assert durable.operation_status("op-import-1", "owner-a")["state"] == "STARTING"
    assert len(auth.list_grants("owner-a")["items"]) == 1
    injected = record_runner_final_answer(
        ledger,
        {"tool": "sentra-cli", "effective_model": "sentra/chatgpt-web/gpt-6",
         "stdout_sha256": output, "live_model_verified": False,
         "evidence_source": "injected_test_runner"},
        instruction=instruction, authority=authority,
        durable=durable, governance=governance, authorization=auth,
    )
    assert injected["counts_as_model_decision"] is False
    assert injected["sealed"] is False
    contract = production_contract()
    assert contract["entry"].endswith("record_runner_final_answer")
    assert contract["homologated"] is False


def test_uncertain_and_unverified_guest_do_not_bind(tmp_path):
    auth, durable, governance, _reserved, authority = _central(tmp_path)
    uncertain = central_effect_admission(
        authority,
        {"lanes": {"sentra-cli": {"delivery_state": "UNCERTAIN", "operation_id": "op-import-1"}}},
        root=tmp_path / "no-clis",
    )
    ledger = DecisionReceiptLedger(tmp_path / "audit")
    with pytest.raises(AuditRefusal, match="UNCERTAIN operation is not resent"):
        record_fleet_admission(
            ledger, uncertain, durable=durable, governance=governance, authorization=auth,
        )
    assert durable.operation_status("op-import-1", "owner-a")["state"] == "STARTING"
    host = central_effect_admission(authority, root=tmp_path / "no-clis")
    forged = dict(host)
    forged["placement"] = {"placement": "guest", "guest_process_verified": False}
    with pytest.raises(AuditRefusal, match="Dot VM registry"):
        record_fleet_admission(
            ledger, forged, durable=durable, governance=governance, authorization=auth,
        )
    verified_only = dict(host)
    verified_only["placement"] = {"placement": "guest", "guest_process_verified": True}
    with pytest.raises(AuditRefusal, match="Dot VM registry"):
        record_fleet_admission(
            ledger, verified_only, durable=durable, governance=governance, authorization=auth,
        )
    forged_pid = dict(host)
    forged_pid["placement"] = {
        "placement": "guest", "guest_process_verified": True,
        "claims_guest_execution": True, "pid": 4242, "evidence_sha256": "a" * 64,
    }
    with pytest.raises(AuditRefusal, match="process id is not a guest execution"):
        record_fleet_admission(
            ledger, forged_pid, durable=durable, governance=governance, authorization=auth,
        )


def test_next_installer_copies_license_docs_and_audit_closure():
    report = diagnose_installer(INSTALLER, product_version=PRODUCT_VERSION)
    assert report["defect"] is None
    assert report["missing"] == []
    assert report["copies_license"] is True
    assert report["copies_comercial"] is True
    assert report["copies_sentra_quality"] is True
    assert report["version_matches"] is True
    assert report["marker_version"] == PRODUCT_VERSION == "1.0.0"
    assert "sentra_quality/decision_receipt_audit.py" not in report["missing"]
    assert report["paywall"] is False
    assert report["local_use_blocked"] is False
    assert report["closes_front_16"] is False
    assert report["physical_proof"] is False
    tree = diagnose_tree(ROOT)
    assert "LICENSE" in tree["present"]
    assert "sentra_quality/decision_receipt_audit.py" in tree["present"]
    assert tree["closes_front_16"] is False


def test_setup_tree_receives_the_license_docs_and_audit_modules(tmp_path):
    from scripts.commander.release_assets import _stage_package_contract
    _stage_package_contract(tmp_path)
    staged = diagnose_tree(tmp_path)
    assert staged["defect"] is None
    assert staged["missing"] == []
    assert staged["paywall"] is False
    assert staged["local_use_blocked"] is False
    assert staged["closes_front_16"] is False
