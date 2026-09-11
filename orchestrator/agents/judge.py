from __future__ import annotations

import json
from typing import Any, Dict, List

from ..models import Candidate, Task, ValidationReport
from ..providers.base import AgentProvider, AgentRequest
from .router import ModelRouter


JUDGE_SYSTEM_PROMPT = """You are the OMA Meta-Judge.
Your responsibility is to resolve disputes and contradictions between validators.

Output JSON format:
{
  "verdict": "PROMOTE" | "REQUEST_REPAIR" | "ESCALATE",
  "reasoning": "Clear explanation of the judgment",
  "critical_concerns_validated": ["list of genuine issues"],
  "dismissed_findings": ["list of false positives"]
}
"""


class JudgeAgent:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def arbitrate(
        self,
        task: Task,
        candidate: Candidate,
        validation_reports: List[ValidationReport],
    ) -> Dict[str, Any]:
        reports_summary = []
        for r in validation_reports:
            reports_summary.append({
                "validator": r.validator_role,
                "status": r.status,
                "confidence": r.confidence,
                "findings": [f.to_dict() for f in r.findings],
            })

        user_prompt = f"""TASK OBJECTIVE: {task.objective}

CANDIDATE V{candidate.version} SUMMARY: {candidate.summary}
DIFF:
```diff
{candidate.patch}
```

VALIDATOR REPORTS:
{json.dumps(reports_summary, indent=2)}
"""
        req = AgentRequest(
            system_prompt=JUDGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            role="judge",
        )

        resp = await self.router.execute(req)

        verdict_data = {"verdict": "REQUEST_REPAIR", "reasoning": resp.content}
        if resp.structured_data:
            verdict_data = resp.structured_data
        else:
            try:
                start = resp.content.find("{")
                end = resp.content.rfind("}")
                if start != -1 and end != -1:
                    verdict_data = json.loads(resp.content[start : end + 1])
            except Exception:
                pass

        return verdict_data
