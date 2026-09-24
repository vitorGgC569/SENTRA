"""Unified controlled browser sessions over Playwright and the SENTRA Edge relay."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from browser.session import BrowserSession

from ..audit import AuditLogger
from ..config import MCPConfig
from ..errors import SentraSemanticError


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
        self.edge_sessions: dict[str, dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self.screenshot_root = config.state_root / "screenshots"
        self.relay_url = self._configured_relay_url()
        self.relay_token_path = config.state_root / "browser" / "relay-token"

    @staticmethod
    def _configured_relay_url() -> str:
        raw = os.environ.get("SENTRA_EDGE_RELAY_URL", "http://127.0.0.1:8765").strip()
        parsed = urlparse(raw)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("SENTRA_EDGE_RELAY_URL must be a loopback http URL")
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            loopback = ip.is_loopback
        except ValueError:
            loopback = parsed.hostname.casefold() == "localhost"
        if not loopback:
            raise ValueError("SENTRA_EDGE_RELAY_URL must target loopback")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("SENTRA_EDGE_RELAY_URL must not include path/query/fragment")
        port = parsed.port or 80
        if not 1 <= port <= 65535:
            raise ValueError("SENTRA_EDGE_RELAY_URL has an invalid port")
        host = "[::1]" if parsed.hostname == "::1" else parsed.hostname
        return f"http://{host}:{port}"

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
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    host,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                )
            }
        except OSError as exc:
            raise ValueError("browser hostname could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_reserved
            ):
                raise PermissionError("browser navigation to private/local networks is blocked")
        return url

    async def _validate_url(self, url: str) -> str:
        return await asyncio.to_thread(self._validate_url_sync, url)

    @staticmethod
    def _is_chatgpt_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        return parsed.scheme == "https" and parsed.hostname == "chatgpt.com"

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

    def _owned_playwright(self, session_id: str, owner: str) -> dict[str, Any]:
        item = self.sessions.get(session_id)
        if item is None:
            raise FileNotFoundError("browser session not found")
        if item["owner"] != owner:
            raise PermissionError("browser session belongs to another owner")
        return item

    def _owned_edge(self, session_id: str, owner: str) -> dict[str, Any]:
        item = self.edge_sessions.get(session_id)
        if item is None:
            raise FileNotFoundError("Edge browser session not found or not reserved")
        if item["owner"] != owner:
            raise PermissionError("Edge browser session belongs to another owner")
        return item

    def _relay_token(self) -> str:
        try:
            token = self.relay_token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("Edge relay token is unavailable; start SENTRA relay first") from exc
        if len(token) < 32:
            raise RuntimeError("Edge relay token is invalid")
        return token

    def _relay_request_sync(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        authenticated: bool = True,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self._relay_token()
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.relay_url + path,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read(1024 * 1024)
                return json.loads(raw or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(65536)).get("error", str(exc))
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"Edge relay HTTP {exc.code}: {detail}") from exc
        except OSError as exc:
            raise RuntimeError("Edge relay is unavailable") from exc

    async def _edge_health(self) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                self._relay_request_sync,
                "/health",
                authenticated=False,
                timeout=2.0,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}

    async def _edge_workers(self) -> list[str]:
        health = await self._edge_health()
        return [
            str(worker)
            for worker in health.get("workers_online", [])
            if isinstance(worker, str) and worker.startswith("TAB-")
        ]

    def _edge_submit_sync(
        self,
        worker: str | None,
        *,
        kind: str,
        browser_action: str = "",
        browser_args: dict[str, Any] | None = None,
        timeout_s: int = 20,
    ) -> dict[str, Any]:
        task_id = "mcp-browser-" + uuid.uuid4().hex
        payload: dict[str, Any] = {
            "task_id": task_id,
            "prompt": "",
            "timeout_s": max(5, min(int(timeout_s), 120)),
            "new_chat": False,
            "kind": kind,
        }
        if worker:
            payload["target_worker"] = worker
        if kind == "BROWSER_ACTION":
            payload["browser_action"] = browser_action
            payload["browser_args"] = dict(browser_args or {})
        submitted = self._relay_request_sync(
            "/jobs/submit",
            method="POST",
            payload=payload,
            timeout=5.0,
        )
        job_id = str(submitted["job_id"])
        deadline = time.monotonic() + max(5, min(timeout_s, 120))
        try:
            while time.monotonic() < deadline:
                remaining = max(0.1, min(20.0, deadline - time.monotonic()))
                query = urllib.parse.urlencode({"job_id": job_id, "timeout_s": remaining})
                result = self._relay_request_sync(
                    "/jobs/wait?" + query,
                    timeout=remaining + 2,
                )
                if result.get("pending"):
                    continue
                if result.get("status") != "COMPLETED":
                    raise RuntimeError(str(result.get("error") or "Edge browser action failed"))
                raw = result.get("result") or "{}"
                decoded = json.loads(raw) if isinstance(raw, str) else raw
                try:
                    self._relay_request_sync(
                        "/jobs/ack",
                        method="POST",
                        payload={"job_id": job_id},
                        timeout=3.0,
                    )
                except Exception:
                    pass
                if isinstance(decoded, dict):
                    decoded.setdefault("worker", result.get("worker") or worker)
                    return decoded
                return {"result": decoded, "worker": result.get("worker") or worker}
            raise TimeoutError("Edge browser action timed out")
        except Exception:
            try:
                self._relay_request_sync(
                    "/jobs/cancel",
                    method="POST",
                    payload={"job_id": job_id},
                    timeout=3.0,
                )
            except Exception:
                pass
            raise

    async def _edge_action(
        self,
        worker: str | None,
        action: str,
        args: dict[str, Any],
        *,
        timeout_s: int = 20,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._edge_submit_sync,
            worker,
            kind="BROWSER_ACTION",
            browser_action=action,
            browser_args=args,
            timeout_s=timeout_s,
        )


    def _chat_phase_sync(
        self,
        worker: str | None,
        *,
        kind: str,
        prompt: str = "",
        conversation_url: str | None = None,
        timeout_s: int = 180,
    ) -> dict[str, Any]:
        task_id = "mcp-research-" + uuid.uuid4().hex
        payload: dict[str, Any] = {
            "task_id": task_id,
            "prompt": prompt,
            "timeout_s": max(10, min(int(timeout_s), 600)),
            "new_chat": kind == "CHAT_START",
            "kind": kind,
        }
        if worker:
            payload["target_worker"] = worker
        if conversation_url:
            payload["conversation_url"] = conversation_url
        submitted = self._relay_request_sync(
            "/jobs/submit",
            method="POST",
            payload=payload,
            timeout=5.0,
        )
        job_id = str(submitted["job_id"])
        deadline = time.monotonic() + payload["timeout_s"]
        try:
            while time.monotonic() < deadline:
                remaining = max(0.1, min(20.0, deadline - time.monotonic()))
                query = urllib.parse.urlencode(
                    {"job_id": job_id, "timeout_s": remaining}
                )
                result = self._relay_request_sync(
                    "/jobs/wait?" + query,
                    timeout=remaining + 2,
                )
                if result.get("pending"):
                    continue
                if result.get("status") != "COMPLETED":
                    raise RuntimeError(
                        str(result.get("error") or f"{kind} failed")
                    )
                try:
                    self._relay_request_sync(
                        "/jobs/ack",
                        method="POST",
                        payload={"job_id": job_id},
                        timeout=3.0,
                    )
                except Exception:
                    pass
                raw = result.get("result")
                decoded: dict[str, Any] = {}
                if kind == "CHAT_START" and isinstance(raw, str) and raw:
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        value = {}
                    if isinstance(value, dict):
                        decoded = value
                return {
                    "job_id": job_id,
                    "worker": result.get("worker") or worker,
                    "text": "" if kind == "CHAT_START" else str(raw or ""),
                    "conversation_url": (
                        result.get("conversation_url")
                        or decoded.get("conversation_url")
                        or conversation_url
                    ),
                    "conversation_id": (
                        result.get("conversation_id")
                        or decoded.get("conversation_id")
                    ),
                    **({"started": bool(decoded.get("started"))} if kind == "CHAT_START" else {}),
                }
            raise TimeoutError(f"{kind} timed out")
        except Exception:
            try:
                self._relay_request_sync(
                    "/jobs/cancel",
                    method="POST",
                    payload={"job_id": job_id},
                    timeout=3.0,
                )
            except Exception:
                pass
            raise

    async def chat_start(
        self,
        owner: str,
        prompt: str,
        *,
        timeout_s: int = 90,
    ) -> dict[str, Any]:
        """Start a fresh ChatGPT conversation and return its id without waiting.

        A single READY Edge controller tab can start many conversations
        sequentially; generations continue server-side and are collected later
        by conversation id/URL.
        """
        if not prompt or len(prompt) > 200_000:
            raise ValueError("research prompt must be 1..200000 characters")
        result = await asyncio.to_thread(
            self._chat_phase_sync,
            None,
            kind="CHAT_START",
            prompt=prompt,
            timeout_s=timeout_s,
        )
        if not result.get("conversation_id") or not result.get("conversation_url"):
            raise RuntimeError("CHAT_START returned no conversation identity")
        self.audit.emit(
            "research.chat_start",
            "ok",
            {
                "owner": owner,
                "worker": result.get("worker"),
                "conversation_id": result.get("conversation_id"),
            },
        )
        return result

    async def chat_collect(
        self,
        owner: str,
        conversation_url: str,
        *,
        timeout_s: int = 180,
    ) -> dict[str, Any]:
        """Collect one server-side generation by conversation id/URL."""
        if not self._is_chatgpt_url(conversation_url):
            raise ValueError("conversation_url must target https://chatgpt.com")
        result = await asyncio.to_thread(
            self._chat_phase_sync,
            None,
            kind="CHAT_COLLECT",
            conversation_url=conversation_url,
            timeout_s=timeout_s,
        )
        self.audit.emit(
            "research.chat_collect",
            "ok",
            {
                "owner": owner,
                "worker": result.get("worker"),
                "conversation_id": result.get("conversation_id"),
            },
        )
        return result

    def _delete_chat_sync(
        self,
        worker: str | None,
        conversation_url: str,
        timeout_s: int = 30,
    ) -> dict[str, Any]:
        task_id = "mcp-delete-chat-" + uuid.uuid4().hex
        payload = {
            "task_id": task_id,
            "prompt": "",
            "timeout_s": max(10, min(int(timeout_s), 120)),
            "new_chat": False,
            "conversation_url": conversation_url,
            "kind": "DELETE_CHAT",
        }
        if worker:
            payload["target_worker"] = worker
        submitted = self._relay_request_sync(
            "/jobs/submit", method="POST", payload=payload, timeout=5.0
        )
        job_id = str(submitted["job_id"])
        deadline = time.monotonic() + payload["timeout_s"]
        while time.monotonic() < deadline:
            remaining = max(0.1, min(10.0, deadline - time.monotonic()))
            query = urllib.parse.urlencode({"job_id": job_id, "timeout_s": remaining})
            result = self._relay_request_sync(
                "/jobs/wait?" + query, timeout=remaining + 2
            )
            if result.get("pending"):
                continue
            if result.get("status") != "COMPLETED":
                raise RuntimeError(str(result.get("error") or "DELETE_CHAT failed"))
            try:
                self._relay_request_sync(
                    "/jobs/ack", method="POST", payload={"job_id": job_id}, timeout=3.0
                )
            except Exception:
                pass
            raw = result.get("result")
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"result": raw}
            return raw if isinstance(raw, dict) else {"deleted": True}
        raise TimeoutError("DELETE_CHAT timed out")

    async def delete_chat(
        self,
        owner: str,
        conversation_url: str,
        *,
        timeout_s: int = 30,
    ) -> dict[str, Any]:
        """Delete a temporary ChatGPT conversation through the lazy controller."""
        return await asyncio.to_thread(
            self._delete_chat_sync,
            None,
            conversation_url,
            timeout_s,
        )

    def _edge_cached_status_sync(self, worker: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"worker": worker})
        return self._relay_request_sync(
            "/workers/status?" + query,
            timeout=3.0,
        )

    def _edge_expected_identity_sync(self) -> dict[str, Any]:
        return self._relay_request_sync(
            "/extension/version",
            authenticated=False,
            timeout=3.0,
        )

    async def _edge_worker_status(self, worker: str) -> dict[str, Any]:
        """Classify a relay worker from heartbeat-cached tab status."""
        try:
            cached = await asyncio.to_thread(
                self._edge_cached_status_sync,
                worker,
            )
        except Exception as exc:
            return {
                "worker": worker,
                "worker_state": "UNHEALTHY",
                "usable": False,
                "url": None,
                "status": {},
                "error": str(exc)[:500],
            }

        if not cached.get("online"):
            return {
                "worker": worker,
                "worker_state": "STALE",
                "usable": False,
                "url": None,
                "status": cached.get("status") or {},
                "last_seen": cached.get("last_seen"),
            }

        status = cached.get("status")
        if not isinstance(status, dict):
            status = {}
        try:
            expected = await asyncio.to_thread(self._edge_expected_identity_sync)
        except Exception as exc:
            expected = {"error": str(exc)[:500]}

        expected_version = expected.get("version")
        expected_build = expected.get("build_id")
        expected_source_hash = expected.get("source_hash")
        actual_versions = {
            "sw_version": status.get("sw_version"),
            "cs_version": status.get("cs_version"),
            "sw_build_id": status.get("sw_build_id"),
            "cs_build_id": status.get("cs_build_id"),
            "sw_source_hash": status.get("sw_source_hash"),
            "cs_source_hash": status.get("cs_source_hash"),
        }
        # Heartbeats from legacy/unit-test workers may omit identity entirely.
        # Classify their UI readiness independently here; contract enforcement is
        # performed by capability_manifest/open before any side effect.
        identity_present = any(value is not None for value in actual_versions.values())
        stale_reasons: list[str] = []
        if identity_present and expected_version:
            if actual_versions["sw_version"] != expected_version:
                stale_reasons.append("service-worker version")
            if actual_versions["cs_version"] != expected_version:
                stale_reasons.append("content-script version")
        if identity_present and expected_build:
            if actual_versions["sw_build_id"] != expected_build:
                stale_reasons.append("service-worker build")
            if actual_versions["cs_build_id"] != expected_build:
                stale_reasons.append("content-script build")
        if identity_present and expected_source_hash:
            if actual_versions["sw_source_hash"] != expected_source_hash:
                stale_reasons.append("service-worker source hash")
            if actual_versions["cs_source_hash"] != expected_source_hash:
                stale_reasons.append("content-script source hash")
        if stale_reasons:
            return {
                "worker": worker,
                "worker_state": "STALE",
                "usable": False,
                "url": status.get("url"),
                "status": status,
                "last_seen": cached.get("last_seen"),
                "error_code": "PLUGIN_STALE",
                "error": "PLUGIN_STALE: " + ", ".join(stale_reasons),
                "plugin_identity": {
                    "expected": expected,
                    "actual": actual_versions,
                    "verified": False,
                },
            }

        url = status.get("url")
        if isinstance(url, str) and url and not self._is_chatgpt_url(url):
            return {
                "worker": worker,
                "worker_state": "CONNECTED",
                "usable": False,
                "url": url,
                "status": status,
                "last_seen": cached.get("last_seen"),
                "error_code": "SESSION_WRONG_PLACE",
                "error": "SESSION_WRONG_PLACE: controller is not on chatgpt.com",
                "plugin_identity": {
                    "expected": expected,
                    "actual": actual_versions,
                    "verified": True,
                },
            }
        diagnostics = status.get("diagnostics") or {}
        composer = diagnostics.get("composer") if isinstance(diagnostics, dict) else None
        composer_found = bool(
            status.get("composer_found")
            or (
                isinstance(composer, dict)
                and composer.get("visible")
                and composer.get("editable")
                and not composer.get("disabled")
            )
        )
        ready = bool(
            isinstance(url, str)
            and self._is_chatgpt_url(url)
            and composer_found
            and not status.get("error")
        )
        unhealthy = bool(status.get("error"))
        return {
            "worker": worker,
            "worker_state": (
                "READY" if ready else "UNHEALTHY" if unhealthy else "CONNECTED"
            ),
            "usable": ready,
            "url": url,
            "status": status,
            "last_seen": cached.get("last_seen"),
            "plugin_identity": {
                "expected": expected,
                "actual": actual_versions,
                "verified": bool(
                    identity_present
                    and (not expected_version or actual_versions["sw_version"] == expected_version)
                    and (not expected_version or actual_versions["cs_version"] == expected_version)
                    and (not expected_build or actual_versions["sw_build_id"] == expected_build)
                    and (not expected_build or actual_versions["cs_build_id"] == expected_build)
                    and (
                        not expected_source_hash
                        or actual_versions["sw_source_hash"] == expected_source_hash
                    )
                    and (
                        not expected_source_hash
                        or actual_versions["cs_source_hash"] == expected_source_hash
                    )
                ),
            },
            **(
                {"error": str(status.get("error"))[:500]}
                if unhealthy
                else {}
            ),
        }

    async def _edge_worker_inventory(self) -> list[dict[str, Any]]:
        workers = await self._edge_workers()
        if not workers:
            return []
        return list(await asyncio.gather(
            *(self._edge_worker_status(worker) for worker in workers)
        ))

    async def capability_manifest(self) -> dict[str, Any]:
        """Negotiated target/plugin capabilities and mandatory build identity."""
        try:
            expected = await asyncio.to_thread(self._edge_expected_identity_sync)
        except Exception as exc:
            expected = {"error": str(exc)[:500]}
        health = await self._edge_health()
        inventory = await self._edge_worker_inventory()
        pool = health.get("pool") if isinstance(health, dict) else {}
        pool = pool if isinstance(pool, dict) else {}
        stale = [item for item in inventory if item.get("error_code") == "PLUGIN_STALE"]
        wrong_place = [
            item for item in inventory
            if item.get("error_code") == "SESSION_WRONG_PLACE"
        ]
        verified = [
            item for item in inventory
            if (item.get("plugin_identity") or {}).get("verified") is True
        ]
        identity_required = bool(
            expected.get("version")
            or expected.get("build_id")
            or expected.get("source_hash")
        )
        unverified_online = [
            item for item in inventory
            if identity_required
            and item.get("worker_state") in {"READY", "CONNECTED"}
            and (item.get("plugin_identity") or {}).get("verified") is not True
        ]
        compatibility_error = None
        compatibility_message = None
        if stale:
            compatibility_error = "PLUGIN_STALE"
            compatibility_message = str(stale[0].get("error") or "loaded plugin build is stale")
        elif unverified_online:
            compatibility_error = "PLUGIN_STALE"
            compatibility_message = (
                "PLUGIN_STALE: loaded Edge worker did not publish the required build identity"
            )
        elif wrong_place:
            compatibility_error = "SESSION_WRONG_PLACE"
            compatibility_message = str(
                wrong_place[0].get("error") or "controller is on the wrong target"
            )
        available = bool(pool.get("active") or inventory) and compatibility_error is None
        return {
            "target": "edge",
            "available": available,
            "readiness": (
                "SESSION_READY"
                if any(item.get("worker_state") == "READY" for item in inventory)
                else "PLUGIN_HANDSHAKE"
                if verified
                else "TRANSPORT_CONNECTED"
                if pool.get("active")
                else "UNKNOWN"
            ),
            "expected_plugin_identity": expected,
            "plugin_identity_verified": bool(verified),
            "workers": inventory,
            "pool": pool,
            "capabilities": {
                "navigate": True,
                "extract": True,
                "click": True,
                "type": True,
                "screenshot": "viewport",
                "chat_start": True,
                "chat_collect": True,
                "delete_chat": True,
                "max_controller_tabs": 1,
                "principal_edge_only": True,
                "silent_invasive_fallback": False,
            },
            "compatibility_error": compatibility_error,
            "compatibility_message": compatibility_message,
        }

    async def open(
        self,
        owner: str,
        url: str = "https://chatgpt.com",
        *,
        backend: str = "auto",
        headless: bool = False,
        cdp_url: str | None = None,
        allow_invasive_fallback: bool = False,
    ) -> dict[str, Any]:
        if not owner.strip():
            raise ValueError("owner is required")
        if backend not in {"auto", "playwright", "edge"}:
            raise ValueError("backend must be auto, playwright or edge")
        await self._validate_url(url)

        if backend in {"auto", "edge"} and self._is_chatgpt_url(url):
            inventory = await self._edge_worker_inventory()

            # A browser session can outlive its connector owner when the client
            # disconnects after browser_open. If the relay no longer considers
            # that TAB-* worker online, the reservation is orphaned and must not
            # block the next lazy-controller bootstrap.
            online_workers = {
                item.get("worker")
                for item in inventory
                if isinstance(item.get("worker"), str)
            }
            for stale_session_id, stale_session in list(self.edge_sessions.items()):
                if stale_session.get("worker") in online_workers:
                    continue
                self.edge_sessions.pop(stale_session_id, None)
                self.audit.emit(
                    "browser.session.reclaim",
                    "ok",
                    {
                        "session_id": stale_session_id,
                        "reason": "worker_offline",
                    },
                )

            expected_identity = {}
            try:
                expected_identity = await asyncio.to_thread(
                    self._edge_expected_identity_sync
                )
            except Exception:
                expected_identity = {}
            identity_required = bool(
                expected_identity.get("version")
                or expected_identity.get("build_id")
                or expected_identity.get("source_hash")
            )
            unverified_worker = next(
                (
                    item for item in inventory
                    if identity_required
                    and item.get("worker_state") in {"READY", "CONNECTED"}
                    and (item.get("plugin_identity") or {}).get("verified") is not True
                ),
                None,
            )
            if unverified_worker is not None:
                raise SentraSemanticError(
                    "PLUGIN_STALE",
                    "principal Edge plugin did not publish the required SENTRA build identity",
                    category="compatibility",
                    retryable=True,
                    details={
                        "worker": unverified_worker.get("worker"),
                        "expected": expected_identity,
                        "actual": (unverified_worker.get("plugin_identity") or {}).get("actual"),
                    },
                )
            reserved = {item["worker"] for item in self.edge_sessions.values()}
            available = [
                item["worker"]
                for item in inventory
                if item["worker_state"] == "READY" and item["worker"] not in reserved
            ]

            worker = available[0] if available else None
            result: dict[str, Any] | None = None
            bootstrap_error: Exception | None = None

            # Lazy principal-Edge bootstrap: when the bridge is healthy but idle
            # there is deliberately no TAB-* worker yet. Queue one untargeted,
            # authenticated BROWSER_ACTION so the existing extension adopts its
            # single inactive ChatGPT tab and returns the concrete worker id.
            # Never do this while another MCP Edge session is reserved.
            if worker is None and not self.edge_sessions:
                try:
                    result = await self._edge_action(
                        None,
                        "navigate",
                        {"url": url},
                        timeout_s=30,
                    )
                    claimed = result.get("worker")
                    if not isinstance(claimed, str) or not claimed.startswith("TAB-"):
                        raise RuntimeError(
                            "lazy Edge bootstrap returned no TAB-* worker identity"
                        )
                    worker = claimed
                except Exception as exc:
                    bootstrap_error = exc

            # Another coroutine may have completed a bootstrap while this one
            # awaited the relay. Never let two owners reserve the same controller.
            reserved = {item["worker"] for item in self.edge_sessions.values()}
            if worker is not None and worker in reserved:
                worker = None
                bootstrap_error = RuntimeError("principal Edge controller is already reserved")

            if worker is not None:
                session_id = "edge:" + worker
                self.edge_sessions[session_id] = {
                    "owner": owner,
                    "worker": worker,
                    "created": time.time(),
                }
                try:
                    if result is None:
                        result = await self._edge_action(
                            worker,
                            "navigate",
                            {"url": url},
                        )
                except Exception as exc:
                    self.edge_sessions.pop(session_id, None)
                    raise RuntimeError(
                        "principal Edge browser action failed; "
                        "SENTRA will not fall back to Playwright"
                    ) from exc

                self.audit.emit(
                    "browser.open",
                    "ok",
                    {
                        "session_id": session_id,
                        "owner": owner,
                        "url": result.get("url", url),
                        "backend": "edge",
                    },
                )
                return {
                    "session_id": session_id,
                    "owner": owner,
                    "url": result.get("url", url),
                    "backend": "edge",
                }

            # ChatGPT must never fall back to a fresh Playwright/Edge profile:
            # that would lose the user's authenticated principal-browser session
            # and can silently land on a different/free account. For ChatGPT,
            # both "auto" and "edge" are principal-Edge-only.
            plugin_stale = next(
                (item for item in inventory if item.get("error_code") == "PLUGIN_STALE"),
                None,
            )
            wrong_place = next(
                (item for item in inventory if item.get("error_code") == "SESSION_WRONG_PLACE"),
                None,
            )
            if plugin_stale is not None:
                raise SentraSemanticError(
                    "PLUGIN_STALE",
                    "principal Edge plugin build does not match the SENTRA relay build",
                    category="compatibility",
                    retryable=True,
                    details={
                        "worker": plugin_stale.get("worker"),
                        "identity": plugin_stale.get("plugin_identity"),
                    },
                )
            if wrong_place is not None:
                raise SentraSemanticError(
                    "SESSION_WRONG_PLACE",
                    "principal Edge controller is on the wrong target",
                    category="readiness",
                    retryable=True,
                    details={"worker": wrong_place.get("worker"), "url": wrong_place.get("url")},
                )
            states = {item["worker"]: item["worker_state"] for item in inventory}
            detail = (
                f"; bootstrap_error={str(bootstrap_error)[:300]}"
                if bootstrap_error is not None
                else ""
            )
            raise SentraSemanticError(
                "CAPABILITY_MISSING",
                "principal Edge bridge is required for chatgpt.com but is not ready",
                category="readiness",
                retryable=True,
                details={
                    "required": "principal-edge-controller",
                    "worker_states": states,
                    "bootstrap_error": str(bootstrap_error)[:300]
                    if bootstrap_error is not None else None,
                    "fallback_policy": "fail_closed",
                },
            )
        elif backend == "edge":
            raise ValueError("Edge backend is restricted to https://chatgpt.com; use Playwright for other sites")

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

        session_id = "playwright:" + str(uuid.uuid4())
        session_kwargs: dict[str, Any] = {
            "role": f"mcp-{session_id[-8:]}",
            "headless": headless,
            "cdp_url": cdp_url,
            "target_url": "about:blank",
            "storage_state_path": None,
        }
        if allow_invasive_fallback:
            session_kwargs["allow_invasive_fallback"] = True
        session = self.session_factory(**session_kwargs)
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
        self.audit.emit(
            "browser.open",
            "ok",
            {"session_id": session_id, "owner": owner, "url": session.page.url, "backend": "playwright"},
        )
        return {
            "session_id": session_id,
            "owner": owner,
            "url": session.page.url,
            "backend": "playwright",
        }

    async def tabs(self, owner: str) -> dict[str, Any]:
        result: list[dict[str, Any]] = []
        for session_id, item in list(self.sessions.items()):
            if item["owner"] != owner:
                continue
            session = item["session"]
            result.append({
                "session_id": session_id,
                "backend": "playwright",
                "url": session.page.url if session.page and not session.page.is_closed() else "",
                "live": session.is_live,
                "reserved": True,
                "created": item["created"],
            })

        edge_health = await self._edge_health()
        inventory = await self._edge_worker_inventory()
        by_worker = {item["worker"]: (sid, item) for sid, item in self.edge_sessions.items()}
        for worker_info in inventory:
            worker = worker_info["worker"]
            sid_item = by_worker.get(worker)
            reserved_by_caller = bool(sid_item and sid_item[1]["owner"] == owner)
            result.append({
                "session_id": sid_item[0] if reserved_by_caller else "edge:" + worker,
                "backend": "edge",
                "worker": worker,
                "url": worker_info.get("url"),
                "live": worker_info["worker_state"] in {"CONNECTED", "READY"},
                "worker_state": worker_info["worker_state"],
                "usable": worker_info["usable"],
                "reserved": sid_item is not None,
                "reserved_by_caller": reserved_by_caller,
                "capabilities": ["navigate", "extract", "click", "type", "screenshot"],
                "status": worker_info.get("status") or {},
                **({"error": worker_info["error"]} if worker_info.get("error") else {}),
            })
        pool = edge_health.get("pool") if isinstance(edge_health, dict) else {}
        if not isinstance(pool, dict):
            pool = {}
        workers_online = [
            str(worker)
            for worker in edge_health.get("workers_online", [])
            if isinstance(worker, str) and worker.startswith("TAB-")
        ] if isinstance(edge_health, dict) else []
        if edge_health.get("ok") is False:
            bridge_state = "UNHEALTHY"
        elif workers_online:
            bridge_state = "CONNECTED"
        elif pool.get("active"):
            bridge_state = "IDLE"
        else:
            bridge_state = "DISCONNECTED"
        return {
            "tabs": result,
            "items": result,
            "page": {
                "offset": 0,
                "limit": len(result),
                "returned": len(result),
                "total": len(result),
                "next_offset": None,
            },
            "edge_bridge": {
                "state": bridge_state,
                "lazy_controller": True,
                "controller_tabs": len(workers_online),
                "max_controller_tabs": 1,
                "pool_active": bool(pool.get("active")),
                "workers_online": workers_online,
                **(
                    {"error": edge_health.get("error")}
                    if edge_health.get("error")
                    else {}
                ),
            },
        }

    async def navigate(self, session_id: str, owner: str, url: str) -> dict[str, Any]:
        await self._validate_url(url)
        if session_id.startswith("edge:"):
            item = self._owned_edge(session_id, owner)
            if not self._is_chatgpt_url(url):
                raise ValueError("Edge backend is restricted to https://chatgpt.com")
            result = await self._edge_action(item["worker"], "navigate", {"url": url})
            self.audit.emit("browser.navigate", "ok", {"session_id": session_id, "owner": owner, "url": result.get("url", url), "backend": "edge"})
            return {"session_id": session_id, "backend": "edge", **result}

        item = self._owned_playwright(session_id, owner)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.audit.emit("browser.navigate", "ok", {"session_id": session_id, "owner": owner, "url": page.url, "backend": "playwright"})
        return {"session_id": session_id, "backend": "playwright", "url": page.url}

    async def extract(self, session_id: str, owner: str, selector: str = "body", max_chars: int = 200000) -> dict[str, Any]:
        selector = self._validate_selector(selector)
        if not 1 <= max_chars <= 1_000_000:
            raise ValueError("max_chars must be between 1 and 1000000")
        if session_id.startswith("edge:"):
            item = self._owned_edge(session_id, owner)
            result = await self._edge_action(
                item["worker"],
                "extract",
                {"selector": selector, "max_chars": max_chars},
            )
            return {"backend": "edge", **result}

        item = self._owned_playwright(session_id, owner)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        text = await page.locator(selector).first.inner_text(timeout=30000)
        truncated = len(text) > max_chars
        return {"backend": "playwright", "text": text[:max_chars], "truncated": truncated, "url": page.url}

    def _write_screenshot_bytes(
        self,
        session_id: str,
        payload: bytes,
        suffix: str,
        mime_type: str,
        url: str | None,
        *,
        include_base64: bool,
        full_page: bool,
        backend: str,
    ) -> dict[str, Any]:
        if len(payload) > self.config.max_read_bytes:
            raise ValueError("screenshot exceeds configured read limit")
        self.screenshot_root.mkdir(parents=True, exist_ok=True)
        safe_id = session_id.replace(":", "-").replace("/", "-")
        target = self.screenshot_root / f"{safe_id}-{int(time.time()*1000)}{suffix}"
        target.write_bytes(payload)
        result: dict[str, Any] = {
            "path": str(target),
            "resource_uri": f"sentra://screenshot/{target.name}",
            "bytes": len(payload),
            "mime_type": mime_type,
            "url": url,
            "full_page": full_page,
            "backend": backend,
        }
        if include_base64:
            result["image_base64"] = base64.b64encode(payload).decode("ascii")
        return result

    async def screenshot(
        self,
        session_id: str,
        owner: str,
        *,
        full_page: bool = True,
        include_base64: bool = False,
    ) -> dict[str, Any]:
        if session_id.startswith("edge:"):
            item = self._owned_edge(session_id, owner)
            if full_page:
                raise ValueError(
                    "principal Edge supports viewport screenshots only; pass full_page=false"
                )
            result = await self._edge_action(
                item["worker"],
                "screenshot",
                {"full_page": False},
                timeout_s=30,
            )
            encoded = result.get("image_base64")
            if not isinstance(encoded, str) or not encoded:
                raise RuntimeError("principal Edge screenshot returned no image bytes")
            try:
                payload = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise RuntimeError("principal Edge screenshot returned invalid base64") from exc
            mime_type = str(result.get("mime_type") or "image/jpeg")
            suffixes = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
            }
            suffix = suffixes.get(mime_type)
            if suffix is None:
                raise RuntimeError("principal Edge screenshot returned unsupported image type")
            saved = self._write_screenshot_bytes(
                session_id,
                payload,
                suffix,
                mime_type,
                str(result.get("url") or "https://chatgpt.com/"),
                include_base64=include_base64,
                full_page=False,
                backend="edge",
            )
            saved["session_id"] = session_id
            self.audit.emit(
                "browser.screenshot",
                "ok",
                {
                    "session_id": session_id,
                    "owner": owner,
                    "bytes": len(payload),
                    "backend": "edge",
                    "full_page": False,
                },
            )
            return saved

        item = self._owned_playwright(session_id, owner)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        payload = await page.screenshot(full_page=bool(full_page))
        saved = self._write_screenshot_bytes(
            session_id,
            payload,
            ".png",
            "image/png",
            page.url,
            include_base64=include_base64,
            full_page=bool(full_page),
            backend="playwright",
        )
        saved["session_id"] = session_id
        self.audit.emit("browser.screenshot", "ok", {"session_id": session_id, "owner": owner, "bytes": len(payload), "backend": "playwright"})
        return saved

    async def click(self, session_id: str, owner: str, selector: str) -> dict[str, Any]:
        selector = self._validate_selector(selector)
        if session_id.startswith("edge:"):
            item = self._owned_edge(session_id, owner)
            result = await self._edge_action(item["worker"], "click", {"selector": selector})
            self.audit.emit("browser.click", "ok", {"session_id": session_id, "owner": owner, "selector": selector, "backend": "edge"})
            return {"session_id": session_id, "backend": "edge", **result}

        item = self._owned_playwright(session_id, owner)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        await page.locator(selector).first.click(timeout=30000)
        self.audit.emit("browser.click", "ok", {"session_id": session_id, "owner": owner, "selector": selector, "backend": "playwright"})
        return {"session_id": session_id, "backend": "playwright", "url": page.url}

    async def type_text(
        self,
        session_id: str,
        owner: str,
        selector: str,
        text: str,
        *,
        clear: bool = False,
    ) -> dict[str, Any]:
        selector = self._validate_selector(selector)
        if len(text.encode("utf-8")) > self.config.max_write_bytes:
            raise ValueError("browser input exceeds write limit")
        if session_id.startswith("edge:"):
            item = self._owned_edge(session_id, owner)
            result = await self._edge_action(
                item["worker"],
                "type",
                {"selector": selector, "text": text, "clear": bool(clear)},
            )
            self.audit.emit("browser.type", "ok", {"session_id": session_id, "owner": owner, "bytes": len(text.encode("utf-8")), "backend": "edge"})
            return {"session_id": session_id, "backend": "edge", **result}

        item = self._owned_playwright(session_id, owner)
        page = item["session"].page
        if page is None:
            raise RuntimeError("browser page unavailable")
        locator = page.locator(selector).first
        if clear:
            await locator.fill(text, timeout=30000)
        else:
            await locator.type(text, timeout=30000)
        self.audit.emit("browser.type", "ok", {"session_id": session_id, "owner": owner, "bytes": len(text.encode("utf-8")), "backend": "playwright"})
        return {"session_id": session_id, "backend": "playwright", "url": page.url}

    async def close(self, session_id: str, owner: str) -> dict[str, Any]:
        if session_id.startswith("edge:"):
            item = self._owned_edge(session_id, owner)
            # A principal-Edge session owns only a controller reference, never
            # the user's tab. Close therefore means explicit release + restore.
            await self._edge_action(item["worker"], "close", {}, timeout_s=20)
            self.edge_sessions.pop(session_id, None)
            self.audit.emit("browser.close", "ok", {"session_id": session_id, "owner": owner, "backend": "edge"})
            return {"session_id": session_id, "backend": "edge", "closed": True, "tab_preserved": True}

        item = self._owned_playwright(session_id, owner)
        await item["session"].close()
        self.sessions.pop(session_id, None)
        self.audit.emit("browser.close", "ok", {"session_id": session_id, "owner": owner, "backend": "playwright"})
        return {"session_id": session_id, "backend": "playwright", "closed": True}

    def read_screenshot(self, name: str) -> bytes:
        if not name or Path(name).name != name or not name.lower().endswith((".png", ".jpg", ".jpeg")):
            raise FileNotFoundError("invalid screenshot resource")
        target = self.screenshot_root / name
        if not target.is_file():
            raise FileNotFoundError("screenshot not found")
        if target.stat().st_size > self.config.max_read_bytes:
            raise ValueError("screenshot exceeds configured read limit")
        return target.read_bytes()

    async def shutdown(self) -> None:
        for session_id, item in list(self.sessions.items()):
            try:
                await item["session"].close()
            except Exception:
                pass
            self.sessions.pop(session_id, None)

        # Best-effort explicit release of every principal-Edge controller.
        # Shutdown must not leave a user tab adopted until the failsafe expires.
        for session_id, item in list(self.edge_sessions.items()):
            try:
                await self._edge_action(item["worker"], "close", {}, timeout_s=20)
            except Exception:
                pass
            self.edge_sessions.pop(session_id, None)
