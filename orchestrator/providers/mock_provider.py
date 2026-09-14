from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from .base import AgentProvider, AgentRequest, AgentResponse
from ..models import TokenUsage


class MockProvider:
    """
    Deterministic provider for automated testing, benchmarks, and offline simulation.
    Can be configured with custom response handlers, pre-programmed responses, or default mock behaviors.
    """

    def __init__(
        self,
        default_response: Optional[str] = None,
        custom_handler: Optional[Callable[[AgentRequest], AgentResponse]] = None,
        model_name: str = "mock-model",
    ):
        self.default_response = default_response or "MOCK_RESPONSE_OK"
        self.custom_handler = custom_handler
        self.model_name = model_name
        self.history: List[AgentRequest] = []
        self.should_fail: bool = False
        self.failure_error: str = "Mock provider simulated network/service failure"

    async def execute(self, request: AgentRequest) -> AgentResponse:
        self.history.append(request)
        start_time = time.time()

        if self.should_fail:
            return AgentResponse(
                content="",
                token_usage=TokenUsage(model=self.model_name),
                latency=0.001,
                success=False,
                error=self.failure_error,
                model=self.model_name,
            )

        if self.custom_handler:
            return self.custom_handler(request)

        # Default intelligent response generation based on request role
        content = self._generate_default_content(request)
        structured = None
        try:
            structured = json.loads(content)
        except Exception:
            pass

        return AgentResponse(
            content=content,
            structured_data=structured,
            token_usage=TokenUsage(
                input_tokens=len(request.user_prompt) // 4,
                output_tokens=len(content) // 4,
                model=self.model_name,
            ),
            latency=0.005,
            success=True,
            model=self.model_name,
        )

    def _generate_default_content(self, request: AgentRequest) -> str:
        role = request.role.lower()

        if "planner" in role or "decomposer" in role:
            return json.dumps({
                "tasks": [
                    {
                        "id": "T-01",
                        "objective": "Implement core logic",
                        "description": "Create base module implementation",
                        "dependencies": [],
                        "priority": "HIGH",
                        "risk": "LOW",
                        "required_capabilities": ["python"],
                        "validation_strategy": "standard",
                    },
                    {
                        "id": "T-02",
                        "objective": "Add tests and validation",
                        "description": "Create unit tests verifying correctness",
                        "dependencies": ["T-01"],
                        "priority": "MEDIUM",
                        "risk": "LOW",
                        "required_capabilities": ["pytest"],
                        "validation_strategy": "deterministic",
                    },
                ]
            })

        if "executor" in role or "implementer" in role:
            if (request.metadata.get("repository_session_id")
                    and len(request.metadata.get("messages", [])) == 2):
                # Exercise the actual same-worker repository roundtrip in offline E2Es.
                return "[[R|math_utils.py|1|40]]"
            if request.metadata.get("task_id") == "T-02":
                return (
                    "BEGIN_RESULT\nSTATUS: COMPLETE\nSUMMARY: Added boundary tests.\nPATCH:\n```diff\n"
                    "--- /dev/null\n+++ b/tests/test_factorial_edges.py\n@@ -0,0 +1,6 @@\n"
                    "+import pytest\n+from math_utils import factorial\n+def test_zero():\n"
                    "+    assert factorial(0) == 1\n+def test_negative():\n"
                    "+    with pytest.raises(ValueError): factorial(-1)\n"
                    "```\nVALIDATION_COMMANDS:\n- [[TEST|all]]\nEND_RESULT")
            return (
                "BEGIN_RESULT\n"
                "STATUS: COMPLETE\n"
                "SUMMARY: Implemented solution successfully.\n"
                "PATCH:\n"
                "```diff\n"
                "--- a/math_utils.py\n"
                "+++ b/math_utils.py\n"
                "@@ -0,0 +1,4 @@\n"
                "+def factorial(n: int) -> int:\n"
                "+    if n < 0:\n"
                "+        raise ValueError('Negative not allowed')\n"
                "+    return 1 if n <= 1 else n * factorial(n - 1)\n"
                "--- /dev/null\n+++ b/tests/test_factorial.py\n@@ -0,0 +1,3 @@\n"
                "+from math_utils import factorial\n+def test_factorial():\n+    assert factorial(5) == 120\n"
                "```\n"
                "VALIDATION_COMMANDS:\n"
                "- [[TEST|all]]\n"
                "END_RESULT"
            )

        if "validator" in role:
            return json.dumps({
                "status": "APPROVED",
                "confidence": 0.95,
                "score": 9.5,  # Scripted demo evidence, never a real-model calibration.
                "summary": "Validation passed without errors.",
                "requirements_checked": request.metadata.get("acceptance_criteria", ["RF-001", "RF-002"]),
                "findings": [],
                "tests": [{"name": "test_basic", "status": "PASS"}],
                "recommended_action": "PROMOTE",
            })

        if "repair" in role:
            return (
                "BEGIN_RESULT\n"
                "STATUS: COMPLETE\n"
                "SUMMARY: Fixed reported validation issues.\n"
                "PATCH:\n"
                "```diff\n"
                "--- a/math_utils.py\n"
                "+++ b/math_utils.py\n"
                "@@ -0,0 +1 @@\n"
                "+# Added type assertions\n"
                "```\n"
                "VALIDATION_COMMANDS:\n"
                "- [[TEST|all]]\n"
                "END_RESULT"
            )

        if "master" in role:
            return json.dumps({
                "decision": "APPROVED",
                "confidence": 0.98,
                "critical_issues": [],
                "remaining_risks": [],
                "needs_more_work": False,
                "final_response": "The solution meets all quality and functional requirements.",
                "reasoning": "All validators approved and objective tests passed with 100% confidence.",
            })

        return self.default_response
