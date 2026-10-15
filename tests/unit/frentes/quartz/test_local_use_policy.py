"""Front 16: license, user docs, and support. Local use stays open."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.observability import AuditSpanRecorder, MetricsCollector
from sentra_quality.__main__ import main
from sentra_quality.local_use_policy import (
    LOCAL_SURFACES,
    LocalUsePolicy,
    evaluate_access,
    support_bundle,
)

ROOT = Path(__file__).resolve().parents[4]
COMERCIAL = ROOT / "docs" / "frentes-18" / "comercial"


def test_policy_refuses_paywall_charge_and_block():
    policy = LocalUsePolicy()
    body = policy.to_dict()
    assert body["license_spdx"] == "MIT"
    assert body["charge_user"] is False
    assert body["paywall"] is False
    assert body["block_local_use"] is False
    assert body["commercial_homologated"] is False
    assert body["authorizes_effect"] is False
    for flag in ("charge_user", "paywall", "block_local_use"):
        with pytest.raises(ValueError, match="no paywall"):
            LocalUsePolicy(**{flag: True})
    with pytest.raises(ValueError, match="MIT"):
        LocalUsePolicy(license_spdx="BUSL-1.1")


def test_local_surfaces_stay_open_without_account():
    policy = LocalUsePolicy()
    for surface in LOCAL_SURFACES:
        for account in (False, True):
            decision = evaluate_access(policy, surface=surface, authenticated_account=account)
            assert decision["allowed"] is True
            assert decision["charge"] is False
            assert decision["paywall"] is False
            assert decision["account_required"] is False
            assert decision["blocks_local"] is False
            assert decision["authorizes_effect"] is False
    hosted = evaluate_access(policy, surface="hosted_optional")
    assert hosted["allowed"] is False
    assert hosted["blocks_local"] is False
    assert hosted["charge"] is False
    assert hosted["paywall"] is False
    with pytest.raises(ValueError, match="unknown surface"):
        evaluate_access(policy, surface="paid-tier")


def test_support_bundle_and_cli_collect_no_secrets(capsys):
    bundle = support_bundle()
    encoded = json.dumps(bundle)
    assert bundle["charge_user"] is False
    assert bundle["paywall"] is False
    assert bundle["local_use_blocked"] is False
    assert bundle["commercial_homologation"] == "not_homologated"
    assert "auth.json" in bundle["never_collect"]
    assert "tokens" in bundle["never_collect"]
    assert "sk-" not in encoded
    assert main(["local-use"]) == 0
    policy_out = json.loads(capsys.readouterr().out)
    assert policy_out["paywall"] is False
    assert policy_out["block_local_use"] is False
    assert main(["support-bundle"]) == 0
    support_out = json.loads(capsys.readouterr().out)
    assert support_out["local_use_blocked"] is False
    assert "credentials" in support_out["never_collect"]


def test_commercial_docs_keep_local_use_open():
    expected = {
        "README.md": "uso local",
        "LICENCA.md": "Não há paywall.",
        "USUARIO.md": "uso local permanece aberto",
        "SUPORTE.md": "Não envie tokens",
    }
    for name, phrase in expected.items():
        text = (COMERCIAL / name).read_text(encoding="utf-8")
        assert phrase in text
        lowered = text.lower()
        assert "cobrança obrigatória" not in lowered
        assert "assinatura obrigatória" not in lowered
        assert "r$" not in lowered
    user = (COMERCIAL / "USUARIO.md").read_text(encoding="utf-8")
    assert "modelo não concede permissão" in user
    assert "não é reenviada" in user
    assert "homologado comercialmente" in user.lower()
    license_text = (COMERCIAL / "LICENCA.md").read_text(encoding="utf-8")
    assert "MIT" in license_text
    assert "não cobra" in license_text.lower()
    support = (COMERCIAL / "SUPORTE.md").read_text(encoding="utf-8")
    assert "auth.json" in support
    assert "homologado comercialmente" in support.lower()


def test_metrics_collector_keeps_its_fields_and_audit_spans_do_not_grant():
    snapshot = MetricsCollector().to_dict()
    for key in (
        "tasks_total", "tasks_completed", "tasks_failed", "validation_attempts",
        "validation_pass_rate", "tokens_master", "latencies",
    ):
        assert key in snapshot
    recorder = AuditSpanRecorder()
    recorder.record("chains_opened")
    recorder.record("uncertain_held")
    recorder.record("injection_refused")
    body = recorder.to_dict()
    assert body["authorizes_effect"] is False
    assert body["resend_uncertain"] is False
    assert body["injection_refused"] == 1
    with pytest.raises(ValueError, match="unknown audit span"):
        recorder.record("grant")
