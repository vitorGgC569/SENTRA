from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..models import CandidatePackage, MasterDecision, TokenUsage
from ..providers.base import AgentProvider, AgentRequest
from .router import ModelRouter


MASTER_SYSTEM_PROMPT = """You are the OMA Master Model.
You are an internal package reviewer, not the user's central AI. Your approval is
advisory and cannot bypass deterministic tests or authorize deployment/promotion.

Your duties:
1. Audit the Candidate Package (solution, tests, validator reports, evidence).
2. Determine if the solution meets the overarching objectives and acceptance criteria.
3. If satisfactory, declare decision APPROVED and synthesize the final authoritative response.
4. If issues remain, declare REJECTED or REPLAN with concrete feedback or new tasks.

Output JSON format:
{
  "decision": "APPROVED" | "REJECTED" | "REPLAN",
  "confidence": 0.0 to 1.0,
  "critical_issues": [],
  "remaining_risks": [],
  "needs_more_work": false,
  "final_response": "Authoritative summary / response to user",
  "reasoning": "Rationale for decision",
  "new_tasks": []
}
"""


class ReviewProtocolError(RuntimeError):
    """No usable review was received. This is NOT evidence against the patch."""


class MasterModelAgent:
    def __init__(self, router: ModelRouter, master_provider_name: str = "master"):
        self.router = router
        self.master_provider_name = master_provider_name

    async def review_candidate_package(
        self,
        global_objective: str,
        package: CandidatePackage,
    ) -> MasterDecision:
        user_prompt = f"""GLOBAL OBJECTIVE:
{global_objective}

CANDIDATE PACKAGE AUDIT:
- Candidate ID: {package.candidate_id}
- Task ID: {package.task_id}
- Task Objective: {package.task_objective}
- Solution Summary: {package.solution_summary}
- Validation: {package.approvals_count} approvals, {package.rejections_count} rejections out of {package.validators_count} validators.
- Objective Tests: {package.tests_passed}/{package.tests_total} passed.
- Calculated Confidence: {package.calculated_confidence:.2f}
- Repair Rounds: {package.repair_rounds}
- Critical Risks: {package.critical_risks}
- Remaining Risks: {package.remaining_risks}

PROPOSED SOLUTION / DIFF:
```diff
{package.patch}
```
"""
        req = AgentRequest(
            system_prompt=MASTER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            role="master",
            metadata={"task_id": package.task_id, "candidate_id": package.candidate_id},
        )

        resp = await self.router.execute(req, preferred_provider=self.master_provider_name)

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

        import math
        if (not resp.success or not isinstance(parsed, dict)
                or parsed.get("decision") not in {"APPROVED", "REJECTED", "REPLAN"}
                or type(parsed.get("confidence")) not in (int, float)
                or not math.isfinite(parsed["confidence"])
                or not 0 <= parsed["confidence"] <= 1
                or type(parsed.get("needs_more_work")) is not bool
                or any(not isinstance(parsed.get(key, []), list)
                       for key in ("critical_issues", "remaining_risks", "new_tasks"))
                or not isinstance(parsed.get("reasoning"), str)
                or not parsed["reasoning"].strip()):
            raise ReviewProtocolError(resp.error or "MASTER_REVIEW_PROTOCOL: expected a typed JSON decision")
        decision_str = str(parsed.get("decision", "REJECTED")).upper()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0
        if (not resp.success or decision_str not in {"APPROVED", "REJECTED", "REPLAN"}
                or not math.isfinite(confidence) or not 0 <= confidence <= 1
                or parsed.get("critical_issues") or parsed.get("needs_more_work", True)):
            decision_str = "REJECTED"

        return MasterDecision(
            decision=decision_str,
            selected_candidate_id=package.candidate_id if decision_str == "APPROVED" else None,
            confidence=confidence if math.isfinite(confidence) else 0.0,
            critical_issues=parsed.get("critical_issues", []),
            remaining_risks=parsed.get("remaining_risks", []),
            needs_more_work=bool(parsed.get("needs_more_work", decision_str != "APPROVED")),
            new_tasks=parsed.get("new_tasks", []),
            final_response=parsed.get("final_response") or resp.content,
            reasoning=parsed.get("reasoning", "Master model package review completed."),
            token_usage=resp.token_usage,
        )

    async def synthesize_final_report(
        self,
        global_objective: str,
        completed_packages: List[CandidatePackage],
    ) -> str:
        packages_summary = []
        for p in completed_packages:
            packages_summary.append(
                f"- Task {p.task_id} ({p.task_objective}): {p.solution_summary} (Confidence: {p.calculated_confidence:.2f})"
            )

        user_prompt = f"""GLOBAL OBJECTIVE:
{global_objective}

COMPLETED MILESTONES:
{chr(10).join(packages_summary)}

Please provide a clear, comprehensive final report summarizing the work accomplished, the verification results, and next operational steps.
"""
        req = AgentRequest(
            system_prompt="You are the OMA Master Model. Provide an executive and technical summary of the completed work.",
            user_prompt=user_prompt,
            role="master",
        )

        resp = await self.router.execute(req, preferred_provider=self.master_provider_name)
        if not resp.success or not resp.content:
            raise RuntimeError(resp.error or "final synthesis returned no content")
        return resp.content
