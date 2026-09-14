"""Protocolo OMA <-> Edge Extension via relay local. Schemas validam tudo."""
# PROGRESS CONTRACT (extensao -> relay, 10 linhas):
# 1. POST /jobs/progress {job_id,worker,lease_token,phase} estende lease +120s, teto deadline.
# 2. Fases pre-send seguras: preparing|navigating|settling|ready (prova de nada enviado).
# 3. Fases pos-send incertas: sending|sent|waiting|reading (nunca re-enfileira).
# 4. Worker DEVE POST sending e aguardar 200 ANTES de SEND_MESSAGE (senao seguranca nula).
# 5. Heartbeat /jobs/lease (10s) renova 120s; progresso renova 120s; deadline nunca cresce.
# 6. Expiracao: sem sinal => WORKER_LOST; progresso recente + deadline => DELIVERY_SLOW.
# 7. Orfao seguro volta a QUEUED no maximo 1 vez (requeues visivel); depois FAILED.
# 8. Requeue so se phase segura + may_have_sent=0 + deadline futuro; senao FAILED incerto.
# 9. Poll retorna requeues; FAILED traz erro distinto para retry (seguro) vs reconcile.
# 10. Poll/lease/result/ack/cancel inalterados; progresso e opcional e compativel.
from __future__ import annotations

import time
import uuid
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

OPS_TO_EXTENSION = {"CREATE_CHAT", "SEND_MESSAGE", "WAIT_RESPONSE", "READ_RESPONSE",
                    "GET_CONVERSATION_ID", "GET_CONVERSATION_URL", "STOP_GENERATION",
                    "GET_STATUS", "NEW_CHAT"}
# Job que o OMA submete ao relay (a extensão traduz para ops primitivas).
# STATUS_PROBE só lê o DOM (envio disponível? banner de cap?) — nunca envia
# mensagem, nunca consome quota. É a forma segura de vigiar rate-limit.
JOB_TYPES = {"CHAT_TASK", "STATUS_PROBE"}


# Visual evidence attachments: screenshots travel as data URLs inside the job
# (loopback only). Caps keep every job inside the relay 1 MiB body limit.
MAX_IMAGES_PER_JOB = 2
MAX_IMAGE_CHARS = 400000  # ~300 KiB PNG each
MAX_IMAGES_TOTAL_CHARS = 700000

# Lease resilience: heartbeat renova LEASE_WINDOW_S, progresso renova
# PROGRESS_WINDOW_S, teto = created+timeout. Janela 120s: cobre suspensao MV3
# (~30-60s sem eventos) com folga, sem chegar perto dos deadlines de job
# (300s+); deteccao de morte real continua via progresso vencido.
LEASE_WINDOW_S = 120.0
PROGRESS_WINDOW_S = 120.0
MAX_REQUEUES_DEFAULT = 1
# Fases que provam que nada foi enviado (antes de qualquer SEND_MESSAGE).
PRE_SEND_PHASES = frozenset({"preparing", "navigating", "settling", "ready"})
# Todas as fases validas; tudo fora de PRE_SEND e considerado pos-send/incerto.
PROGRESS_PHASES = frozenset(PRE_SEND_PHASES | {"sending", "sent", "waiting", "reading"})


def _valid_image_url(url: Any) -> bool:
    return (isinstance(url, str) and len(url) <= MAX_IMAGE_CHARS
            and re.fullmatch(r"data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+", url) is not None)


@dataclass
class ChatJob:
    job_id: str = field(default_factory=lambda: f"job_{uuid.uuid4().hex}")
    task_id: str = ""
    prompt: str = ""
    timeout_s: int = 180
    new_chat: bool = True
    conversation_url: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    kind: str = "CHAT_TASK"
    images: List[str] = field(default_factory=list)

    def validate(self) -> None:
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 128:
            raise ValueError("task_id required")
        if not isinstance(self.images, list) or len(self.images) > MAX_IMAGES_PER_JOB:
            raise ValueError(f"images must be a list of at most {MAX_IMAGES_PER_JOB}")
        for url in self.images:
            if not _valid_image_url(url):
                raise ValueError("image must be a data:image/png|jpeg URL within size cap")
        if sum(len(u) for u in self.images) > MAX_IMAGES_TOTAL_CHARS:
            raise ValueError("images exceed total size cap")
        if self.kind not in JOB_TYPES:
            raise ValueError(f"unknown job kind {self.kind!r}")
        if self.kind == "STATUS_PROBE":
            if self.prompt and len(self.prompt) > 20000:
                raise ValueError("prompt max 20000 chars")
        elif not isinstance(self.prompt, str) or not self.prompt or len(self.prompt) > 20000:
            raise ValueError("prompt required (max 20000 chars)")
        if type(self.new_chat) is not bool or type(self.timeout_s) is not int or not (5 <= self.timeout_s <= 900):
            raise ValueError("timeout_s must be 5..900")
        if self.conversation_url is not None and not re.fullmatch(
                r"https://chatgpt\.com/c/[A-Za-z0-9-]{1,128}", self.conversation_url):
            raise ValueError("invalid conversation URL")
        if self.kind != "STATUS_PROBE" and not self.new_chat and not self.conversation_url:
            raise ValueError("continuation requires an explicit conversation URL")
        if self.new_chat and self.conversation_url:
            raise ValueError("new chat cannot target an existing conversation")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChatResult:
    job_id: str = ""
    task_id: str = ""
    status: str = "COMPLETED"  # COMPLETED | FAILED
    result: str = ""
    conversation_url: Optional[str] = None
    conversation_id: Optional[str] = None
    error: Optional[str] = None
    worker: str = ""
    # Telemetry: how many job images the extension confirmed pasted.
    # 0 with images submitted = paste failed (visible, never silent).
    images_attached: int = 0

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("job_id required")
        if not isinstance(self.result, str) or len(self.result) > 200000:
            raise ValueError("result must be text (max 200000 chars)")
        if self.conversation_url and not re.fullmatch(r"https://chatgpt\.com/c/[A-Za-z0-9-]{1,128}", self.conversation_url):
            raise ValueError("invalid conversation URL")
        if self.status not in ("COMPLETED", "FAILED"):
            raise ValueError(f"unknown status {self.status!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProgressReport:
    job_id: str = ""
    worker: str = ""
    lease_token: str = ""
    phase: str = ""

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("job_id required")
        if not self.worker or len(self.worker) > 100:
            raise ValueError("worker required (max 100 chars)")
        if not self.lease_token:
            raise ValueError("lease_token required")
        if self.phase not in PROGRESS_PHASES:
            raise ValueError(f"unknown phase {self.phase!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
