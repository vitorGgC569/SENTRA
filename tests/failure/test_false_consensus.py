"""False-consensus resistance — quorum is not enough without evidence.

Cases: multiple validators APPROVE a defective candidate but deterministic tests
fail -> QualityGate must block. High quorum + critical security finding -> REJECTED.
"""
from orchestrator.models import Candidate, Finding, Severity, Task, ValidationReport
from orchestrator.quality_gate import QualityGate, QuorumPolicy


def _approved(role: str) -> ValidationReport:
    return ValidationReport(validator_role=role, status="APPROVED", confidence=0.95)


def test_deterministic_test_failure_overrides_validator_consensus():
    gate = QualityGate(QuorumPolicy(validators_required=3, minimum_approvals=2,
                                    objective_test_required=True))
    task = Task(id="T-1", run_id="r", objective="implement login")
    cand = Candidate(candidate_id="C-1", task_id="T-1", summary="login done")
    reports = [_approved("validator.logic"), _approved("validator.requirements"),
               _approved("validator.edge_cases")]
    test_results = {"all_passed": False, "failed_commands": ["pytest test_login"],
                    "results": [{"passed": False}]}
    passed, reason, _ = gate.evaluate(task, cand, reports, test_results=test_results)
    assert passed is False
    assert "Objective verification" in reason


def test_critical_security_finding_blocks_despite_high_quorum():
    gate = QualityGate(QuorumPolicy(validators_required=5, minimum_approvals=4,
                                    critical_rejection_blocks=True))
    task = Task(id="T-s", run_id="r", objective="payment handler")
    cand = Candidate(candidate_id="C-s", task_id="T-s")
    reports = [_approved("v1"), _approved("v2"), _approved("v3"), _approved("v4"),
               ValidationReport(validator_role="validator.security", status="REJECTED",
                                findings=[Finding(severity=Severity.CRITICAL,
                                                  category="SECURITY",
                                                  description="command injection via unsanitized input")])]
    passed, reason, _ = gate.evaluate(task, cand, reports, test_results={"all_passed": True})
    assert passed is False
    assert "critical" in reason.lower()
