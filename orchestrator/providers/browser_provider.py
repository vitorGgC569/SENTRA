from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import Any, Dict, List, Optional

from .base import AgentRequest, AgentResponse
from ..models import TokenUsage
from browser.outcomes import classify_failure
from browser.pool import BrowserPool
from browser.session import BrowserSession


DEFAULT_BOT_PROFILE_DIR = "browser_profiles/edge-bot"
DEFAULT_LAUNCH_FLAGS: List[str] = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]

_URL_RE = re.compile(r"https://chatgpt\.com/c/([A-Za-z0-9-]{1,128})")


def _classify_browser_error(exc: BaseException) -> str:
    """Map exceptions to the OMA failure taxonomy (Section 73)."""
    if isinstance(exc, asyncio.CancelledError):
        return "CANCELLED"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "TIMEOUT"
    msg = str(exc).lower()
    if "vazia" in msg or "incompleta" in msg or "expirada" in msg:
        return "MODEL_ERROR"
    if "closed" in msg or "disconnected" in msg or "sessao" in msg:
        return "NETWORK_ERROR"
    if "ausente" in msg or "dom" in msg or "selector" in msg or "login" in msg:
        return "DEPENDENCY_ERROR"
    return "TOOL_ERROR"


def _synthetic_conversation_url(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"https://chatgpt.com/c/browser-{digest}"


class BrowserProvider:
    """
    Adapter that routes requests through chatgpt.com via persistent
    Microsoft Edge (Playwright channel="msedge" / CDP). Responses are
    correlated with task_id for auditability.

    Persistent delivery contract (same as extension_provider.py, consumed by
    FixedConversationRouter): success carries
    ``{conversation_url, conversation_id, delivery_state: CONFIRMED}``;
    failures carry ``delivery_state`` NOT_SENT / UNCERTAIN / BLOCKED via
    ``browser.outcomes.classify_failure`` so uncertain sends are never
    replayed by fallback.
    """

    MAX_CONVERSATIONS = 1000
    persistent_conversations = True

    def __init__(
        self,
        pool: Optional[BrowserPool] = None,
        session: Optional[BrowserSession] = None,
        model_name: str = "browser-chatgpt-edge",
        bot_profile_dir: str = DEFAULT_BOT_PROFILE_DIR,
        launch_flags: Optional[List[str]] = None,
        bot_headless: bool = False,
    ):
        self.pool = pool
        self.session = session
        self.model_name = model_name
        self.bot_profile_dir = bot_profile_dir
        self.launch_flags = list(launch_flags) if launch_flags is not None else list(DEFAULT_LAUNCH_FLAGS)
        self.bot_headless = bot_headless
        # Auditoria: conversation_key (run:role) -> {conversation_id, conversation_url, worker}
        self.conversations: Dict[str, Dict[str, Any]] = {}
        # Sessões adotadas de runs anteriores do MESMO run-id (claims em disco).
        self.adopted_urls: set = set()
        self._pool_ready = False
        self._pool_lock = asyncio.Lock()

    async def _ensure_pool_ready(self) -> None:
        """Inicializa o pool na primeira chamada (browser abre aqui, não no build)."""
        if self._pool_ready or self.pool is None:
            return
        async with self._pool_lock:
            if self._pool_ready or self.pool is None:
                return
            initializer = getattr(self.pool, "initialize_all", None)
            if initializer is None:
                # Pool gerenciado externamente (ex.: doubles de teste):
                # nada a inicializar aqui.
                self._pool_ready = True
                return
            await initializer()
            self._pool_ready = True

    def adopt_conversations(self, urls) -> int:
        """Adota conversas criadas por runs anteriores (mesmo run-id, disco local)."""
        n = 0
        for u in urls or []:
            if isinstance(u, str) and _URL_RE.fullmatch(u):
                if u not in self.adopted_urls:
                    self.adopted_urls.add(u)
                    n += 1
        return n

    def _remember(self, task_id: str, info: Dict[str, Any]) -> None:
        self.conversations[task_id] = info
        while len(self.conversations) > self.MAX_CONVERSATIONS:
            self.conversations.pop(next(iter(self.conversations)))

    def _live_conversation_url(self, role: str) -> Optional[str]:
        """URL remota real da página live, quando disponível e bem formada."""
        try:
            if self.session is not None:
                page = getattr(self.session, "page", None)
                url = getattr(page, "url", None)
                if isinstance(url, str) and _URL_RE.fullmatch(url):
                    return url
            if self.pool is not None:
                sessions = getattr(self.pool, "sessions", {}) or {}
                sess = sessions.get(role) or (next(iter(sessions.values())) if sessions else None)
                page = getattr(sess, "page", None) if sess is not None else None
                url = getattr(page, "url", None) if page is not None else None
                if isinstance(url, str) and _URL_RE.fullmatch(url):
                    return url
        except Exception:
            pass
        return None

    async def _heal_page(self) -> bool:
        """Recarrega a(s) página(s) do bot após congelamento (best-effort).

        Nunca levanta: o erro original segue seu fluxo normal. Recarregar não
        duplica nada (o histórico vive no servidor) e devolve DOM fresco
        para as próximas chamadas da run.
        """
        healed = False
        try:
            sessions = []
            if self.session is not None:
                sessions.append(self.session)
            pool_sessions = getattr(self.pool, "sessions", {}) or {}
            sessions.extend(pool_sessions.values())
            for sess in sessions:
                page = getattr(sess, "page", None)
                if page is None:
                    continue
                try:
                    await asyncio.wait_for(
                        page.reload(wait_until="domcontentloaded"), timeout=45)
                    healed = True
                except Exception:
                    continue
        except Exception:
            pass
        return healed

    async def execute(self, request: AgentRequest) -> AgentResponse:
        start = time.time()
        role = request.role
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
        try:
            if self.pool:
                await self._ensure_pool_ready()
                submit_kwargs = dict(
                    role=role,
                    task={"id": task_id},
                    prompt=prompt,
                    round_number=request.metadata.get("round_number", 0),
                    timeout_seconds=timeout,
                    new_chat=new_chat,
                    conversation_url=None if new_chat else conversation_url,
                )
                try:
                    res = await self.pool.submit(**submit_kwargs)
                except Exception as first_err:
                    # FILL_FAILED prova que nada foi enviado (o fill sequer
                    # confirmou): curar a página e retentar UMA vez pelo mesmo
                    # caminho (que re-navega) não duplica. Outro erro segue
                    # o fluxo normal abaixo.
                    if "FILL_FAILED" not in str(first_err):
                        raise
                    await self._heal_page()
                    res = await self.pool.submit(**submit_kwargs)
                content = res.get("raw_response", "")
            elif self.session:
                content = await asyncio.wait_for(
                    self.session.ask(prompt, timeout_seconds=timeout),
                    timeout=timeout + 10,
                )
            else:
                raise RuntimeError("No BrowserPool or BrowserSession provided to BrowserProvider")
        except asyncio.CancelledError:
            # RF-017: never swallow cancellation; let the orchestrator observe it.
            raise
        except (TimeoutError, asyncio.TimeoutError) as e:
            # Cura best-effort antes de devolver: a próxima chamada da run
            # encontra DOM fresco em vez do renderer congelado.
            await self._heal_page()
            return AgentResponse(content="", token_usage=TokenUsage(model=self.model_name),
                                 latency=time.time() - start, success=False,
                                 error=f"[TIMEOUT] task={task_id} {e}", model=self.model_name,
                                 metadata=classify_failure(e))
        except Exception as e:
            code = _classify_browser_error(e)
            return AgentResponse(content="", token_usage=TokenUsage(model=self.model_name),
                                 latency=time.time() - start, success=False,
                                 error=f"[{code}] task={task_id} {e}", model=self.model_name,
                                 metadata=classify_failure(f"[{code}] {e}"))

        if not content:
            return AgentResponse(content="", token_usage=TokenUsage(model=self.model_name),
                                 latency=time.time() - start, success=False,
                                 error=f"[MODEL_ERROR] task={task_id} empty response from chatgpt.com (resposta incompleta)",
                                 model=self.model_name,
                                 metadata=classify_failure("[MODEL_ERROR] resposta vazia"))

        live_url = self._live_conversation_url(role)
        if new_chat:
            url = live_url or _synthetic_conversation_url(key)
        else:
            if live_url is not None:
                if live_url != conversation_url:
                    return AgentResponse(content="", success=False, model=self.model_name,
                                         error="[CONVERSATION_MISMATCH] result came from another conversation",
                                         metadata={"delivery_state": "UNCERTAIN", "retry_safe": False})
                url = live_url
            else:
                if not isinstance(conversation_url, str) or not _URL_RE.fullmatch(conversation_url):
                    return AgentResponse(content="", success=False, model=self.model_name,
                                         error="[CONVERSATION_MISMATCH] missing or inconsistent remote conversation identity",
                                         metadata={"delivery_state": "UNCERTAIN", "retry_safe": False})
                url = conversation_url
        match = _URL_RE.fullmatch(url)
        if not match:
            return AgentResponse(content="", success=False, model=self.model_name,
                                 error="[CONVERSATION_MISMATCH] missing or inconsistent remote conversation identity",
                                 metadata={"delivery_state": "UNCERTAIN", "retry_safe": False})
        info = {
            "conversation_id": match.group(1),
            "conversation_url": url,
            "worker": role,
            "delivery_state": "CONFIRMED",
        }
        self._remember(key, info)
        return AgentResponse(
            content=content,
            token_usage=TokenUsage(input_tokens=len(prompt) // 4,
                                   output_tokens=len(content) // 4,
                                   model=self.model_name),
            latency=time.time() - start, success=True, model=self.model_name, metadata=info)
