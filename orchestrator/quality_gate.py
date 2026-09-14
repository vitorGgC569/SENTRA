from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
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
    # Release bar: MINIMUM critic score (0-10) across ran validators. A critic
    # releases exec only at/above this bar; below it the loop keeps refining.
    min_release_score: float = 9.5
    # Legacy library callers can opt out; operational configuration requires scores.
    require_explicit_scores: bool = False


class QualityGate:
    """
    Deterministic Quality Gate evaluating formal candidate readiness as specified
    in Sections 10, 11, 15, and 16 of OMA.
    'Uma mensagem READY produzida pelo modelo não significa automaticamente que a tarefa está pronta.'
    """

    def __init__(self, policy: Optional[QuorumPolicy] = None):
        self.policy = policy or QuorumPolicy()

    @staticmethod
    def _report_score(report) -> float:
        """Critic score 0-10 with documented fallback (confidence x10) for
        unset legacy scores. Single choke point: gate and package agree."""
        score = getattr(report, "score", None)
        if score is None:
            try:
                conf = float(getattr(report, "confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            return round(max(0.0, min(1.0, conf)) * 10.0, 2)
        try:
            return round(max(0.0, min(10.0, float(score))), 2)
        except (TypeError, ValueError):
            return 0.0

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
            results = [r for r in test_results.get("results", []) if not r.get("refused")]
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
        if any((r.task_id and r.task_id != task.id) or
               (r.candidate_id and r.candidate_id != candidate.candidate_id) for r in reports):
            return False, "Report belongs to a different task/candidate", None
        identities = [r.validator_id or r.validator_role for r in reports]
        if any(not identity for identity in identities) or len(set(identities)) != len(identities):
            return False, "Duplicate or missing validator identity", None
        if len({r.report_id for r in reports}) != len(reports):
            return False, "Duplicate validation report", None
        if any(r.status not in {"APPROVED", "REJECTED", "DISPUTED"}
               or not math.isfinite(r.confidence) or not 0 <= r.confidence <= 1 for r in reports):
            return False, "Invalid validation report status/confidence", None
        # Relatórios com ran=False não são evidência (validador não executou:
        # budget, timeout, transporte). Excluídos do quorum — jamais contam
        # como voto contra o candidato.
        abstained = [r.validator_role for r in reports if not r.ran]
        effective = [r for r in reports if r.ran]
        if self.policy.require_explicit_scores and any(
                type(r.score) not in (int, float) or not math.isfinite(r.score)
                or not 0 <= r.score <= 10 for r in effective):
            return False, "INSUFFICIENT_VALIDATION: missing/invalid explicit quality score", None
        if self.policy.require_explicit_scores and any(r.score < self.policy.min_release_score for r in effective):
            return False, "Below release threshold: explicit score below required bar", None
        if abstained and not effective:
            return (
                False,
                f"INSUFFICIENT_VALIDATION: 0/{len(reports)} validators ran "
                f"(abstained: {sorted(set(abstained))}).",
                None,
            )
        total_validators = len(effective)
        approvals = sum(1 for r in effective if r.status == "APPROVED")
        rejections = total_validators - approvals

        # 1. Quorum check (sobre validações que realmente executaram)
        if total_validators < self.policy.validators_required:
            suffix = (f" Abstained: {sorted(set(abstained))}."
                      if abstained else "")
            if abstained:
                return (
                    False,
                    f"INSUFFICIENT_VALIDATION: {total_validators}/{self.policy.validators_required} "
                    f"ran.{suffix}",
                    None,
                )
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

        # 3. Critical findings check (só de validações que executaram)
        critical_findings = [
            f for r in effective for f in r.findings if f.severity == Severity.CRITICAL
        ]
        if self.policy.critical_rejection_blocks and critical_findings:
            issues = [f.description for f in critical_findings]
            return (
                False,
                f"Blocked by {len(critical_findings)} critical findings: {issues}",
                None,
            )

        # 4. Objective test check. Zero checagens executadas (tudo recusado
        # pela política) NÃO é falha do candidato: é incapacidade de julgar.
        if self.policy.objective_test_required:
            if (test_results and "checks_ran" in test_results
                    and not [r for r in test_results.get("results", []) if not r.get("refused")]):
                refused = test_results.get("refused_commands", [])
                return (
                    False,
                    f"INSUFFICIENT_VALIDATION: no deterministic checks ran (refused: {refused})",
                    None,
                )
            if not test_results or test_results.get("all_passed") is not True:
                failed = (test_results or {}).get("failed_commands", [])
                return (
                    False,
                    f"Objective verification tests failed: {failed}",
                    None,
                )
            results = [r for r in test_results.get("results", []) if not r.get("refused")]
            if not results or any(r.get("passed") is not True for r in results):
                return False, "Objective verification requires nonempty passing evidence", None
        if test_results:
            if test_results.get("candidate_id", candidate.candidate_id) != candidate.candidate_id:
                return False, "Tests belong to a different candidate", None
            expected_patch = hashlib.sha256(candidate.patch.encode("utf-8")).hexdigest()
            if test_results.get("patch_hash", expected_patch) != expected_patch:
                return False, "Tests belong to a different patch version", None
            if test_results.get("source_unchanged") is False:
                return False, "Source changed during verification", None
        critical = str(task.risk).upper() in {"HIGH", "CRITICAL"} or str(
            getattr(task.priority, "value", task.priority)).upper() == "CRITICAL"
        if critical and self.policy.security_validator_required_for_critical:
            approved_roles = {r.validator_role for r in effective if r.status == "APPROVED"}
            if not {"validator.security", "validator.adversarial"} <= approved_roles:
                return False, "Critical work requires approved security and adversarial validators", None
        required = set(task.metadata.get("acceptance_criteria", []))
        checked = {item for r in effective if r.status == "APPROVED" for item in r.requirements_checked}
        coverage = len(required & checked) / len(required) if required else 1.0

        # 5. Calculated confidence check
        confidence = self.calculate_confidence(effective, test_results, requirements_coverage=coverage)
        if confidence < self.policy.minimum_confidence_threshold:
            return (
                False,
                f"Confidence below threshold: {confidence:.2f} < {self.policy.minimum_confidence_threshold:.2f}",
                None,
            )

        # 6. Release bar: the MINIMUM critic score releases exec. One critic
        # below the bar keeps refining — majority approval is not enough.
        scores = [self._report_score(r) for r in effective]
        min_score = min(scores) if scores else 0.0
        if min_score < self.policy.min_release_score:
            return (
                False,
                f"Below release threshold: min critic score {min_score:.2f} < "
                f"{self.policy.min_release_score:.2f}",
                None,
            )

        # Passed all gate criteria! Build CandidatePackage for Master Model (Section 22)
        tests_list = ([r for r in test_results.get("results", []) if not r.get("refused")]
                      if test_results else [])
        passed_tests = sum(1 for t in tests_list if t.get("passed", False))
        failed_tests = len(tests_list) - passed_tests

        remaining_risks = [
            f.description
            for r in effective
            for f in r.findings
            if f.severity in {Severity.MAJOR, Severity.MINOR}
        ]

        mean_score = round(sum(scores) / len(scores), 2) if scores else 0.0
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
            min_validator_score=min_score,
            mean_validator_score=mean_score,
            tests_total=len(tests_list),
            tests_passed=passed_tests,
            tests_failed=failed_tests,
            requirements_coverage=coverage,
            calculated_confidence=confidence,
            execution_iterations=candidate.version,
            repair_rounds=task.current_repair_round,
            critical_risks=[f.description for f in critical_findings],
            remaining_risks=remaining_risks,
            status="READY_FOR_MASTER",
        )

        return True, "Passed Quality Gate! READY_FOR_MASTER.", package
