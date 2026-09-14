"""WS2 supervisor de longa duracao: mastiga MASTER_QUEUE 24/7 com watchdog.

Filosofia do repo: uma run executa no maximo uma tarefa; o supervisor e o
laco externo que faltava. Sem novas dependencias (stdlib + codigo do repo),
controle por arquivos-sentinela (funciona no Windows), sem replay de envio
incerto: item travado vira BLOCKED com replay_allowed=False e exige operador.

Uso real (via main.py --supervise): pluga MasterQueue + IntegratedRun.
Uso em teste: injete next_item/run_item/mark_stalled falsificaveis que
retornam dicts canned. Nenhuma chamada live acontece aqui por si so.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from pathlib import Path


DEFAULT_IDLE_EXIT_SECS = 300.0
DEFAULT_WATCHDOG_SECS = 600.0
DEFAULT_BACKOFF_BASE_SECS = 5.0
DEFAULT_BACKOFF_MAX_SECS = 300.0
DEFAULT_POLL_INTERVAL_SECS = 5.0

SUCCESS_STATUSES = frozenset({"CANDIDATE_READY", "COMPLETED", "APPLIED", "OK", "SUCCESS"})
STALLED_STATUSES = frozenset({"STALLED", "BLOCKED", "CANCELLED", "TIMEOUT", "CANCELLED_BY_WATCHDOG"})
IDLE_STATUS_EXACT = frozenset({"IDLE_OR_WAITING_FOR_DEPENDENCY_PROMOTION", "IDLE", "EMPTY", "NO_WORK"})


class SupervisorStall(RuntimeError):
    """Watchdog: a run ativa nao mostrou progresso em events.jsonl a tempo."""


def _is_success(result) -> bool:
    return isinstance(result, dict) and str(result.get("status", "")) in SUCCESS_STATUSES


def _is_idle_result(result) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status", ""))
    return status in IDLE_STATUS_EXACT or status.startswith("IDLE")


def _is_stalled_result(result) -> bool:
    return isinstance(result, dict) and str(result.get("status", "")) in STALLED_STATUSES


class Supervisor:
    """Daemon que consome trabalho ate idle-timeout, max-iterations ou stop.

    Parametros:
      workspace: diretorio do projeto (deve existir). Sentinelas e snapshot
        vivem em <workspace>/runs/.
      next_item: () -> dict | None. None significa ocioso. Pode ser sync ou
        async. Default: peek nao-destrutivo na MasterQueue (None quando nao ha
        jobs PENDING/RUNNING/BLOCKED).
      run_item: (item) -> dict | awaitable[dict]. Resultado canned com chave
        "status". Default: MasterQueue.run_next (claim+IntegratedRun+finish
        atomicos, com as mesmas garantias de escala/conversas/medicao).
        Runners sync devem retornar rapido; somente runners async podem ser
        cancelados pelo watchdog.
      mark_stalled: (item, reason) -> None | awaitable[None]. Default: no-op
        no modo MasterQueue (run_next ja marca BLOCKED sem replay); no modo
        injetado, chama o hook para o teste observar.
      clock: () -> float monotono para duracoes. Default time.monotonic.
      wall_clock: () -> float para timestamps. Default time.time.
      sleep: async (secs) -> None. Default asyncio.sleep. Injetavel para
        observar backoff sem espera real.
      max_iterations: None (ilimitado) ou int >= 1. Conta apenas runs
        nao-IDLE executadas.
      idle_exit_secs: segundos ociosos ate sair sozinho. 0 = nunca sai por
        ociosidade (daemon puro 24/7). Default 300.
      watchdog_secs: segundos sem progresso em events.jsonl ate cancelar a
        run ativa e marcar o item como travado, sem replay. Default 600.
      backoff_base_secs / backoff_max_secs: backoff exponencial
        base * 2**(falhas_consecutivas-1), limitado ao maximo. Default 5/300.
      poll_interval_secs: intervalo de polling para ociosidade/pausa e teto
        do polling do watchdog. Default 5.
      trust_workspace: repassado ao MasterQueue.run_next default. Default
        False (exige Docker, como --queue run).
    """

    def __init__(self, workspace, *, next_item=None, run_item=None,
                 mark_stalled=None, clock=None, wall_clock=None, sleep=None,
                 max_iterations=None, idle_exit_secs=DEFAULT_IDLE_EXIT_SECS,
                 watchdog_secs=DEFAULT_WATCHDOG_SECS,
                 backoff_base_secs=DEFAULT_BACKOFF_BASE_SECS,
                 backoff_max_secs=DEFAULT_BACKOFF_MAX_SECS,
                 poll_interval_secs=DEFAULT_POLL_INTERVAL_SECS,
                 trust_workspace=False,
                 pause_filename="SUPERVISOR.pause",
                 stop_filename="SUPERVISOR.stop",
                 status_filename="supervisor-status.json"):
        root = Path(workspace)
        if not root.is_dir():
            raise ValueError("workspace inexistente: %s" % (workspace,))
        self.workspace = root.resolve()
        if max_iterations is not None and (type(max_iterations) is not int or max_iterations < 1):
            raise ValueError("max_iterations deve ser None ou int >= 1")
        for name, value in (("idle_exit_secs", idle_exit_secs), ("watchdog_secs", watchdog_secs),
                            ("backoff_base_secs", backoff_base_secs), ("backoff_max_secs", backoff_max_secs),
                            ("poll_interval_secs", poll_interval_secs)):
            if not isinstance(value, (int, float)) or not (value == value):
                raise ValueError("%s deve ser numero" % name)
        if idle_exit_secs < 0:
            raise ValueError("idle_exit_secs deve ser >= 0 (0 = nunca sai por ociosidade)")
        if watchdog_secs <= 0:
            raise ValueError("watchdog_secs deve ser positivo")
        if backoff_base_secs <= 0 or backoff_max_secs < backoff_base_secs:
            raise ValueError("backoff requer 0 < base <= max")
        if poll_interval_secs <= 0:
            raise ValueError("poll_interval_secs deve ser positivo")
        self._next_item_fn = next_item
        self._run_item_fn = run_item
        self._mark_stalled_fn = mark_stalled
        self._clock = clock or time.monotonic
        self._wall = wall_clock or time.time
        self._sleep = sleep or asyncio.sleep
        self.max_iterations = max_iterations
        self.idle_exit_secs = float(idle_exit_secs)
        self.watchdog_secs = float(watchdog_secs)
        self.backoff_base_secs = float(backoff_base_secs)
        self.backoff_max_secs = float(backoff_max_secs)
        self.poll_interval_secs = float(poll_interval_secs)
        self.trust_workspace = bool(trust_workspace)
        self.pause_filename = pause_filename
        self.stop_filename = stop_filename
        self.status_filename = status_filename
        self.iterations = 0
        self.completed = 0
        self.failed = 0
        self.stalled = 0
        self.consecutive_failures = 0
        self.last_error = None
        self._started_at = None

    @property
    def _runs_dir(self) -> Path:
        return self.workspace / "runs"

    @property
    def _pause_path(self) -> Path:
        return self._runs_dir / self.pause_filename

    @property
    def _stop_path(self) -> Path:
        return self._runs_dir / self.stop_filename

    @property
    def _status_path(self) -> Path:
        return self._runs_dir / self.status_filename

    @property
    def _use_default_queue(self) -> bool:
        return self._run_item_fn is None

    def _backoff_delay(self) -> float:
        n = max(1, self.consecutive_failures)
        return min(self.backoff_max_secs, self.backoff_base_secs * (2.0 ** (n - 1)))

    @staticmethod
    def _run_id_for(item) -> str:
        if isinstance(item, dict):
            value = item.get("run_id") or item.get("id") or "supervisor-run"
            return str(value)
        return str(item)

    @staticmethod
    def _stat_snapshot(path: Path):
        try:
            st = path.stat()
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

    def _events_path_for(self, item):
        if isinstance(item, dict) and item.get("queue") == "master-queue":
            return self._discover_running_events_path()
        run_id = self._run_id_for(item)
        safe = "".join(c if (c.isalnum() or c in ("-", "_")) else "-" for c in run_id)[:80] or "run"
        return self._runs_dir / safe / "events.jsonl"

    def _discover_running_events_path(self):
        try:
            from .master_queue import MasterQueue
            try:
                mq = MasterQueue(self.workspace)
            except Exception:
                return None
            for job in mq.status().get("jobs", []):
                if job.get("state") == "RUNNING":
                    return self._runs_dir / ("mq-" + str(job.get("id"))) / "events.jsonl"
        except Exception:
            return None
        return None

    def _default_next_item(self):
        from .master_queue import MasterQueue
        try:
            mq = MasterQueue(self.workspace)
        except Exception:
            return None
        jobs = mq.status().get("jobs", [])
        if not jobs:
            return None
        if not any(j.get("state") in {"PENDING", "RUNNING", "BLOCKED"} for j in jobs):
            return None
        return {"id": "master-queue", "run_id": "master-queue", "queue": "master-queue"}

    async def _default_run_item(self, item):
        from .master_queue import MasterQueue
        mq = MasterQueue(self.workspace)
        return await mq.run_next(trust_workspace=self.trust_workspace)

    async def _resolve_next(self):
        fn = self._next_item_fn or self._default_next_item
        result = fn()
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _invoke_runner(self, item):
        fn = self._run_item_fn or self._default_run_item
        result = fn(item)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _notify_stalled(self, item, reason: str):
        if self._use_default_queue and self._mark_stalled_fn is None:
            return
        fn = self._mark_stalled_fn
        if fn is None:
            return
        result = fn(item, reason)
        if inspect.isawaitable(result):
            await result

    def _write_status(self, state: str, active_run, exit_reason):
        try:
            self._runs_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "state": state,
                "active_run": active_run,
                "iterations": self.iterations,
                "completed": self.completed,
                "failed": self.failed,
                "stalled": self.stalled,
                "consecutive_failures": self.consecutive_failures,
                "last_error": self.last_error,
                "exit_reason": exit_reason,
                "started_at": self._started_at,
                "updated_at": self._wall(),
                "workspace": str(self.workspace),
                "pid": os.getpid(),
                "limits": {
                    "max_iterations": self.max_iterations,
                    "idle_exit_secs": self.idle_exit_secs,
                    "watchdog_secs": self.watchdog_secs,
                },
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            tmp = self._status_path.with_name(self._status_path.name + ".tmp.%d" % os.getpid())
            tmp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(str(tmp), str(self._status_path))
        except OSError:
            pass

    def _watchdog_poll(self) -> float:
        return min(self.poll_interval_secs, max(0.01, self.watchdog_secs / 4.0))

    async def _run_with_watchdog(self, item):
        start = self._clock()
        last_progress = start
        last_stat = self._stat_snapshot(self._events_path_for(item) or Path("__missing__"))
        if last_stat is None:
            last_stat = self._missing_marker()
        task = asyncio.create_task(self._invoke_runner(item))
        try:
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=self._watchdog_poll())
                except asyncio.TimeoutError:
                    pass
                if task.done():
                    break
                current_path = self._events_path_for(item)
                now = self._clock()
                if current_path is None:
                    continue
                current = self._stat_snapshot(current_path)
                if current is not None and current != last_stat:
                    last_progress = now
                    last_stat = current
                elif current is None:
                    if now - start >= self.watchdog_secs:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise SupervisorStall(
                            "watchdog: sem progresso por %gs (sem events.jsonl para %s)"
                            % (self.watchdog_secs, self._run_id_for(item)))
                elif now - last_progress >= self.watchdog_secs:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    raise SupervisorStall(
                        "watchdog: sem progresso por %gs em %s"
                        % (self.watchdog_secs, self._run_id_for(item)))
            return task.result()
        finally:
            if not task.done():
                task.cancel()

    @staticmethod
    def _missing_marker():
        return ("__missing__", -1)

    async def serve(self) -> dict:
        """Laco principal. Retorna resumo com exit_reason e contadores."""
        self._started_at = self._wall()
        last_activity = self._clock()
        exit_reason = None
        state = "running"
        active_run = None
        self._write_status(state, active_run, exit_reason)
        try:
            while True:
                if self.max_iterations is not None and self.iterations >= self.max_iterations:
                    exit_reason = "max-iterations"
                    break
                if self._stop_path.exists():
                    exit_reason = "stop-requested"
                    state = "stopping"
                    self._write_status(state, active_run, exit_reason)
                    break
                if self._pause_path.exists():
                    state = "paused"
                    last_activity = self._clock()
                    self._write_status(state, active_run, exit_reason)
                    await self._sleep(self.poll_interval_secs)
                    continue
                state = "running"
                try:
                    item = await self._resolve_next()
                except Exception as exc:
                    self.consecutive_failures += 1
                    self.failed += 1
                    self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:500])
                    self._write_status(state, None, None)
                    if self.max_iterations is not None and self.iterations >= self.max_iterations:
                        exit_reason = "max-iterations"
                        break
                    await self._sleep(self._backoff_delay())
                    continue
                if item is None:
                    idle_for = self._clock() - last_activity
                    if self.idle_exit_secs > 0 and idle_for >= self.idle_exit_secs:
                        exit_reason = "idle-timeout"
                        break
                    state = "idle"
                    self._write_status(state, None, None)
                    remaining = self.poll_interval_secs
                    if self.idle_exit_secs > 0:
                        remaining = min(remaining, max(0.01, self.idle_exit_secs - idle_for))
                    await self._sleep(min(self.poll_interval_secs, remaining))
                    continue
                active_run = self._run_id_for(item)
                self._write_status("running", active_run, None)
                try:
                    result = await self._run_with_watchdog(item)
                except SupervisorStall as exc:
                    self.iterations += 1
                    self.stalled += 1
                    self.consecutive_failures += 1
                    self.last_error = str(exc)[:500]
                    last_activity = self._clock()
                    try:
                        await self._notify_stalled(item, self.last_error)
                    except Exception:
                        pass
                    self._write_status("running", None, None)
                    if self.max_iterations is not None and self.iterations >= self.max_iterations:
                        exit_reason = "max-iterations"
                        break
                    await self._sleep(self._backoff_delay())
                    active_run = None
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.iterations += 1
                    self.failed += 1
                    self.consecutive_failures += 1
                    self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:500])
                    last_activity = self._clock()
                    self._write_status("running", None, None)
                    if self.max_iterations is not None and self.iterations >= self.max_iterations:
                        exit_reason = "max-iterations"
                        break
                    await self._sleep(self._backoff_delay())
                    active_run = None
                    continue
                if _is_idle_result(result):
                    active_run = None
                    idle_for = self._clock() - last_activity
                    if self.idle_exit_secs > 0 and idle_for >= self.idle_exit_secs:
                        exit_reason = "idle-timeout"
                        break
                    state = "idle"
                    self._write_status(state, None, None)
                    await self._sleep(self.poll_interval_secs)
                    continue
                self.iterations += 1
                last_activity = self._clock()
                if _is_success(result):
                    self.completed += 1
                    self.consecutive_failures = 0
                    self.last_error = None
                    self._write_status("running", None, None)
                elif _is_stalled_result(result):
                    self.stalled += 1
                    self.consecutive_failures += 1
                    detail = ""
                    if isinstance(result, dict):
                        detail = str(result.get("error") or result.get("reason") or result.get("status") or "")[:300]
                    self.last_error = ("travado: %s" % detail) if detail else "travado sem replay; operador requerido"
                    try:
                        await self._notify_stalled(item, self.last_error)
                    except Exception:
                        pass
                    self._write_status("running", None, None)
                    if self.max_iterations is not None and self.iterations >= self.max_iterations:
                        exit_reason = "max-iterations"
                        break
                    await self._sleep(self._backoff_delay())
                else:
                    self.failed += 1
                    self.consecutive_failures += 1
                    detail = ""
                    if isinstance(result, dict):
                        errors = result.get("errors") or []
                        detail = str(result.get("error") or (errors[0] if errors else result.get("status") or "FAILED"))[:500]
                    self.last_error = detail or "falha sem detalhe"
                    self._write_status("running", None, None)
                    if self.max_iterations is not None and self.iterations >= self.max_iterations:
                        exit_reason = "max-iterations"
                        break
                    await self._sleep(self._backoff_delay())
                active_run = None
                if self.max_iterations is not None and self.iterations >= self.max_iterations:
                    exit_reason = "max-iterations"
                    break
        except asyncio.CancelledError:
            exit_reason = exit_reason or "interrupted"
            self._write_status("stopping", active_run, exit_reason)
            raise
        except KeyboardInterrupt:
            exit_reason = exit_reason or "interrupted"
            self._write_status("stopping", active_run, exit_reason)
            raise
        exit_reason = exit_reason or "idle-timeout"
        self._write_status("done", None, exit_reason)
        return {
            "exit_reason": exit_reason,
            "iterations": self.iterations,
            "completed": self.completed,
            "failed": self.failed,
            "stalled": self.stalled,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "status_path": str(self._status_path),
        }

    def run(self) -> dict:
        """Envoltório síncrono para CLI: asyncio.run(self.serve())."""
        return asyncio.run(self.serve())
