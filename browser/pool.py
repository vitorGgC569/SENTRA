from __future__ import annotations

import asyncio
from typing import Dict, Any
from .session import BrowserSession


class BrowserPool:
    def __init__(self, sessions: Dict[str, BrowserSession]):
        self.sessions = sessions
        self.locks = {role: asyncio.Lock() for role in sessions}

    async def initialize_all(self, target_url: str = "https://chatgpt.com") -> None:
        for role, session in self.sessions.items():
            await session.initialize(target_url=target_url)

    async def submit(
        self,
        role: str,
        task: Dict[str, Any],
        prompt: str,
        round_number: int,
        timeout_seconds: int = 600,
    ) -> Dict[str, Any]:
        session = self.sessions.get(role) or list(self.sessions.values())[0]
        lock = self.locks.get(role) or list(self.locks.values())[0]

        # Per-role lock serializes access to a single Edge tab/profile while
        # different roles run concurrently. Cancellation propagates (RF-017).
        async with lock:
            response_text = await asyncio.wait_for(
                session.ask(prompt, timeout_seconds=timeout_seconds),
                timeout=timeout_seconds + 10,
            )

        return {
            "role": role,
            "task_id": task.get("id", "task-unknown"),
            "raw_response": response_text,
        }

    async def close_all(self) -> None:
        for session in self.sessions.values():
            await session.close()
