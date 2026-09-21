"""Controlled Playwright browser sessions exposed through SENTRA MCP."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from browser.session import BrowserSession

from ..audit import AuditLogger
from ..config import MCPConfig


class BrowserControlService:
    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        *,
        session_factory: Callable[..., BrowserSession] = BrowserSession,
    ) -> None:
        self.config = config
        self.audit = audit
        self.session_factory = session_factory
        self.sessions: dict[str, dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self.screenshot_root = config.allowed_roots[0] / ".sentra" / "screenshots"

    @staticmethod
    def _validate_selector(selector: str) -> str:
        if not selector or len(selector) > 500 or "\x00" in selector:
            raise ValueError("selector must be 1..500 characters")
        return selector

    @staticmethod
    def _validate_url_sync(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("browser URL must be absolute http/https")
        host = parsed.hostname
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
        except OSError as exc:
            raise ValueError("browser hostname could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
                raise PermissionError("browser navigation to private/local networks is blocked")
        return url

    async def _validate_url(self, url: str) -> str:
        return await asyncio.to_thread(self._validate_url_sync, url)

    async def _install_network_guard(self, session: BrowserSession) -> None:
        if session.context is None:
            return

        async def guard(route, request):
            try:
                await self._validate_url(request.url)
            except Exception:
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await session.context.route("**/*", guard)

    def _owned(self, session_id: str, owner: str) -> dict[str, Any]:
        item = self.sessions.get(session_id)
        if item is None:
            raise FileNotFoundError("browser session not found")
        if item["owner"] != owner:
            raise PermissionError("browser session belongs to another owner")
        return item

    async def open(self, owner: str, url: str = "https://chatgpt.com", *, headless: bool = False, cdp_url: str | None = None) -> dict[str, Any]:
        if not owner.strip():
            raise ValueError("owner is required")
        await self._validate_url(url)
        if cdp_url:
            parsed_cdp = urlparse(cdp_url)
            if parsed_cdp.scheme not in {"http", "https", "ws", "wss"} or not parsed_cdp.hostname:
                raise ValueError("CDP URL must be an absolute HTTP(S)/WS(S) URL")
            try:
                cdp_ip = ipaddress.ip_address(socket.gethostbyname(parsed_cdp.hostname))
            except (OSError, ValueError) as exc:
                raise ValueError("CDP hostname could not be resolved") from exc
            if not cdp_ip.is_loopback:
                raise PermissionError("CDP attachment is restricted to loopback")
        session_id = str(uuid.uuid4())
        session = self.session_factory(
            role=f"mcp-{session_id[:8]}",
            headless=headless,
            cdp_url=cdp_url,
            target_url="about:blank",
            storage_state_path=None,
        )
        await session.initialize("about:blank")
        if not session.is_live:
            await session.close()
            raise RuntimeError("browser session failed to initialize")
        await self._install_network_guard(session)
        if session.page is None:
            await session.close()
            raise RuntimeError("browser page unavailable")
        await session.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        async with self.lock:
            self.sessions[session_id] = {
                "owner": owner,
                "session": session,
                "created": time.time(),
            }
        self.audit.emit("browser.open", "ok", {"session_id": session_id, "owner": owner, "url": url})
        return {"session_id": session_id, "owner": owner, "url": session.page.url if session.page else url}

    async def tabs(self, owner: str) -> dict[str, Any]:
        result = []
        for session_id, item in list(self.sessions.items()):
            if item["owner"] != owner:
                continue
            session = item["session"]
            result.append({
                "session_id": session_id,
                "url": session.page.url if session.page and not session.page.is_closed() else "",
                "live": session.is_live,
                "created": item["created"],
            })
        return {"tabs": result}

    async def navigate(self, session_id: str, owner: str, url: str) -> dict[str, Any]:
        item = self._owned(session_id, owner)
        await self._validate_url(url)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.audit.emit("browser.navigate", "ok", {"session_id": session_id, "owner": owner, "url": page.url})
        return {"session_id": session_id, "url": page.url}

    async def extract(self, session_id: str, owner: str, selector: str = "body", max_chars: int = 200000) -> dict[str, Any]:
        item = self._owned(session_id, owner)
        selector = self._validate_selector(selector)
        if not 1 <= max_chars <= 1_000_000:
            raise ValueError("max_chars must be between 1 and 1000000")
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        text = await page.locator(selector).first.inner_text(timeout=30000)
        truncated = len(text) > max_chars
        return {"text": text[:max_chars], "truncated": truncated, "url": page.url}

    async def screenshot(self, session_id: str, owner: str, *, full_page: bool = True) -> dict[str, Any]:
        item = self._owned(session_id, owner)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        self.screenshot_root.mkdir(parents=True, exist_ok=True)
        target = self.screenshot_root / f"{session_id}-{int(time.time()*1000)}.png"
        await page.screenshot(path=str(target), full_page=bool(full_page))
        size = target.stat().st_size
        if size > self.config.max_read_bytes:
            target.unlink(missing_ok=True)
            raise ValueError("screenshot exceeds configured read limit")
        import base64
        encoded = base64.b64encode(target.read_bytes()).decode("ascii")
        self.audit.emit("browser.screenshot", "ok", {"session_id": session_id, "owner": owner, "bytes": size})
        return {"path": str(target), "bytes": size, "mime_type": "image/png", "image_base64": encoded, "url": page.url}

    async def click(self, session_id: str, owner: str, selector: str) -> dict[str, Any]:
        item = self._owned(session_id, owner)
        selector = self._validate_selector(selector)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        await page.locator(selector).first.click(timeout=30000)
        self.audit.emit("browser.click", "ok", {"session_id": session_id, "owner": owner, "selector": selector})
        return {"session_id": session_id, "url": page.url}

    async def type_text(self, session_id: str, owner: str, selector: str, text: str, *, clear: bool = False) -> dict[str, Any]:
        item = self._owned(session_id, owner)
        selector = self._validate_selector(selector)
        if len(text.encode("utf-8")) > self.config.max_write_bytes:
            raise ValueError("browser input exceeds write limit")
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        locator = page.locator(selector).first
        if clear:
            await locator.fill(text, timeout=30000)
        else:
            await locator.type(text, timeout=30000)
        self.audit.emit("browser.type", "ok", {"session_id": session_id, "owner": owner, "bytes": len(text.encode("utf-8"))})
        return {"session_id": session_id, "url": page.url}

    async def close(self, session_id: str, owner: str) -> dict[str, Any]:
        item = self._owned(session_id, owner)
        await item["session"].close()
        self.sessions.pop(session_id, None)
        self.audit.emit("browser.close", "ok", {"session_id": session_id, "owner": owner})
        return {"session_id": session_id, "closed": True}

    async def shutdown(self) -> None:
        for session_id, item in list(self.sessions.items()):
            try:
                await item["session"].close()
            except Exception:
                pass
            self.sessions.pop(session_id, None)
