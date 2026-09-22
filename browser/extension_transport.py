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


def _post(url: str, payload: Dict[str, Any], timeout: float = 15.0, token: str = "") -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: float = 30.0, token: str = "") -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
            pool = h.get("pool") if isinstance(h.get("pool"), dict) else {}
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

    async def submit_chat(self, task_id: str, prompt: str, timeout_s: int = 180,
                          new_chat: bool = True, conversation_url: str | None = None,
                          images: Optional[list] = None) -> Dict[str, Any]:
        """Submete e espera o resultado. Levanta TimeoutError se estourar.
        images: data URLs (validadas pelo protocolo); vão no corpo do job."""
        if not self.token:
            raise RuntimeError("relay pairing required: start python main.py --relay and pair the extension")
        deadline = time.monotonic() + timeout_s
        await self._wait_first_worker(min(self.FIRST_WORKER_GRACE_S, float(timeout_s)))
        body: Dict[str, Any] = {"task_id": task_id, "prompt": prompt, "timeout_s": timeout_s,
                                "new_chat": new_chat, "conversation_url": conversation_url}
        if images:
            body["images"] = images
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

    async def delete_chat(self, conversation_url_or_id: str, timeout_s: int = 30) -> Dict[str, Any]:
        """Solicita a exclusão do chat no provedor remoto para não poluir o histórico."""
        if not self.token:
            raise RuntimeError("relay pairing required: start python main.py --relay and pair the extension")
        task_id = "del-" + uuid.uuid4().hex[:8]
        conv_url = conversation_url_or_id if conversation_url_or_id.startswith("http") else f"https://chatgpt.com/c/{conversation_url_or_id}"
        body: Dict[str, Any] = {
            "task_id": task_id,
            "prompt": conversation_url_or_id,
            "timeout_s": timeout_s,
            "new_chat": False,
            "conversation_url": conv_url,
            "kind": "DELETE_CHAT",
        }
        deadline = time.monotonic() + timeout_s
        sub = await asyncio.to_thread(_post, f"{self.base}/jobs/submit", body, 10.0, self.token)
        job_id = sub["job_id"]
        try:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"[TIMEOUT] delete job {job_id} exceeded {timeout_s}s")
                chunk = min(5.0, max(.1, deadline - time.monotonic()))
                res = await asyncio.to_thread(_get, f"{self.base}/jobs/wait?job_id={job_id}&timeout_s={chunk}",
                                              chunk + 2, self.token)
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

