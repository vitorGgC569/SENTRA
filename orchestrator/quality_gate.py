from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Candidate,
    CandidatePackage,
    Severity,
    Task,
    ValidationReport,
)


@dataclass
class QuorumPolicy:
    validators_required: int = 3
    minimum_approvals: int = 2
    critical_rejection_blocks: bool = True
    objective_test_required: bool = True
    minimum_confidence_threshold: float = 0.75
    security_validator_required_for_critical: bool = True


class QualityGate:
    """
    Deterministic Quality Gate evaluating formal candidate readiness as specified
    in Sections 10, 11, 15, and 16 of OMA.
    'Uma mensagem READY produzida pelo modelo não significa automaticamente que a tarefa está pronta.'
    """

    def __init__(self, policy: Optional[QuorumPolicy] = None):
        self.policy = policy or QuorumPolicy()

    def calculate_confidence(
        self,
        reports: List[ValidationReport],
        test_results: Optional[Dict[str, Any]],
        requirements_coverage: float = 1.0,
        historical_reliability: float = 1.0,
    ) -> float:
        """
        Calculates confidence score as specified in Section 16:
        FinalConfidence = ValidatorAgreement * TestPassRate * RequirementsCoverage * EvidenceQuality * HistoricalReliability
        """
        if not reports:
            return 0.0

        approvals = sum(1 for r in reports if r.status == "APPROVED")
        validator_agreement = approvals / len(reports)

        test_pass_rate = 1.0
        if test_results:
            results = test_results.get("results", [])
            if results:
                passed = sum(1 for r in results if r.get("passed", False))
                test_pass_rate = passed / len(results)
            elif not test_results.get("all_passed", True):
                test_pass_rate = 0.0

        # Evidence quality: penalized if critical or major findings exist
        total_findings = sum(len(r.findings) for r in reports)
        critical_count = sum(
            1 for r in reports for f in r.findings if f.severity == Severity.CRITICAL
        )
        major_count = sum(
            1 for r in reports for f in r.findings if f.severity == Severity.MAJOR
        )

        if critical_count > 0:
            evidence_quality = 0.2
        elif major_count > 0:
            evidence_quality = max(0.5, 1.0 - (major_count * 0.15))
        else:
            evidence_quality = 1.0

        final_conf = (
            validator_agreement
            * test_pass_rate
            * requirements_coverage
            * evidence_quality
            * historical_reliability
        )

        return round(max(0.0, min(1.0, final_conf)), 4)

    def evaluate(
        self,
        task: Task,
        candidate: Candidate,
        reports: List[ValidationReport],
        test_results: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[CandidatePackage]]:
        """
        Evaluates whether candidate passes the Quality Gate to reach READY_FOR_MASTER.
        Returns: (passed: bool, reason: str, package: Optional[CandidatePackage])
        """
        total_validators = len(reports)
        approvals = sum(1 for r in reports if r.status == "APPROVED")
        rejections = total_validators - approvals

        # 1. Quorum check
        if total_validators < self.policy.validators_required:
            return (
                False,
                f"Quorum not met: received {total_validators}/{self.policy.validators_required} reports.",
                None,
            )

        # 2. Minimum approvals
        if approvals < self.policy.minimum_approvals:
            return (
                False,
                f"Insufficient approvals: {approvals}/{self.policy.minimum_approvals} approvals.",
                None,
            )

        # 3. Critical findings check
        critical_findings = [
            f for r in reports for f in r.findings if f.severity == Severity.CRITICAL
        ]
        if self.policy.critical_rejection_blocks and critical_findings:
            issues = [f.description for f in critical_findings]
            return (
                False,
                f"Blocked by {len(critical_findings)} critical findings: {issues}",
                None,
            )

        # 4. Objective test check
        if self.policy.objective_test_required and test_results:
            if not test_results.get("all_passed", True):
                failed = test_results.get("failed_commands", [])
                return (
                    False,
                    f"Objective verification tests failed: {failed}",
                    None,
                )

        # 5. Calculated confidence check
        confidence = self.calculate_confidence(reports, test_results)
        if confidence < self.policy.minimum_confidence_threshold:
            return (
                False,
                f"Confidence below threshold: {confidence:.2f} < {self.policy.minimum_confidence_threshold:.2f}",
                None,
            )

        # Passed all gate criteria! Build CandidatePackage for Master Model (Section 22)
        tests_list = test_results.get("results", []) if test_results else []
        passed_tests = sum(1 for t in tests_list if t.get("passed", False))
        failed_tests = len(tests_list) - passed_tests

        remaining_risks = [
            f.description
            for r in reports
            for f in r.findings
            if f.severity in {Severity.MAJOR, Severity.MINOR}
        ]

        package = CandidatePackage(
            candidate_id=candidate.candidate_id,
            task_id=task.id,
            task_objective=task.objective,
            solution_summary=candidate.summary,
            solution=candidate.solution,
            patch=candidate.patch,
            validators_count=total_validators,
            approvals_count=approvals,
            rejections_count=rejections,
            tests_total=len(tests_list),
            tests_passed=passed_tests,
            tests_failed=failed_tests,
            requirements_coverage=1.0,
            calculated_confidence=confidence,
            execution_iterations=candidate.version,
            repair_rounds=task.current_repair_round,
            critical_risks=[],
            remaining_risks=remaining_risks,
            status="READY_FOR_MASTER",
        )

        return True, "Passed Quality Gate! READY_FOR_MASTER.", package
