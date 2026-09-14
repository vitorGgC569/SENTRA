"""Version-regression: downgrade sem justificativa bloqueia; upgrade só informa."""
import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.agents.validators import SpecializedValidator
from orchestrator.models import Candidate, Severity, Task, ValidatorRole
from orchestrator.providers.mock_provider import MockProvider
from orchestrator.quality_gate import QualityGate, QuorumPolicy


def _router():
    mock = MockProvider(model_name="m")
    return ModelRouter(providers={"primary": mock}, primary_provider_name="primary",
                       fallback_provider_name=None)


def _evidence(downgrades=(), upgrades=()):
    return {"all_passed": True, "failed_commands": [], "results": [{"passed": True}],
            "checks_ran": 1,
            "version_check": {"downgrades": list(downgrades), "upgrades": list(upgrades)}}


@pytest.mark.asyncio
async def test_downgrade_forces_rejected_with_critical_finding():
    v = SpecializedValidator(ValidatorRole.LOGIC, _router())
    task = Task(id="T-1", run_id="r", objective="fix integrity")
    cand = Candidate(candidate_id="C-1", task_id="T-1", patch="diff")
    rep = await v.validate(task, cand, test_results=_evidence(
        downgrades=[{"path": "edge_extension/content-script.js",
                     "old": "1.3.17", "new": "1.3.9"}]))
    assert rep.status == "REJECTED"
    assert rep.ran is True
    crits = [f for f in rep.findings if f.severity == Severity.CRITICAL]
    assert any(f.category == "VERSION_REGRESSION" and "1.3.17" in f.description
               and "1.3.9" in f.description for f in crits)


@pytest.mark.asyncio
async def test_upgrade_is_info_only_no_force_reject():
    v = SpecializedValidator(ValidatorRole.LOGIC, _router())
    task = Task(id="T-1", run_id="r", objective="release 1.4")
    cand = Candidate(candidate_id="C-1", task_id="T-1", patch="diff")
    rep = await v.validate(task, cand, test_results=_evidence(
        upgrades=[{"path": "edge_extension/manifest.json",
                   "old": "1.3.17", "new": "1.4.0"}]))
    assert rep.status == "APPROVED"  # mock aprova; upgrade não força reject
    assert any(f.category == "VERSION_CHANGE" and f.severity == Severity.INFO
               for f in rep.findings)


def test_gate_blocks_downgrade_candidate_on_merits():
    gate = QualityGate(QuorumPolicy(validators_required=2, minimum_approvals=1,
                                    objective_test_required=False,
                                    minimum_confidence_threshold=0.0))
    from orchestrator.models import ValidationReport, Finding
    task = Task(id="T-1", run_id="r", objective="x")
    cand = Candidate(candidate_id="C-1", task_id="T-1")
    ok = ValidationReport(validator_role="validator.requirements", status="APPROVED",
                          confidence=0.98)
    rep = ValidationReport(validator_role="validator.logic", status="REJECTED",
                           confidence=0.9,
                           findings=[Finding(severity=Severity.CRITICAL,
                                             category="VERSION_REGRESSION",
                                             description="downgrade 1.3.17 -> 1.3.9")])
    passed, reason, _ = gate.evaluate(
        task, cand, [ok, rep], test_results={"all_passed": True, "results": [{"passed": True}]})
    assert passed is False
    assert "critical" in reason.lower()
