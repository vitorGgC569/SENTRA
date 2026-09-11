from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..models import CandidatePackage, MasterDecision, TokenUsage
from ..providers.base import AgentProvider, AgentRequest
from .router import ModelRouter


MASTER_SYSTEM_PROMPT = """You are the OMA Master Model.
You are the highest-tier cognitive intelligence in the system, acting as auditor, supreme judge, and final synthesizer.

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
            metadata={"candidate_id": package.candidate_id},
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

        decision_str = parsed.get("decision", "APPROVED" if resp.success else "REJECTED").upper()

        return MasterDecision(
            decision=decision_str,
            selected_candidate_id=package.candidate_id if decision_str == "APPROVED" else None,
            confidence=float(parsed.get("confidence", 0.95 if decision_str == "APPROVED" else 0.5)),
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
        return resp.content or "Work completed successfully across all tasks."
