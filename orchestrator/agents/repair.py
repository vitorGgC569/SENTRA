from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from ..models import Candidate, Finding, Task, ValidationReport, TokenUsage
from ..providers.base import AgentProvider, AgentRequest
from ..aggregator import Aggregator
from .router import ModelRouter


REPAIR_SYSTEM_PROMPT = """You are the OMA Repair Agent.
Your job is to fix issues, bugs, and requirement gaps identified during validation.

Instructions:
1. Examine the rejected candidate, the reported findings, and any test failures.
2. Produce a targeted repair patch that directly addresses the reported issues.
3. Preserve existing working code and avoid regressions.
4. Output your answer enclosed in BEGIN_RESULT and END_RESULT.

Format:
BEGIN_RESULT
STATUS: COMPLETE
SUMMARY: Detailed explanation of the fixes applied.
PATCH:
```diff
--- a/filepath
+++ b/filepath
@@ ... @@
```
VALIDATION_COMMANDS:
- pytest tests/
END_RESULT
"""


class RepairAgent:
    def __init__(self, router: ModelRouter, agent_id: str = "repair.primary"):
        self.router = router
        self.agent_id = agent_id

    async def repair_candidate(
        self,
        task: Task,
        previous_candidate: Candidate,
        validation_reports: List[ValidationReport],
        test_results: Optional[Dict[str, Any]] = None,
    ) -> Candidate:
        findings_summary = []
        for r in validation_reports:
            for f in r.findings:
                findings_summary.append(
                    f"[{f.severity.value}] [{f.category}] {f.description}"
                    + (f" (Suggested fix: {f.suggested_fix})" if f.suggested_fix else "")
                )

        user_prompt = f"""TASK: {task.objective}
CURRENT REPAIR ROUND: {task.current_repair_round + 1} of {task.max_repair_rounds}

PREVIOUS CANDIDATE (V{previous_candidate.version}) PATCH:
```diff
{previous_candidate.patch}
```

VALIDATION FINDINGS:
{chr(10).join(findings_summary) if findings_summary else "General quality refinement requested."}

AUTOMATED TEST OUTPUT:
{json.dumps(test_results or {}, indent=2)}
"""
        req = AgentRequest(
            system_prompt=REPAIR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            role="repair",
            metadata={"task_id": task.id, "candidate_id": previous_candidate.candidate_id},
        )

        resp = await self.router.execute(req)
        parsed = Aggregator.parse_structured_result(resp.content)

        new_patch = parsed.get("patch") or previous_candidate.patch
        new_summary = parsed.get("summary") or f"Repair V{previous_candidate.version + 1}"
        val_cmds = parsed.get("validation_commands") or previous_candidate.validation_commands

        repaired_candidate = Candidate(
            candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            run_id=task.run_id,
            version=previous_candidate.version + 1,
            summary=new_summary,
            solution=resp.content,
            patch=new_patch,
            files_affected=previous_candidate.files_affected,
            validation_commands=val_cmds,
            created_by=self.agent_id,
            status="CREATED",
            token_usage=resp.token_usage,
        )

        return repaired_candidate
