from __future__ import annotations

import json
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


class TaskPlanner:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def plan(
        self,
        run_id: str,
        objective: str,
        acceptance_criteria: Optional[List[str]] = None,
        repo_summary: str = "",
    ) -> List[Task]:
        user_prompt = f"""OBJECTIVE:
{objective}

ACCEPTANCE CRITERIA:
{json.dumps(acceptance_criteria or [])}

REPOSITORY CONTEXT:
{repo_summary}
"""
        req = AgentRequest(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            role="planner",
        )

        resp = await self.router.execute(req)
        tasks_data = []

        if resp.structured_data and "tasks" in resp.structured_data:
            tasks_data = resp.structured_data["tasks"]
        else:
            try:
                # Try finding JSON block
                start = resp.content.find("{")
                end = resp.content.rfind("}")
                if start != -1 and end != -1:
                    data = json.loads(resp.content[start : end + 1])
                    tasks_data = data.get("tasks", [])
            except Exception:
                pass

        if not tasks_data:
            # Deterministic fallback task
            tasks_data = [
                {
                    "id": "T-01",
                    "objective": objective,
                    "description": "Execute core objective and verify all criteria",
                    "dependencies": [],
                    "priority": "HIGH",
                    "risk": "LOW",
                    "required_capabilities": [],
                    "validation_strategy": "standard",
                    "target_files": [],
                }
            ]

        tasks = []
        for d in tasks_data:
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

        return tasks
