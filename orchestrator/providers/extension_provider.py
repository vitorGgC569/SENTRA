"""BrowserExtensionProvider — AgentProvider sobre Edge real via extensão+relay.

Uso normal/live. Para testes/E2E, use o PlaywrightProvider (BrowserProvider).
Cada execução cria (ou reutiliza) UMA conversa no site e registra a URL remota
para auditoria, sem acoplar o OMA ao provider (IDs desacoplados em projects.py).
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from browser.extension_transport import ExtensionTransport
from browser.outcomes import classify_failure
from native_bridge.protocol import MAX_IMAGES_PER_JOB, MAX_IMAGE_CHARS
from ..models import TokenUsage
from .base import AgentRequest, AgentResponse


def _load_image_attachments(spec: Any) -> Union[List[str], str, None]:
    """File paths (metadata['images']) -> data URLs, or error text, or None.

    Fail-closed: missing/non-PNG/oversize files refuse the whole send with a
    clear error instead of delivering a prompt whose evidence is absent.
    Caps mirror the relay protocol so a job accepted here passes validation.
    """
    if not spec:
        return None
    paths = [spec] if isinstance(spec, (str, Path)) else list(spec)
    if len(paths) > MAX_IMAGES_PER_JOB:
        return (f"[IMAGE_ERROR] at most {MAX_IMAGES_PER_JOB} images per message; "
                "no text was sent")
    urls = []
    for path in paths:
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return f"[IMAGE_ERROR] evidence file not found: {path}; no text was sent"
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return f"[IMAGE_ERROR] evidence must be PNG: {path}; no text was sent"
        url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        if len(url) > MAX_IMAGE_CHARS:
            return (f"[IMAGE_ERROR] evidence exceeds size cap "
                    f"({len(raw)} bytes): {path}; no text was sent")
        urls.append(url)
    return urls


class BrowserExtensionProvider:
    """AgentProvider que fala com tabs reais do Edge via relay local."""

    # Auditoria limitada: dicts sem teto vazam memória em runs longas.
    MAX_CONVERSATIONS = 1000
    persistent_conversations = True

    def __init__(self, relay_base: str = "http://127.0.0.1:8765",
                 model_name: str = "browser-extension", token: str | None = None):
        self.transport = ExtensionTransport(relay_base, token=token)
        self.model_name = model_name
        # Auditoria: task_id -> {conversation_id, conversation_url, worker}
        self.conversations: Dict[str, Dict[str, Any]] = {}
        # Sessões adotadas de runs anteriores do MESMO run-id (claims em disco):
        # permite continuação entre processos sem aceitar URL arbitrária.
        self.adopted_urls: set = set()

    def adopt_conversations(self, urls) -> int:
        """Adota conversas criadas por runs anteriores (mesmo run-id, disco local).
        A checagem exata de URL no resultado continua valendo."""
        import re as _re
        n = 0
        for u in urls or []:
            if isinstance(u, str) and _re.fullmatch(r"https://chatgpt\.com/c/[A-Za-z0-9-]{1,128}", u):
                if u not in self.adopted_urls:
                    self.adopted_urls.add(u)
                    n += 1
        return n

    def _remember(self, task_id: str, info: Dict[str, Any]) -> None:
        self.conversations[task_id] = info
        while len(self.conversations) > self.MAX_CONVERSATIONS:
            self.conversations.pop(next(iter(self.conversations)))

    async def execute(self, request: AgentRequest) -> AgentResponse:
        start = time.time()
        task_id = request.metadata.get("task_id", "t-unknown")
        key = request.metadata.get("conversation_key", task_id)
        new_chat = bool(request.metadata.get("new_chat", True))
        conversation_url = request.metadata.get("conversation_url")
        timeout = max(5, min(int(request.timeout or 180), 900))
        sys_p = (request.system_prompt or "").strip()
        usr_p = (request.user_prompt or "").strip()
        if not new_chat and not request.metadata.get("refresh_system_prompt"):
            prompt = usr_p  # Instructions already live in this exact conversation.
        elif usr_p and (usr_p == sys_p or (sys_p and sys_p in usr_p)):
            prompt = usr_p  # evita duplicação quando system==user ou contido
        else:
            prompt = f"{request.system_prompt}\n\n{request.user_prompt}"
        if len(prompt) > 20000:
            return AgentResponse(content="", success=False, model=self.model_name,
                                 error="[CONTEXT_BUDGET] prompt exceeds 20000 characters; no text was sent",
                                 metadata={"delivery_state": "NOT_SENT", "retry_safe": False})
        if not new_chat:
            prior = self.conversations.get(key)
            owned_here = bool(prior and prior.get("conversation_url") == conversation_url)
            adopted = bool(conversation_url in self.adopted_urls)
            if not (owned_here or adopted):
                return AgentResponse(content="", success=False, model=self.model_name,
                                     error="[CONVERSATION_MISMATCH] continuation is not owned by this session",
                                     metadata={"delivery_state": "NOT_SENT", "retry_safe": False})
        images = _load_image_attachments(request.metadata.get("images"))
        if isinstance(images, str):  # error text, fail closed before any send
            return AgentResponse(content="", success=False, model=self.model_name,
                                 error=images,
                                 metadata={"delivery_state": "NOT_SENT", "retry_safe": False})
        try:
            res = await self.transport.submit_chat(
                task_id=task_id, prompt=prompt, timeout_s=timeout,
                new_chat=new_chat, conversation_url=conversation_url if not new_chat else None,
                images=images or None)
        except asyncio.CancelledError:
            raise  # RF-017: nunca engolir cancelamento
        except (TimeoutError, asyncio.TimeoutError) as e:
            return AgentResponse(content="", token_usage=TokenUsage(model=self.model_name),
                                 latency=time.time() - start, success=False,
                                 error=f"[TIMEOUT] task={task_id} {e}", model=self.model_name,
                                 metadata=classify_failure(e))
        except Exception as e:
            return AgentResponse(content="", token_usage=TokenUsage(model=self.model_name),
                                 latency=time.time() - start, success=False,
                                 error=f"[TOOL_ERROR] task={task_id} {e}", model=self.model_name,
                                 metadata=classify_failure(e))

        if res.get("status") != "COMPLETED":
            return AgentResponse(content="", token_usage=TokenUsage(model=self.model_name),
                                 latency=time.time() - start, success=False,
                                 error=f"[MODEL_ERROR] task={task_id} {res.get('error', 'unknown')}",
                                 model=self.model_name, metadata=classify_failure(res.get('error')))
        if images and int(res.get("images_attached", 0) or 0) < len(images):
            # Texto foi entregue, mas a evidência NÃO anexou (extensão antiga
            # sem paste, ou clipboard bloqueado). Aceitar calado mentiria ao
            # validador, que foi instruído a examinar as imagens. Falha alto;
            # operador recarrega a extensão / verifica o composer.
            return AgentResponse(content="", success=False, model=self.model_name,
                                  error=("[IMAGE_VERSION] evidence failed to attach "
                                         f"({res.get('images_attached', 0)}/{len(images)}); "
                                         "reload edge_extension (>=1.4.0) and reconcile; "
                                         "text may already be delivered"),
                                  metadata={"delivery_state": "UNCERTAIN", "retry_safe": False,
                                            "images_requested": len(images),
                                            "images_attached": res.get("images_attached", 0)})
        content = res.get("result", "") or ""
        info = {
            "conversation_id": res.get("conversation_id"),
            "conversation_url": res.get("conversation_url"),
            "worker": res.get("worker", ""),
            "delivery_state": "CONFIRMED",
            "images_attached": int(res.get("images_attached", 0) or 0),
        }
        match = re.fullmatch(r"https://chatgpt\.com/c/([A-Za-z0-9-]{1,128})", info["conversation_url"] or "")
        if not match or match[1] != info["conversation_id"]:
            return AgentResponse(content="", success=False, model=self.model_name,
                                 error="[CONVERSATION_MISMATCH] missing or inconsistent remote conversation identity",
                                 metadata={"delivery_state": "UNCERTAIN", "retry_safe": False})
        if not new_chat and info["conversation_url"] != conversation_url:
            return AgentResponse(content="", success=False, model=self.model_name,
                                 error="[CONVERSATION_MISMATCH] result came from another conversation",
                                 metadata={"delivery_state": "UNCERTAIN", "retry_safe": False})
        self._remember(key, info)
        return AgentResponse(
            content=content,
            token_usage=TokenUsage(input_tokens=len(prompt) // 4,
                                   output_tokens=len(content) // 4,
                                   model=self.model_name),
            latency=time.time() - start, success=True, model=self.model_name, metadata=info)
