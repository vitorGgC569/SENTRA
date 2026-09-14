from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from ..models import Candidate, Task, TokenUsage
from ..providers.base import AgentProvider, AgentRequest
from ..aggregator import Aggregator
from .router import ModelRouter


EXECUTOR_SYSTEM_PROMPT = """You are the OMA Specialized Code & Solution Executor.
Your job is to implement complete, working solutions for the assigned task.

Instructions:
1. Provide a concise summary of the implementation.
2. Deliver code changes as unified diff patches (--- a/file +++ b/file).
   Hunk headers "@@ -start,count +start,count @@" MUST match exactly the hunk
   lines that follow (' ' context, '-' removed, '+' added). Count twice:
   malformed counts are rejected without review.
   New files use "--- /dev/null" (never "--- a/..."); deleted files use
   "+++ /dev/null". A new-file patch starting with "--- a/" is rejected.
   No renames (separate delete + create instead) and no empty targets.
3. Specify compact validation directives: [[TEST|all]], [[LINT]], [[BUILD]].
   The local runtime alone chooses executable arguments. Shell text is rejected.
4. Enclose your output between BEGIN_RESULT and END_RESULT markers.

Format:
BEGIN_RESULT
STATUS: COMPLETE
SUMMARY: Detailed summary of implementation
PATCH:
```diff
--- a/filepath
+++ b/filepath
@@ -0,0 +1,10 @@
+...
```
VALIDATION_COMMANDS:
- [[TEST|all]]
END_RESULT
"""


class ExecutorAgent:
    def __init__(self, router: ModelRouter, agent_id: str = "executor.primary"):
        self.router = router
        self.agent_id = agent_id

    async def execute_task(
        self,
        task: Task,
        context_summary: str = "",
        target_files_content: Optional[Dict[str, str]] = None,
    ) -> Candidate:
        files_str = ""
        if target_files_content:
            parts = []
            for path, content in target_files_content.items():
                parts.append(f"FILE: {path}\n```\n{content}\n```")
            files_str = "\n\n".join(parts)

        user_prompt = f"""TASK ID: {task.id}
OBJECTIVE: {task.objective}
DESCRIPTION: {task.description}
TARGET FILES: {task.target_files}

CONTEXT / PREVIOUS FINDINGS:
{context_summary}

RELEVANT FILE CONTENTS:
{files_str}
"""
        req = AgentRequest(
            system_prompt=EXECUTOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            role="executor",
            metadata={"task_id": task.id},
        )

        resp = await self.router.execute(req)
        if not resp.success:
            raise RuntimeError(resp.error or "executor provider failed")

        # Parse structured output using Aggregator
        parsed = Aggregator.parse_structured_result(resp.content)

        # Fallback if no explicit patch was found
        patch = parsed.get("patch", "")
        summary = parsed.get("summary") or resp.content[:200]
        val_cmds = parsed.get("validation_commands", [])

        candidate = Candidate(
            candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            run_id=task.run_id,
            version=1,
            summary=summary,
            solution=resp.content,
            patch=patch,
            files_affected=task.target_files,
            validation_commands=val_cmds,
            created_by=self.agent_id,
            status="CREATED",
            token_usage=resp.token_usage,
        )

        return candidate
