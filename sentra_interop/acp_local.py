"""ACP local supervisor with crash-safe *replay prevention* and reconciliation.

Owns the direct stdio child, delegates all effects to the existing ACP gate,
and persists only SHA-256 request fingerprints and states. It
never stores raw prompts, credentials or authorization material. Reopening the
SQLite ledger never retries an UNCERTAIN effect or reattaches to a live PID.
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncIterator, Mapping, Any

from sentra_runtime.contracts import OperationRequest, OperationResult
from .acp import ACPSessionAdapter, ACPStdioTransport
from .acp_session import ACPSessionStore, identity
from .gate import DispatchOutcome, InteropGate, _fingerprint


class ACPReplayBlocked(ValueError):
    pass


class ACPLocalLedger:
    """SQLite transaction reserves idempotency key before any remote effect."""

    def __init__(self, database: str, *, workspace: str) -> None:
        target = Path(database).resolve()
        root = Path(workspace).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError("ACP local ledger must live inside trusted workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path = target
        with self._db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS acp_receipts (
                operation_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL,
                kind TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                  ('IN_FLIGHT','SUCCEEDED','FAILED','CANCELLED','UNCERTAIN')),
                pid INTEGER
            )""")

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reserve(self, request: OperationRequest, kind: str) -> None:
        if kind not in {"launch", "open", "prompt", "cancel", "resume", "list", "close", "delete", "config", "mode"}:
            raise ValueError("invalid ACP operation")
        signature = _fingerprint(request)
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT fingerprint, state FROM acp_receipts WHERE operation_id=? "
                "OR idempotency_key=?", (request.operation_id, request.idempotency_key)
            ).fetchone()
            if current:
                raise ACPReplayBlocked("ACP operation already recorded; reconcile, never resend")
            conn.execute("""INSERT INTO acp_receipts
                (operation_id,idempotency_key,fingerprint,kind,state)
                VALUES (?,?,?,?,?)""", (
                    request.operation_id, request.idempotency_key,
                    signature, kind, "IN_FLIGHT",
                ))

    def finish(self, request: OperationRequest, state: str, *, pid: int | None = None) -> None:
        if state not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
            raise ValueError("invalid ACP terminal state")
        with self._db() as conn:
            updated = conn.execute(
                "UPDATE acp_receipts SET state=?, pid=? "
                "WHERE operation_id=? AND fingerprint=?",
                (state, pid, request.operation_id, _fingerprint(request)),
            )
            if updated.rowcount != 1:
                raise ACPReplayBlocked("unknown or changed ACP receipt")

    def reconcile(self, operation_id: str) -> OperationResult | None:
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state FROM acp_receipts WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                return None
            state = row[0]
            if state == "IN_FLIGHT":
                # After crash or closed parent there is no authoritative
                # confirmation of completion. Never claim success or retry.
                conn.execute(
                    "UPDATE acp_receipts SET state='UNCERTAIN' WHERE operation_id=?",
                    (operation_id,),
                )
                state = "UNCERTAIN"
            return OperationResult(operation_id, state if state != "IN_FLIGHT" else "UNCERTAIN")


class ACPLocalLifecycle:
    """Explicit lifecycle façade; only for approved local ACP subprocesses."""

    def __init__(self, gate: InteropGate, *, workspace: str, ledger_path: str,
                 local_session_id: str | None = None, provider: str = "local",
                 supported_versions: tuple[int, ...] = (1,)) -> None:
        identity(provider)
        if local_session_id is not None:
            identity(local_session_id)
        if not supported_versions or any(type(v) is not int or v not in (1, 2) for v in supported_versions):
            raise ValueError("unsupported ACP revision")
        self.gate = gate
        self.workspace = str(Path(workspace).resolve())
        self.ledger = ACPLocalLedger(ledger_path, workspace=self.workspace)
        self.session_store = ACPSessionStore(ledger_path, workspace=self.workspace)
        self.local_session_id, self.provider = local_session_id, provider
        self.supported_versions = supported_versions
        self.transport: ACPStdioTransport | None = None
        self.adapter: ACPSessionAdapter | None = None

    async def start(self, *, executable: str, argv: tuple[str, ...], cwd: str,
                    launch_request: OperationRequest,
                    session_request: OperationRequest,
                    reattach: bool = False) -> DispatchOutcome:
        if self.transport is not None:
            raise ACPReplayBlocked("ACP lifecycle already started")
        self.ledger.reserve(launch_request, "launch")
        try:
            transport = await ACPStdioTransport.launch(
                executable, argv, cwd=cwd, gate=self.gate, request=launch_request)
            self.transport = transport
            self.ledger.finish(launch_request, "SUCCEEDED", pid=transport.process.pid)
        except BaseException:
            self.ledger.finish(launch_request, "UNCERTAIN")
            raise
        self.adapter = ACPSessionAdapter(self.gate, transport, workspace=self.workspace,
            store=self.session_store if self.local_session_id is not None else None,
            local_session_id=self.local_session_id, provider=self.provider,
            supported_versions=self.supported_versions)
        reserved = False
        try:
            self.ledger.reserve(session_request, "resume" if reattach else "open")
            reserved = True
            outcome = (await self.adapter.reattach(session_request, timeout=4) if reattach
                       else await self.adapter.open(session_request, cwd=cwd, timeout=4))
            self.ledger.finish(session_request, outcome.operation.state)
            if outcome.operation.state != "SUCCEEDED":
                await self.close()
            return outcome
        except BaseException:
            if reserved:
                self.ledger.finish(session_request, "UNCERTAIN")
            await self.close()
            raise

    async def prompt(self, request: OperationRequest, text: str, *,
                     timeout: float = 3) -> DispatchOutcome:
        if self.adapter is None:
            raise ValueError("ACP session not started")
        self.ledger.reserve(request, "prompt")
        try:
            result = await self.adapter.prompt(request, text, timeout=timeout)
            self.ledger.finish(request, result.operation.state)
            return result
        except BaseException:
            self.ledger.finish(request, "UNCERTAIN")
            raise

    async def cancel(self, request: OperationRequest) -> OperationResult:
        if self.adapter is None:
            raise ValueError("ACP session not started")
        self.ledger.reserve(request, "cancel")
        try:
            result = await self.adapter.cancel(request)
            self.ledger.finish(request, result.state)
            return result
        except BaseException:
            self.ledger.finish(request, "UNCERTAIN")
            raise

    async def updates(self, *, timeout: float = 3) -> AsyncIterator[Mapping[str, Any]]:
        if self.adapter is None:
            raise ValueError("ACP session not started")
        async for update in self.adapter.updates(timeout=timeout):
            yield update

    def reconcile(self, operation_id: str) -> OperationResult | None:
        return self.ledger.reconcile(operation_id)

    async def _dispatch(self, request: OperationRequest, kind: str, method: str, **kwargs) -> DispatchOutcome:
        if self.adapter is None:
            raise ValueError("ACP session not started")
        self.ledger.reserve(request, kind)
        try:
            result = await getattr(self.adapter, method)(request, **kwargs)
            self.ledger.finish(request, result.operation.state)
            return result
        except BaseException:
            self.ledger.finish(request, "UNCERTAIN")
            raise

    async def resume(self, request: OperationRequest, *, session_id: str, cwd: str,
                     timeout: float = 30, load_history: bool = False) -> DispatchOutcome:
        return await self._dispatch(request, "resume", "resume", session_id=session_id,
                                    cwd=cwd, timeout=timeout, load_history=load_history)

    async def list_sessions(self, request: OperationRequest, *, cwd: str | None = None,
                            cursor: str | None = None, timeout: float = 30) -> DispatchOutcome:
        return await self._dispatch(request, "list", "list_sessions", cwd=cwd, cursor=cursor, timeout=timeout)

    async def close_session(self, request: OperationRequest, *, timeout: float = 30) -> DispatchOutcome:
        return await self._dispatch(request, "close", "close_session", timeout=timeout)

    async def delete_session(self, request: OperationRequest, *, session_id: str,
                             timeout: float = 30) -> DispatchOutcome:
        return await self._dispatch(request, "delete", "delete_session", session_id=session_id, timeout=timeout)

    async def set_config_option(self, request: OperationRequest, *, config_id: str,
                                value: str | bool, timeout: float = 30) -> DispatchOutcome:
        return await self._dispatch(request, "config", "set_config_option", config_id=config_id,
                                    value=value, timeout=timeout)

    async def set_model(self, request: OperationRequest, *, model_id: str,
                        timeout: float = 30) -> DispatchOutcome:
        return await self._dispatch(request, "config", "set_model", model_id=model_id, timeout=timeout)

    async def set_mode(self, request: OperationRequest, *, mode_id: str,
                       timeout: float = 30) -> DispatchOutcome:
        return await self._dispatch(request, "mode", "set_mode", mode_id=mode_id, timeout=timeout)

    async def close(self) -> None:
        if self.transport is not None:
            await self.transport.close()
            if self.adapter is not None:
                self.adapter.detach()
            self.transport = None
            self.adapter = None
