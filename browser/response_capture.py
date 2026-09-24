from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from typing import Any, Awaitable, Callable, Optional


# Heartbeat de progresso: (fase, timestamp). Fase em
# {"sending", "sent", "waiting", "reading", ...} (fases de espera alinhadas
# ao relay: waiting/reading); timestamp = time.time(). Síncrono ou async.
ProgressCallback = Callable[[str, float], Any]
TextInterceptor = Callable[[str], Any]


async def emit_progress(on_progress: Optional[ProgressCallback], phase: str) -> None:
    """Emite um heartbeat best-effort: nunca quebra o fluxo principal.

    Falhas do callback são engolidas; CancelledError/BaseException propagam
    (RF-017) para não mascarar cancelamento.
    """
    if on_progress is None:
        return
    try:
        res = on_progress(phase, time.time())
        if inspect.isawaitable(res):
            await res
    except Exception:
        pass


def supports_kwarg(fn: Any, kwarg: str) -> bool:
    """Diz se `fn` aceita a kwarg `kwarg` (ou **kwargs).

    Compatibilidade na fronteira old/new: o hook on_progress é repassado só
    a quem o declara; doubles/sessões legadas sem o parâmetro continuam
    funcionando (sem heartbeat) em vez de quebrar com TypeError.
    """
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD or p.name == kwarg for p in params
    )


class ResponseCapture:
    DEFAULT_POLL_INTERVAL_S = 1.5
    DEFAULT_HEARTBEAT_INTERVAL_S = 10.0

    @staticmethod
    async def wait_for_stable_response(
        extract_text_fn: Callable[[], Awaitable[str]],
        is_finished_fn: Callable[[], Awaitable[bool]],
        timeout_seconds: int = 600,
        stable_samples: int = 3,
        *,
        baseline_text: Optional[str] = None,
        poll_interval_s: float = 1.5,
        heartbeat_interval_s: float = 10.0,
        on_progress: Optional[ProgressCallback] = None,
        text_interceptor: Optional[TextInterceptor] = None,
        end_marker: str = "END_RESULT",
    ) -> str:
        """Espera orientada a estado como observer.js: stop some E texto estabiliza.

        - Estabilidade = hash sha256 igual em `stable_samples` amostras seguidas.
        - `baseline_text` = texto do turno anterior: amostras iguais a ele são
          ignoradas (o turno velho nunca satisfaz o envio novo).
        - Deadline absoluto: o estouro sempre vira TimeoutError estruturado,
          nunca retorno parcial silencioso.
        - Heartbeat: `on_progress(fase, timestamp)` no início, a cada
          `heartbeat_interval_s` e na conclusão, para o provider reportar
          durante gerações longas (sem isso o relay declara WORKER_LOST).
        CancelledError sempre propaga (RF-017).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds

        # Teto por sondagem: chamadas CDP numa aba congelada travam para
        # sempre, e o deadline acima só é checado ENTRE iterações. Sem este
        # teto, uma aba morta segura o loop até o timeout externo (15min)
        # sem nenhum diagnóstico. Com ele, N sondas mudas seguidas viram
        # TAB_UNRESPONSIVE alto e rápido (ainda TIMEOUT para o engine).
        POLL_BUDGET_S = 20.0
        MAX_UNRESPONSIVE_POLLS = 6

        previous_hash = None
        stable_count = 0
        last_text = ""
        unresponsive_streak = 0

        await emit_progress(on_progress, "waiting")
        last_beat = time.time()

        while loop.time() < deadline:
            poll_ok = True
            try:
                text = await asyncio.wait_for(extract_text_fn(), timeout=POLL_BUDGET_S)
            except Exception:
                text = ""
                poll_ok = False
            if not isinstance(text, str):
                text = ""

            # Interceptor de estados especiais da UI. Diferente das sondagens
            # best-effort acima, erros daqui propagam: uma recuperação que
            # falhou não pode ser mascarada como simples timeout silencioso.
            if text_interceptor is not None:
                intercepted = text_interceptor(text)
                if inspect.isawaitable(intercepted):
                    intercepted = await intercepted
                if intercepted is not None:
                    text = intercepted if isinstance(intercepted, str) else str(intercepted)

            # Guarda de baseline (observer.js): enquanto o texto for o turno
            # anterior, a geração nova nem começou — nunca conta como estável
            # nem satisfaz a espera. O heartbeat continua pulsando no período.
            if baseline_text is not None and text == baseline_text:
                stale = True
                stable_count = 0
            else:
                stale = False
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

                if text_hash == previous_hash and text:
                    stable_count += 1
                else:
                    stable_count = 0
                    previous_hash = text_hash

            last_text = text

            try:
                finished = await asyncio.wait_for(is_finished_fn(), timeout=POLL_BUDGET_S)
            except Exception:
                finished = False
                poll_ok = False

            if poll_ok:
                unresponsive_streak = 0
            else:
                unresponsive_streak += 1
                if unresponsive_streak >= MAX_UNRESPONSIVE_POLLS:
                    raise TimeoutError(
                        f"TAB_UNRESPONSIVE: chatgpt.com parou de responder a sondagens "
                        f"({unresponsive_streak} sondas consecutivas sem resposta em "
                        f"{int(POLL_BUDGET_S)}s cada); aba provavelmente suspensa, "
                        f"congelada ou fechada"
                    )

            now_wall = time.time()
            if on_progress is not None and (now_wall - last_beat) >= heartbeat_interval_s:
                await emit_progress(on_progress, "reading" if (text and finished) else "waiting")
                last_beat = now_wall

            if not stale and finished and stable_count >= stable_samples:
                await emit_progress(on_progress, "reading")
                return text

            # If END_RESULT marker is present and stable sample count reached
            if not stale and end_marker and end_marker in text and stable_count >= stable_samples:
                await emit_progress(on_progress, "reading")
                return text

            await asyncio.sleep(poll_interval_s)

        # Deadline exceeded without stable finished response: surface a real
        # timeout (RF-016) instead of silently returning a partial capture.
        # Callers that want a degraded fallback must catch this explicitly.
        raise TimeoutError(
            f"Timed out after {timeout_seconds}s waiting for stable chatgpt.com response "
            f"(last capture {len(last_text)} chars, stable_samples={stable_count}/{stable_samples})"
        )
