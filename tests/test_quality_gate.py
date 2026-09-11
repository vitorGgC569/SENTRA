import pytest
from orchestrator.models import (
    Candidate,
    Finding,
    Severity,
    Task,
    ValidationReport,
)
from orchestrator.quality_gate import QualityGate, QuorumPolicy


def test_quality_gate_quorum_failure():
    gate = QualityGate(QuorumPolicy(validators_required=3, minimum_approvals=2))
    task = Task(id="T-1", run_id="r", objective="Test")
    cand = Candidate(candidate_id="C-1", task_id="T-1")

    # Only 2 reports provided when 3 are required
    r1 = ValidationReport(validator_role="v1", status="APPROVED")
    r2 = ValidationReport(validator_role="v2", status="APPROVED")

    passed, reason, package = gate.evaluate(task, cand, [r1, r2])
    assert passed is False
    assert "Quorum not met" in reason


def test_quality_gate_critical_finding_blocks():
    gate = QualityGate(QuorumPolicy(validators_required=3, minimum_approvals=2, critical_rejection_blocks=True))
    task = Task(id="T-1", run_id="r", objective="Test")
    cand = Candidate(candidate_id="C-1", task_id="T-1")

    r1 = ValidationReport(validator_role="v1", status="APPROVED")
    r2 = ValidationReport(validator_role="v2", status="APPROVED")
    # Validator 3 finds a CRITICAL flaw
    r3 = ValidationReport(
        validator_role="v3",
        status="REJECTED",
        findings=[Finding(severity=Severity.CRITICAL, description="Memory leak in loop")],
    )

    passed, reason, package = gate.evaluate(task, cand, [r1, r2, r3])
    assert passed is False
    assert "critical findings" in reason.lower()


def test_quality_gate_objective_tests_required():
    gate = QualityGate(QuorumPolicy(validators_required=2, minimum_approvals=2, objective_test_required=True))
    task = Task(id="T-1", run_id="r", objective="Test")
    cand = Candidate(candidate_id="C-1", task_id="T-1")

    r1 = ValidationReport(validator_role="v1", status="APPROVED")
    r2 = ValidationReport(validator_role="v2", status="APPROVED")

    test_results = {"all_passed": False, "failed_commands": ["pytest failed"]}

    passed, reason, package = gate.evaluate(task, cand, [r1, r2], test_results=test_results)
    assert passed is False
    assert "Objective verification tests failed" in reason


def test_quality_gate_success_and_confidence_calculation():
    gate = QualityGate(QuorumPolicy(validators_required=3, minimum_approvals=2, minimum_confidence_threshold=0.7))
    task = Task(id="T-1", run_id="r", objective="Test")
    cand = Candidate(candidate_id="C-1", task_id="T-1", summary="Implemented math module")

    r1 = ValidationReport(validator_role="validator.logic", status="APPROVED")
    r2 = ValidationReport(validator_role="validator.requirements", status="APPROVED")
    r3 = ValidationReport(validator_role="validator.edge_cases", status="APPROVED")

    test_results = {
        "all_passed": True,
        "results": [{"passed": True}, {"passed": True}],
    }

    passed, reason, package = gate.evaluate(task, cand, [r1, r2, r3], test_results=test_results)
    assert passed is True
    assert package is not None
    assert package.status == "READY_FOR_MASTER"
    assert package.calculated_confidence >= 0.9
