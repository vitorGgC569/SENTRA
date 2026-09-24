from __future__ import annotations

import asyncio
from types import SimpleNamespace

from orchestrator.dispatcher import Orchestrator
from orchestrator.state_machine import Phase


def test_dispatch_respects_browser_runtime_capacity():
    class State:
        def __init__(self):
            self.pending_tasks = [
                {
                    "id": f"T-{i}",
                    "description": f"task {i}",
                    "role": "implementer",
                    "target_files": [],
                }
                for i in range(5)
            ]
            self.round_number = 1
            self.validation = {}
            self.browser_results = []
            self.phase = Phase.DISPATCH
            self.logs = []

        def log(self, message):
            self.logs.append(message)

    class Pool:
        def __init__(self):
            self.calls = []

        def resource_manifest(self):
            return {"max_concurrency": 2, "resources": [{}, {}]}

        async def submit(self, *, role, task, prompt, round_number):
            self.calls.append(task["id"])
            return {"task_id": task["id"], "raw_response": "ok"}

    async def probe():
        obj = object.__new__(Orchestrator)
        obj.state = State()
        obj.spec = SimpleNamespace(
            max_parallel_sessions=4,
            job_id="J1",
            entry_prompt="goal",
            acceptance_criteria=[],
        )
        obj.browser_pool = Pool()

        await Orchestrator.dispatch(obj)

        assert obj.browser_pool.calls == ["T-0", "T-1"]
        assert len(obj.state.browser_results) == 2
        assert obj.state.phase == Phase.COLLECT
        assert any("Browser runtime capacity: 2" in line for line in obj.state.logs)

    asyncio.run(probe())
