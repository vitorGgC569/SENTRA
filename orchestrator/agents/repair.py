from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from ..models import Candidate, Finding, Task, ValidationReport, TokenUsage
from ..providers.base import AgentProvider, AgentRequest
from ..aggregator import Aggregator
from ..failure_summary import summarize_test_results
from .router import ModelRouter


REPAIR_SYSTEM_PROMPT = """You are the OMA Repair Agent.
Your job is to fix issues, bugs, and requirement gaps identified during validation.

Instructions:
1. Examine the rejected candidate, the reported findings, and any test failures.
2. Produce a complete replacement candidate patch against the original baseline,
   addressing the reported issues. Each candidate is tested in a fresh snapshot.
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
- [[TEST|all]]
END_RESULT

Unified diff is mechanical: "@@ -start,count +start,count @@" counts MUST match
exactly the hunk lines that follow (' ' context, '-' removed, '+' added).
Count twice. A patch whose counts do not match is rejected without review.
New files use "--- /dev/null" (never "--- a/..."); deleted files use
"+++ /dev/null". No renames (separate delete + create instead) and no empty
targets.
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
        release_bar: float = 9.5,
    ) -> Candidate:
        findings_summary = []
        score_lines = []
        for r in validation_reports:
            score = r.score if r.score is not None else round(max(0.0, min(1.0, r.confidence)) * 10.0, 2)
            score_lines.append(f"- {r.validator_role}: {score:.2f}/10 ({r.status})")
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

CRITIC SCORES (release requires EVERY critic at/above {release_bar:.2f}/10):
{chr(10).join(score_lines) if score_lines else "(no scores recorded)"}

AUTOMATED TEST OUTPUT (failure-focused, bounded):
{json.dumps(
    (test_results or {}).get("failure_summary")
    or summarize_test_results(test_results or {}),
    indent=2,
)}
"""
        parse_error = (test_results or {}).get("parse_error", "")
        if parse_error and not validation_reports:
            # Sintaxe barrada antes dos validadores: diga exatamente o que
            # quebrou, em vez de enterrar no JSON — senão o repair repete o erro.
            user_prompt += (
                "\nSYNTAX REJECTION (no validator ran): your previous patch was "
                f"rejected by the diff parser: {parse_error}\n"
                "Fix ONLY the diff mechanics: valid ---/+++ headers, one @@ header "
                "per hunk with EXACT line counts, no truncation. Keep the intent."
            )
        req = AgentRequest(
            system_prompt=REPAIR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            role="repair",
            metadata={
                "task_id": task.id,
                "idempotency_key": task.idempotency_key,
                "candidate_id": previous_candidate.candidate_id,
                "priority": getattr(task.priority, "value", task.priority),
                "risk": str(task.risk),
            },
        )

        resp = await self.router.execute(req)
        if not resp.success:
            raise RuntimeError(resp.error or "repair provider failed")
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
