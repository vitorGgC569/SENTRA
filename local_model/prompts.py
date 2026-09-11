from __future__ import annotations

from typing import Any, Dict, List, Optional


class PromptBuilder:
    @staticmethod
    def build_envelope(
        job_id: str,
        round_number: int,
        role: str,
        task_id: str,
        global_objective: str,
        task_description: str,
        relevant_files: List[str],
        current_state_summary: str,
        error_log: Optional[str] = None,
    ) -> str:
        files_str = "\n".join([f"- {f}" for f in relevant_files]) if relevant_files else "- None specified"
        error_block = f"\nOBSERVED ERRORS:\n```\n{error_log}\n```" if error_log else ""

        return f"""RUN_ID: {job_id}
ROUND: {round_number}
SESSION_ROLE: {role.upper()}
TASK_ID: {task_id}

GLOBAL OBJECTIVE:
{global_objective}

THIS SESSION TASK:
{task_description}

RELEVANT FILES:
{files_str}

CURRENT STATE:
{current_state_summary}
{error_block}

RESTRICTIONS:
- Do not alter systems outside task scope.
- Do not remove or disable unit tests.
- Do not swallow errors or suppress exceptions.
- Output MUST strictly follow the required BEGIN_RESULT ... END_RESULT structure.

FORMAT REQUIRED:
BEGIN_RESULT
STATUS: COMPLETE | NEEDS_CONTEXT | FAILED
SUMMARY: Concise explanation of changes.
PATCH:
```diff
--- a/filepath
+++ b/filepath
@@ ... @@
```
VALIDATION_COMMANDS:
- command to test
END_RESULT
"""

    @staticmethod
    def build_continuation_prompt(
        response_id: str,
        last_snippet: str
    ) -> str:
        return f"""The previous response was truncated before completion.

RESPONSE_ID: {response_id}

LAST RECEIVED SNIPPET:
```
{last_snippet[-500:]}
```

INSTRUCTIONS:
1. Continue the response EXACTLY from the point of interruption.
2. Do NOT restart the message or repeat previously delivered code.
3. Maintain the structured format.
4. Conclude with END_RESULT.
"""
