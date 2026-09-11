from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from ..models import (
    Candidate,
    Evidence,
    Finding,
    Severity,
    Task,
    ValidationReport,
    ValidatorRole,
    TokenUsage,
)
from ..providers.base import AgentRequest
from .router import ModelRouter


VALIDATOR_PROMPTS = {
    ValidatorRole.LOGIC: """You are the OMA Logic Validator.
Your job is to scrutinize the candidate solution for:
- Logical inconsistencies, contradictions, and algorithmic bugs.
- Flawed reasoning, off-by-one errors, or incorrect assumptions.
- State corruption or circular dependencies.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "LOGIC",
      "description": "Specific issue",
      "suggested_fix": "Fix recommendation"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.REQUIREMENTS: """You are the OMA Requirements Validator.
Your job is to verify that the proposed solution faithfully and completely satisfies the assigned objective and acceptance criteria.
Check for:
- Missing requirements or partial implementations.
- Divergence from the requested specification.
- Unwanted modifications outside the task scope.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "REQUIREMENTS",
      "description": "Requirement not satisfied",
      "suggested_fix": "How to satisfy it"
    }
  ],
  "requirements_checked": ["list of criteria satisfied"]
}
""",
    ValidatorRole.ADVERSARIAL: """You are the OMA Adversarial Validator.
Your goal is to actively try to BREAK the candidate solution.
Look for:
- Fragile logic, unhandled unexpected inputs, and easy bypasses.
- Silent error suppression or swallowing of exceptions.
- Malformed inputs that cause crashes or data corruption.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "ADVERSARIAL",
      "description": "Vulnerability or breakage found",
      "suggested_fix": "Hardening guidance"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.EDGE_CASES: """You are the OMA Edge Cases Validator.
Examine the solution for boundary conditions:
- Empty lists, null / None values, zero / negative numbers.
- Extremely large inputs, unicode / special characters.
- Concurrent access or race conditions.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "EDGE_CASE",
      "description": "Unhandled edge condition",
      "suggested_fix": "Defensive handling"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.SECURITY: """You are the OMA Security Validator.
Audit the solution for security risks:
- Command injection, SQL injection, path traversal, untrusted input execution.
- Credential leaks in logs or code.
- Principle of least privilege violations.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "SECURITY",
      "description": "Security risk identified",
      "suggested_fix": "Sanitization or security measure"
    }
  ],
  "requirements_checked": []
}
""",
    ValidatorRole.PERFORMANCE: """You are the OMA Performance Validator.
Analyze the solution for:
- Algorithmic complexity (e.g. O(N^2) loops where O(N) is feasible).
- Unbounded memory consumption or leaks.
- Excessive I/O, redundant network calls, or blocking operations.

Output JSON:
{
  "status": "APPROVED" | "REJECTED",
  "confidence": 0.0 to 1.0,
  "summary": "Concise summary",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "PERFORMANCE",
      "description": "Performance concern",
      "suggested_fix": "Optimization approach"
    }
  ],
  "requirements_checked": []
}
""",
}


class SpecializedValidator:
    def __init__(self, role: ValidatorRole, router: ModelRouter):
        self.role = role
        self.router = router

    async def validate(
        self,
        task: Task,
        candidate: Candidate,
        test_results: Optional[Dict[str, Any]] = None,
    ) -> ValidationReport:
        system_prompt = VALIDATOR_PROMPTS.get(
            self.role, VALIDATOR_PROMPTS[ValidatorRole.LOGIC]
        )
        user_prompt = f"""TASK OBJECTIVE: {task.objective}
TASK DESCRIPTION: {task.description}

CANDIDATE SUMMARY: {candidate.summary}
PROPOSED PATCH:
```diff
{candidate.patch}
```

DETERMINISTIC TEST RESULTS:
{json.dumps(test_results or {}, indent=2)}
"""
        req = AgentRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role=self.role.value,
            metadata={"task_id": task.id, "candidate_id": candidate.candidate_id},
        )

        resp = await self.router.execute(req)

        # Parse JSON output
        parsed: Dict[str, Any] = {}
        if resp.structured_data:
            parsed = resp.structured_data
        else:
            try:
                start = resp.content.find("{")
                end = resp.content.rfind("}")
                if start != -1 and end != -1:
                    parsed = json.loads(resp.content[start : end + 1])
            except Exception:
                pass

        status = parsed.get("status", "APPROVED" if resp.success else "REJECTED").upper()
        confidence = float(parsed.get("confidence", 0.9 if status == "APPROVED" else 0.5))
        summary = parsed.get("summary", resp.content[:150])

        findings = []
        for f_data in parsed.get("findings", []):
            sev_str = f_data.get("severity", "MINOR").upper()
            sev = Severity[sev_str] if sev_str in Severity.__members__ else Severity.MINOR
            findings.append(
                Finding(
                    finding_id=f"fnd_{uuid.uuid4().hex[:8]}",
                    severity=sev,
                    category=f_data.get("category", self.role.name),
                    description=f_data.get("description", ""),
                    suggested_fix=f_data.get("suggested_fix"),
                )
            )

        # If tests failed deterministically, always add a CRITICAL finding
        if test_results and not test_results.get("all_passed", True):
            status = "REJECTED"
            confidence = min(confidence, 0.4)
            findings.append(
                Finding(
                    finding_id=f"fnd_test_{uuid.uuid4().hex[:6]}",
                    severity=Severity.CRITICAL,
                    category="TEST_FAILURE",
                    description=f"Objective tests failed: {test_results.get('failed_commands', [])}",
                    suggested_fix="Fix code to satisfy automated tests.",
                )
            )

        # Create report
        report = ValidationReport(
            report_id=f"val_{uuid.uuid4().hex[:8]}",
            candidate_id=candidate.candidate_id,
            task_id=task.id,
            validator_id=self.role.value,
            validator_role=self.role.value,
            status=status,
            confidence=confidence,
            summary=summary,
            findings=findings,
            requirements_checked=parsed.get("requirements_checked", []),
            tests=test_results.get("results", []) if test_results else [],
            token_usage=resp.token_usage,
        )

        return report


class ValidatorPool:
    """
    Manages a pool of specialized cognitive diversity validators.
    """

    def __init__(self, router: ModelRouter):
        self.router = router
        self.validators = {
            role: SpecializedValidator(role, router)
            for role in ValidatorRole
            if role != ValidatorRole.GENERAL
        }

    async def validate_candidate(
        self,
        task: Task,
        candidate: Candidate,
        roles: Optional[List[ValidatorRole]] = None,
        test_results: Optional[Dict[str, Any]] = None,
    ) -> List[ValidationReport]:
        selected_roles = roles or [
            ValidatorRole.LOGIC,
            ValidatorRole.REQUIREMENTS,
            ValidatorRole.EDGE_CASES,
        ]

        tasks = [
            self.validators[role].validate(task, candidate, test_results)
            for role in selected_roles
            if role in self.validators
        ]

        reports = await asyncio.gather(*tasks)
        return list(reports)
