from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional
from .response_capture import ProgressCallback, supports_kwarg
from .session import BrowserSession


class BrowserPool:
    def __init__(self, sessions: Dict[str, BrowserSession]):
        self.sessions = sessions
        self.locks = {role: asyncio.Lock() for role in sessions}
        self._closed = False

    async def initialize_all(
        self,
        target_url: str = "https://chatgpt.com",
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        self._closed = False

        async def initialize_one(role: str, session: BrowserSession) -> tuple[str, Exception | None]:
            try:
                if on_progress is not None and supports_kwarg(session.initialize, "on_progress"):
                    await session.initialize(target_url=target_url, on_progress=on_progress)
                else:
                    await session.initialize(target_url=target_url)
                return role, None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return role, exc

        results = await asyncio.gather(
            *(initialize_one(role, session) for role, session in self.sessions.items())
        )
        failures = {
            role: str(error)[:500]
            for role, error in results
            if error is not None
        }
        if failures:
            await self.close_all()
            detail = "; ".join(f"{role}: {error}" for role, error in failures.items())
            raise RuntimeError(f"browser pool initialization failed: {detail}")

    def resource_manifest(self) -> Dict[str, Any]:
        resources = []
        for role, session in sorted(self.sessions.items()):
            cdp_url = getattr(session, "cdp_url", None)
            browser_channel = str(getattr(session, "browser_channel", "") or "chromium")
            profile = getattr(session, "user_data_dir", None)
            target_url = str(getattr(session, "target_url", "") or "")
            resources.append({
                "resource_id": f"browser:{role}",
                "role": role,
                "engine": "cdp" if cdp_url else browser_channel,
                "profile": str(profile) if profile is not None else None,
                "state": "READY" if bool(getattr(session, "is_live", False)) else "OFFLINE",
                "capacity": 1,
                "capabilities": {
                    "browser": True,
                    "chat": target_url.startswith("https://chatgpt.com"),
                    "persistent_profile": bool(cdp_url or profile),
                    "cdp_attach": bool(cdp_url),
                    "headed": not bool(getattr(session, "headless", False)),
                    "isolated_role": True,
                },
            })
        return {
            "resource_type": "browser",
            "max_concurrency": len(resources),
            "resources": resources,
        }

    async def submit(
        self,
        role: str,
        task: Dict[str, Any],
        prompt: str,
        round_number: int,
        timeout_seconds: int = 600,
        *,
        on_progress: Optional[ProgressCallback] = None,
        new_chat: bool = False,
        conversation_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = self.sessions.get(role) or list(self.sessions.values())[0]
        lock = self.locks.get(role) or list(self.locks.values())[0]

        # Per-role lock serializes access to a single Edge tab/profile while
        # different roles run concurrently. Cancellation propagates (RF-017).
        # Heartbeat: on_progress(fase, timestamp) é repassado à sessão para o
        # provider reportar durante gerações longas (sem isso o relay declara
        # WORKER_LOST).
        async with lock:
            # Uma página segura uma conversa por vez: posiciona ANTES de enviar,
            # ainda sob lock, para dois assentos nunca dividirem o mesmo chat.
            adapter = getattr(session, "adapter", None)
            if adapter is None:
                from .site_adapter import ChatSiteAdapter
                page = getattr(session, "page", None)
                if page is None:
                    raise RuntimeError("BrowserSession sem página inicializada")
                adapter = ChatSiteAdapter(page)
                session.adapter = adapter
            if new_chat:
                await adapter.open_new_chat()
            elif conversation_url:
                await adapter.open_conversation(conversation_url)
            if on_progress is not None and supports_kwarg(session.ask, "on_progress"):
                inner = session.ask(
                    prompt, timeout_seconds=timeout_seconds, on_progress=on_progress
                )
            else:
                inner = session.ask(prompt, timeout_seconds=timeout_seconds)
            response_text = await asyncio.wait_for(
                inner,
                timeout=timeout_seconds + 10,
            )

        return {
            "role": role,
            "task_id": task.get("id", "task-unknown"),
            "raw_response": response_text,
        }

    async def close_all(self) -> None:
        """Fecha todas as sessões de forma idempotente; nunca levanta."""
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.gather(
                *(session.close() for session in self.sessions.values()),
                return_exceptions=True,
            )
        except Exception:
            pass
