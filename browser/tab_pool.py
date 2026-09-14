"""TabPool — N tabs reais servem M conversas (M >> N) por reutilização.

50 tarefas -> 3 workers: cada worker pega a próxima tarefa ao concluir.
A fila vive no OMA; aqui só há atribuição determinística + estados.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from .worker import BrowserWorker


class TabPool:
    def __init__(self, min_tabs: int = 1, max_tabs: int = 4):
        if not (1 <= min_tabs <= max_tabs):
            raise ValueError(f"invalid pool bounds: min_tabs={min_tabs} max_tabs={max_tabs}")
        self.min_tabs = min_tabs
        self.max_tabs = max_tabs
        self.workers: List[BrowserWorker] = [
            BrowserWorker(worker_id=f"BROWSER_WORKER_{i + 1:02d}")
            for i in range(min_tabs)
        ]
        self._lock = asyncio.Lock()

    def _idle_worker(self) -> Optional[BrowserWorker]:
        for w in self.workers:
            if w.state == "IDLE":
                return w
        return None

    def snapshot(self) -> List[Dict[str, Any]]:
        return [{"worker_id": w.worker_id, "state": w.state,
                 "task": w.current_task_id, "completed": w.completed} for w in self.workers]

    async def run_all(self, task_ids: List[str],
                      handler: Callable[[BrowserWorker, str], Any],
                      timeout_per_task: float = 300.0) -> Dict[str, Any]:
        """Distribui task_ids entre workers com concorrência = nº de workers.

        handler(worker, task_id) executa o trabalho real (rede/relay) e pode
        levantar exceção (= falha da tarefa) ou asyncio.CancelledError (= cancela tudo).
        Retorna {completed: [...], failed: {task: error}} sem perder/duplicar tarefas.
        """
        queue: asyncio.Queue = asyncio.Queue()
        for t in task_ids:
            queue.put_nowait(t)
        completed: List[str] = []
        failed: Dict[str, str] = {}

        async def _worker_loop(worker: BrowserWorker) -> None:
            while True:
                try:
                    task_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                async with self._lock:
                    worker.state = "BUSY"
                    worker.current_task_id = task_id
                try:
                    async with self._lock:
                        worker.state = "WAITING_RESPONSE"
                    await asyncio.wait_for(handler(worker, task_id), timeout=timeout_per_task)
                    async with self._lock:
                        worker.completed += 1
                    completed.append(task_id)
                except asyncio.CancelledError:
                    async with self._lock:
                        worker.state = "IDLE"
                        worker.current_task_id = None
                    raise
                except Exception as e:
                    async with self._lock:
                        worker.failed += 1
                    failed[task_id] = str(e)[:2000]
                finally:
                    async with self._lock:
                        worker.state = "IDLE"
                        worker.current_task_id = None
                    queue.task_done()

        # Expande até max_tabs se houver mais tarefas que workers
        while len(self.workers) < min(self.max_tabs, len(task_ids)):
            self.workers.append(BrowserWorker(worker_id=f"BROWSER_WORKER_{len(self.workers) + 1:02d}"))

        await asyncio.gather(*[_worker_loop(w) for w in self.workers])
        # Prova de não-perda/não-duplicação como erro explícito (assert some com -O).
        if len(completed) + len(failed) != len(task_ids):
            raise RuntimeError(
                f"TabPool perdeu tarefas: {len(completed)} ok + {len(failed)} falhas "
                f"!= {len(task_ids)} submetidas")
        if len(set(completed)) != len(completed):
            raise RuntimeError("TabPool executou tarefa duplicada")
        return {"completed": completed, "failed": failed, "workers": self.snapshot()}
