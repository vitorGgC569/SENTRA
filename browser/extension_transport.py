"""Cliente do relay local para o BrowserExtensionProvider (stdlib, sem deps novas).

submit -> long-poll /jobs/wait em fatias de 60s até timeout total.
CancelledError sempre propaga (RF-017); timeout vira TimeoutError (RF-016).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from sentra_core.conversation import ConversationIdentity


def _post(url: str, payload: Dict[str, Any], timeout: float = 15.0, token: str = "") -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: float = 30.0, token: str = "") -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class ExtensionDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        delivery_state: str,
        retry_safe: bool,
        phase: str = "",
        job_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.delivery_state = delivery_state
        self.retry_safe = retry_safe
        self.phase = phase
        self.job_id = job_id


class ExtensionTransport:
    FIRST_WORKER_GRACE_S = 15.0

    def __init__(self, relay_base: str = "http://127.0.0.1:8765", token: str | None = None):
        from urllib.parse import urlparse
        parsed = urlparse(relay_base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("relay must use loopback HTTP")
        self.base = relay_base.rstrip("/")
        configured_token_file = os.environ.get("SENTRA_EDGE_RELAY_TOKEN_PATH", "").strip()
        token_file = (
            Path(configured_token_file).expanduser().resolve()
            if configured_token_file
            else Path(__file__).resolve().parents[1] / ".oma" / "relay-token"
        )
        self.token = token if token is not None else os.environ.get("OMA_RELAY_TOKEN", "")
        if not self.token and token_file.is_file():
            self.token = token_file.read_text(encoding="utf-8").strip()

    async def health(self) -> Dict[str, Any]:
        return await asyncio.to_thread(_get, f"{self.base}/health", 10.0, self.token)

    async def _wait_first_worker(self, budget_s: float) -> None:
        """Falha rápido quando não há extensão nem pool líder conectado.

        No controller lazy, logo após restart pode haver pool líder ativo antes
        do primeiro TAB-* existir. Esse pool é prova suficiente de que a extensão
        está conectada e pode adotar uma aba assim que o job entrar na fila.
        """
        start = asyncio.get_running_loop().time()
        while True:
            try:
                h = await self.health()
            except Exception:
                return  # relay com problema: deixa o fluxo normal classificar
            raw_pool = h.get("pool")
            pool: Dict[str, Any] = raw_pool if isinstance(raw_pool, dict) else {}
            if (
                h.get("workers_ever_seen", 1) > 0
                or h.get("workers_online")
                or (pool.get("active") is True and bool(pool.get("owner")))
            ):
                return
            if asyncio.get_running_loop().time() - start >= budget_s:
                raise RuntimeError(
                    "no extension connected: nenhum worker (tab real) fez poll "
                    "no relay. Suba a extensão no Edge (edge_extension/README.md).")
            await asyncio.sleep(1.0)

    async def probe_quota(self, timeout_s: int = 60) -> Dict[str, Any]:
        """Sonda de quota: lê o DOM via worker, nunca envia mensagem (custo zero).
        Retorna {send_available, cap_banner, url, ...} ou levanta TimeoutError."""
        task_id = "probe-" + uuid.uuid4().hex
        sub = await asyncio.to_thread(
            _post, f"{self.base}/jobs/submit",
            {"task_id": task_id, "prompt": "", "timeout_s": timeout_s,
             "new_chat": False, "kind": "STATUS_PROBE"}, 10.0, self.token)
        job_id = sub["job_id"]
        deadline = time.monotonic() + timeout_s
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("quota probe timed out")
                chunk = min(5.0, max(.1, deadline - time.monotonic()))
                res = await asyncio.to_thread(_get, f"{self.base}/jobs/wait?job_id={job_id}&timeout_s={chunk}",
                                              chunk + 2, self.token)
                if res.get("pending"):
                    continue
                if res.get("job_id") != job_id or res.get("task_id") != task_id:
                    raise RuntimeError("probe response correlation mismatch")
                await asyncio.to_thread(_post, f"{self.base}/jobs/ack", {"job_id": job_id}, 5, self.token)
                if res.get("status") != "COMPLETED":
                    raise RuntimeError("probe failed: " + str(res.get("error")))
                data = json.loads(res.get("result", "{}"))
                if not isinstance(data, dict):
                    raise ValueError("probe result must be an object")
                from .outcomes import classify_probe
                data["availability"] = classify_probe(data)
                return data
        except (asyncio.CancelledError, TimeoutError, RuntimeError, ValueError):
            try:
                await asyncio.to_thread(_post, f"{self.base}/jobs/cancel", {"job_id": job_id}, 2, self.token)
            except Exception:
                pass
            raise

    async def submit_chat(
        self,
        task_id: str,
        prompt: str,
        timeout_s: int = 180,
        new_chat: bool = True,
        conversation_url: str | None = None,
        images: Optional[list] = None,
        *,
        project_id: str | None = None,
        project_url: str | None = None,
        chat_title: str | None = None,
        provider: str = "chatgpt",
        model: str | None = None,
    ) -> Dict[str, Any]:
        """Submete e espera o resultado. Levanta TimeoutError se estourar.
        images: data URLs (validadas pelo protocolo); vão no corpo do job."""
        if not self.token:
            raise RuntimeError("relay pairing required: start python main.py --relay and pair the extension")
        deadline = time.monotonic() + timeout_s
        await self._wait_first_worker(min(self.FIRST_WORKER_GRACE_S, float(timeout_s)))
        body: Dict[str, Any] = {
            "task_id": task_id,
            "prompt": prompt,
            "timeout_s": timeout_s,
            "new_chat": new_chat,
            "conversation_url": conversation_url,
            "provider": provider,
        }
        if model:
            body["model"] = model
        if images:
            body["images"] = images
        if project_id:
            body["project_id"] = project_id
        if project_url:
            body["project_url"] = project_url
        if chat_title:
            body["chat_title"] = chat_title
        sub = await asyncio.to_thread(
            _post, f"{self.base}/jobs/submit", body, 10.0, self.token)
        job_id = sub["job_id"]
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"[TIMEOUT] extension job {job_id} task={task_id} exceeded {timeout_s}s")
                chunk = min(5.0, max(.1, deadline - time.monotonic()))
                res = await asyncio.to_thread(_get, f"{self.base}/jobs/wait?job_id={job_id}&timeout_s={chunk}",
                                             chunk+2, self.token)
                if res.get("pending"):
                    continue
                if res.get("job_id") != job_id or res.get("task_id") != task_id:
                    raise RuntimeError("relay response correlation mismatch")
                await asyncio.to_thread(_post, f"{self.base}/jobs/ack", {"job_id": job_id}, 5, self.token)
                return res
        except (asyncio.CancelledError, TimeoutError):
            try:
                await asyncio.to_thread(_post, f"{self.base}/jobs/cancel", {"job_id": job_id}, 2, self.token)
            except Exception:
                pass
            raise



    async def _phase_job(
        self,
        body: Dict[str, Any],
        *,
        timeout_s: int,
        on_submitted=None,
        auto_ack: bool = True,
    ) -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("relay pairing required: start python main.py --relay and pair the extension")
        await self._wait_first_worker(min(self.FIRST_WORKER_GRACE_S, float(timeout_s)))
        submitted = await asyncio.to_thread(
            _post, f"{self.base}/jobs/submit", body, 10.0, self.token
        )
        job_id = str(submitted["job_id"])
        if on_submitted is not None:
            callback = on_submitted(job_id)
            if asyncio.iscoroutine(callback):
                await callback
        deadline = time.monotonic() + timeout_s
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"[TIMEOUT] extension phase job {job_id} exceeded {timeout_s}s"
                    )
                chunk = min(5.0, max(.1, deadline - time.monotonic()))
                result = await asyncio.to_thread(
                    _get,
                    f"{self.base}/jobs/wait?job_id={job_id}&timeout_s={chunk}",
                    chunk + 2,
                    self.token,
                )
                if result.get("pending"):
                    continue
                if result.get("job_id") != job_id or result.get("task_id") != body["task_id"]:
                    raise RuntimeError("relay response correlation mismatch")
                if auto_ack:
                    await asyncio.to_thread(
                        _post, f"{self.base}/jobs/ack", {"job_id": job_id}, 5, self.token
                    )
                result["job_id"] = job_id
                result["_needs_ack"] = not auto_ack
                return result
        except (asyncio.CancelledError, TimeoutError):
            try:
                await asyncio.to_thread(
                    _post, f"{self.base}/jobs/cancel", {"job_id": job_id}, 2, self.token
                )
            except Exception:
                pass
            raise

    async def send_chat(
        self,
        *,
        task_id: str,
        prompt: str,
        timeout_s: int = 60,
        conversation_url: str | None = None,
        provider: str = "chatgpt",
        model: str | None = None,
        chat_title: str | None = None,
        on_submitted=None,
    ) -> Dict[str, Any]:
        """Send one turn and release the physical controller before generation completes."""
        new_chat = not bool(conversation_url)
        body: Dict[str, Any] = {
            "task_id": task_id,
            "prompt": prompt,
            "timeout_s": max(5, min(int(timeout_s), 900)),
            "new_chat": new_chat,
            "conversation_url": conversation_url,
            "kind": "CHAT_SEND",
            "provider": provider,
        }
        if model:
            body["model"] = model
        if chat_title and provider == "chatgpt":
            body["chat_title"] = chat_title
        result = await self._phase_job(
            body,
            timeout_s=body["timeout_s"],
            on_submitted=on_submitted,
            auto_ack=False,
        )
        if result.get("status") != "COMPLETED":
            may_have_sent = bool(result.get("_may_have_sent"))
            raise ExtensionDeliveryError(
                str(result.get("error") or "CHAT_SEND failed"),
                delivery_state="UNCERTAIN" if may_have_sent else "NOT_SENT",
                retry_safe=not may_have_sent,
                phase=str(result.get("_delivery_phase") or ""),
                job_id=str(result.get("job_id") or "") or None,
            )
        raw = result.get("result")
        decoded: Dict[str, Any] = {}
        if isinstance(raw, str) and raw:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {}
            if isinstance(value, dict):
                decoded = value
        return {
            **decoded,
            "job_id": result.get("job_id"),
            "worker": result.get("worker"),
            "conversation_url": result.get("conversation_url") or decoded.get("conversation_url"),
            "conversation_id": result.get("conversation_id") or decoded.get("conversation_id"),
            "provider": provider,
            "model": model,
        }

    async def inspect_job(self, job_id: str, *, timeout_s: float = 0.1) -> Dict[str, Any]:
        if not self.token:
            raise RuntimeError("relay pairing required")
        return await asyncio.to_thread(
            _get,
            f"{self.base}/jobs/wait?job_id={job_id}&timeout_s={max(0.0, min(float(timeout_s), 25.0))}",
            max(2.0, min(float(timeout_s), 25.0) + 2.0),
            self.token,
        )

    async def ack_job(self, job_id: str) -> None:
        if not self.token:
            raise RuntimeError("relay pairing required")
        await asyncio.to_thread(
            _post, f"{self.base}/jobs/ack", {"job_id": job_id}, 5, self.token
        )

    async def collect_chat(
        self,
        *,
        task_id: str,
        conversation_url: str,
        timeout_s: int = 180,
        provider: str,
    ) -> Dict[str, Any]:
        """Collect a previously-sent server-side generation using read-only peeks."""
        deadline = time.monotonic() + max(5, int(timeout_s))
        last: Dict[str, Any] = {}
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            remaining = deadline - time.monotonic()
            body: Dict[str, Any] = {
                "task_id": f"{task_id}-peek-{attempt}",
                "prompt": "",
                "timeout_s": max(5, min(15, int(max(5, remaining)))),
                "new_chat": False,
                "conversation_url": conversation_url,
                "kind": "CHAT_PEEK",
                "provider": provider,
            }
            peek_timeout_s = int(body["timeout_s"])
            result = await self._phase_job(body, timeout_s=peek_timeout_s)
            if result.get("status") != "COMPLETED":
                raise RuntimeError(str(result.get("error") or "CHAT_PEEK failed"))
            raw = result.get("result")
            decoded: Dict[str, Any] = {}
            if isinstance(raw, str) and raw:
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = {}
                if isinstance(value, dict):
                    decoded = value
            last = {
                **decoded,
                "worker": result.get("worker"),
                "conversation_url": result.get("conversation_url") or conversation_url,
                "conversation_id": result.get("conversation_id") or decoded.get("conversation_id"),
                "provider": provider,
            }
            if last.get("ready") and last.get("text"):
                return last
            await asyncio.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
        raise TimeoutError(
            "CHAT_COLLECT timed out after bounded peeks "
            f"(additional_checks={bool(last.get('additional_checks'))})"
        )

    async def delete_chat(
        self,
        conversation_url_or_id: str,
        timeout_s: int = 30,
        *,
        provider: str | None = None,
    ) -> Dict[str, Any]:
        """Delete a managed conversation only when the provider has a verified primitive.

        Gemini Web currently has no verified delete primitive in SENTRA.  It is
        therefore retained explicitly instead of pretending cleanup succeeded.
        """
        if not self.token:
            raise RuntimeError(
                "relay pairing required: start python main.py --relay and pair the extension"
            )

        raw = str(conversation_url_or_id or "").strip()
        identity = None
        if raw.startswith("http"):
            identity = ConversationIdentity.parse(raw)
            if provider is not None and identity.provider != str(provider).strip().lower():
                raise ValueError("cleanup provider does not match conversation URL")
        else:
            resolved = str(provider or "chatgpt").strip().lower()
            identity = ConversationIdentity.from_parts(resolved, raw)

        if identity.provider == "gemini":
            return {
                "status": "UNSUPPORTED",
                "provider": "gemini",
                "conversation_id": identity.conversation_id,
                "conversation_url": identity.canonical_url,
                "retained": True,
                "deleted": False,
                "reason": "verified Gemini Web delete primitive is not available",
            }

        task_id = "del-" + uuid.uuid4().hex[:8]
        body: Dict[str, Any] = {
            "task_id": task_id,
            "prompt": identity.conversation_id,
            "timeout_s": timeout_s,
            "new_chat": False,
            "conversation_url": identity.canonical_url,
            "kind": "DELETE_CHAT",
            "provider": identity.provider,
        }
        deadline = time.monotonic() + timeout_s
        sub = await asyncio.to_thread(
            _post, f"{self.base}/jobs/submit", body, 10.0, self.token
        )
        job_id = sub["job_id"]
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"[TIMEOUT] delete job {job_id} exceeded {timeout_s}s"
                    )
                chunk = min(5.0, max(.1, deadline - time.monotonic()))
                res = await asyncio.to_thread(
                    _get,
                    f"{self.base}/jobs/wait?job_id={job_id}&timeout_s={chunk}",
                    chunk + 2,
                    self.token,
                )
                if res.get("pending"):
                    continue
                if res.get("job_id") != job_id or res.get("task_id") != task_id:
                    raise RuntimeError("relay response correlation mismatch")
                await asyncio.to_thread(
                    _post, f"{self.base}/jobs/ack", {"job_id": job_id}, 5, self.token
                )
                return res
        except (asyncio.CancelledError, TimeoutError):
            try:
                await asyncio.to_thread(
                    _post, f"{self.base}/jobs/cancel", {"job_id": job_id}, 2, self.token
                )
            except Exception:
                pass
            raise

