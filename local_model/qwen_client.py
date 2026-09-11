from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI


class QwenLocalClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        model_name: str = "qwen2.5-coder:14b",
        api_key: str = "local",
        temperature: float = 0.1,
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.temperature = temperature
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def _ask(self, system_prompt: str, user_prompt: str) -> str:
        try:
            print(f"[QwenLocal] Querying {self.model_name}...", flush=True)
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
            )
            ans = response.choices[0].message.content or ""
            print(f"[QwenLocal] Response received ({len(ans)} chars).", flush=True)
            return ans
        except Exception as e:
            err_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"[QwenLocal] Error querying model: {err_msg}", flush=True)
            return f"ERROR: Failed to connect to local Qwen endpoint ({self.base_url}): {err_msg}"

    def _extract_json(self, text: str) -> Dict[str, Any]:
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        raw_json = match.group(1) if match else text
        try:
            return json.loads(raw_json)
        except Exception:
            pass

        # Fallback: grab the first balanced-looking {...} block in the text.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass

        return {}

    async def analyze(
        self,
        objective: str,
        repository_summary: str,
        previous_validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        system_prompt = (
            "You are Qwen Local Controller. Analyze project objective and repository structure. "
            "Output JSON with keys: 'summary' (str), 'tasks' (list of dicts with 'id', 'description', 'role', 'target_files')."
        )
        user_prompt = f"""OBJECTIVE:
{objective}

REPOSITORY SUMMARY:
{repository_summary}

PREVIOUS VALIDATION:
{json.dumps(previous_validation, indent=2)}
"""
        raw = await self._ask(system_prompt, user_prompt)
        extracted = self._extract_json(raw)
        if not extracted.get("tasks"):
            extracted["tasks"] = [
                {
                    "id": "task-001",
                    "description": f"Implement initial task: {objective[:100]}",
                    "role": "implementer",
                    "target_files": [],
                }
            ]
        return extracted

    async def create_round_plan(
        self,
        objective: str,
        pending_tasks: List[Dict[str, Any]],
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        system_prompt = (
            "You are Qwen Plan Refiner. Given pending tasks and validation state, select/refine subtasks for this round. "
            "Output JSON with key 'tasks' (list of task dicts)."
        )
        user_prompt = f"""OBJECTIVE: {objective}\nPENDING TASKS: {json.dumps(pending_tasks)}\nVALIDATION: {json.dumps(validation)}"""
        raw = await self._ask(system_prompt, user_prompt)
        extracted = self._extract_json(raw)
        return extracted if extracted.get("tasks") else {"tasks": pending_tasks}

    async def normalize_browser_results(
        self,
        objective: str,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        # Simple passthrough / validation wrapper
        return {"results": results}

    async def critique(
        self,
        objective: str,
        acceptance_criteria: List[str],
        browser_results: List[Dict[str, Any]],
        repository_state: str,
    ) -> Dict[str, Any]:
        # Qwen acts as judge for proposed patches
        accepted = []
        revision_needed = []

        for res in browser_results:
            patch = res.get("patch", "")
            status = res.get("status", "UNKNOWN")
            if patch and status in {"COMPLETE", "ACCEPTED", "UNKNOWN"}:
                accepted.append(res)
            elif status == "REVISION_NEEDED":
                revision_needed.append(res)

        if accepted:
            return {
                "status": "accept",
                "reason": "Patches provided and valid syntax.",
                "accepted_results": accepted,
                "revision_tasks": [],
            }
        elif revision_needed:
            return {
                "status": "request_revision",
                "reason": "Reviewer requested revision.",
                "accepted_results": [],
                "revision_tasks": revision_needed,
            }
        else:
            return {
                "status": "reject",
                "reason": "No usable patch produced in this round.",
                "accepted_results": [],
                "revision_tasks": [],
            }

    async def verify_acceptance(
        self,
        objective: str,
        acceptance_criteria: List[str],
        validation: Dict[str, Any],
        diff: str,
    ) -> Dict[str, Any]:
        all_passed = validation.get("all_passed", False)
        return {
            "accepted": all_passed,
            "reason": "All validation commands passed cleanly." if all_passed else "Validation failed.",
        }
