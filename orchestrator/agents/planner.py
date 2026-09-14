from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..models import Task, TaskPriority, TaskStatus, TokenUsage
from ..providers.base import AgentProvider, AgentRequest
from .router import ModelRouter


PLANNER_SYSTEM_PROMPT = """You are the OMA Task Planner.
Your job is to decompose an overarching software or technical objective into a Directed Acyclic Graph (DAG) of well-defined subtasks.

Rules:
1. Each task must have a unique ID (e.g. 'T-01', 'T-02').
2. Explicitly specify dependencies: a task can only depend on tasks that must precede it.
3. Assign priority: CRITICAL, HIGH, MEDIUM, or LOW.
4. Keep the decomposition balanced (avoid creating more than 5 tasks unless absolutely necessary).
5. Output MUST be valid JSON with a 'tasks' array.
6. Respond with ONLY the JSON: no prose before or after it.
7. Escape every double quote inside strings with a backslash (e.g. \"name\").
   Unescaped inner quotes produce invalid JSON and your answer is rejected.

JSON Schema:
{
  "tasks": [
    {
      "id": "T-01",
      "objective": "Concise task goal",
      "description": "Clear step-by-step description",
      "dependencies": [],
      "priority": "HIGH",
      "risk": "LOW",
      "required_capabilities": ["python"],
      "validation_strategy": "standard",
      "target_files": []
    }
  ]
}
"""


def _extract_tasks(content: str) -> List[Any]:
    """Parse the tasks array from model output.

    Prefers a ```json fenced block (models wrap answers in fences); falls
    back to the first-{ to last-} slice. Raises ValueError when unparseable
    or when no tasks array is present — callers decide retry vs abort.
    A silent single-task fallback here once burned whole runs (1 task with
    the raw objective instead of the planned DAG), so this never invents
    tasks: no JSON, no plan.
    """
    text = content or ""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fence.group(1)] if fence else []
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception as exc:  # noqa: BLE001 - trying next candidate
            last_error = exc
            continue
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        if isinstance(tasks, list) and tasks:
            return tasks
        last_error = ValueError("no non-empty 'tasks' array in planner JSON")
    raise ValueError(f"planner returned no parseable task JSON ({last_error})")


class TaskPlanner:
    #: Bounded planning attempts: the first uses the base prompt, retries
    #: append a strict JSON-only repair note (same seat continuation).
    max_attempts: int = 3

    def __init__(self, router: ModelRouter):
        self.router = router

    async def plan(
        self,
        run_id: str,
        objective: str,
        acceptance_criteria: Optional[List[str]] = None,
        repo_summary: str = "",
    ) -> List[Task]:
        base_prompt = f"""OBJECTIVE:
{objective}

ACCEPTANCE CRITERIA:
{json.dumps(acceptance_criteria or [])}

REPOSITORY CONTEXT:
{repo_summary}
"""
        tasks_data: List[Any] = []
        last_error = "no attempt made"
        for attempt in range(max(1, self.max_attempts)):
            user_prompt = base_prompt
            if attempt:
                user_prompt += (
                    "\nSUA RESPOSTA ANTERIOR NAO ERA JSON VALIDO. "
                    "Responda APENAS com o JSON (sem cercas de codigo, sem prosa), "
                    "com array 'tasks', e escape aspas internas com backslash.\n"
                )
            req = AgentRequest(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                role="planner",
            )
            resp = await self.router.execute(req)
            if not resp.success:
                last_error = resp.error or "planner provider failed"
                continue
            if resp.structured_data and "tasks" in resp.structured_data:
                tasks_data = resp.structured_data["tasks"]
                break
            try:
                tasks_data = _extract_tasks(resp.content)
                break
            except ValueError as exc:
                last_error = str(exc)
                continue

        if not tasks_data:
            raise RuntimeError(f"planner failed after attempts: {last_error}")

        if not isinstance(tasks_data, list) or len(tasks_data) > 200:
            raise ValueError("planner must return at most 200 tasks")
        tasks = []
        for d in tasks_data:
            if not isinstance(d, dict):
                raise ValueError("planner task must be an object")
            t = Task(
                id=d.get("id", f"T-{len(tasks) + 1:02d}"),
                run_id=run_id,
                objective=d.get("objective", objective),
                description=d.get("description", ""),
                dependencies=d.get("dependencies", []),
                priority=TaskPriority(d.get("priority", "MEDIUM").upper())
                if d.get("priority", "MEDIUM").upper() in TaskPriority.__members__
                else TaskPriority.MEDIUM,
                risk=d.get("risk", "LOW"),
                required_capabilities=d.get("required_capabilities", []),
                validation_strategy=d.get("validation_strategy", "standard"),
                target_files=d.get("target_files", []),
            )
            tasks.append(t)

        by_id = {t.id: t for t in tasks}
        if len(by_id) != len(tasks) or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", t.id) for t in tasks):
            raise ValueError("planner task IDs must be unique and path-safe")
        done = set()
        for task in tasks:
            if not isinstance(task.dependencies, list) or any(d not in by_id for d in task.dependencies):
                raise ValueError("unknown dependency in planner DAG")
        while len(done) < len(tasks):
            ready = {t.id for t in tasks if set(t.dependencies) <= done} - done
            if not ready:
                raise ValueError("planner returned a cyclic DAG")
            done.update(ready)

        return tasks
