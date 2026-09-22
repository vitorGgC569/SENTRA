"""Compact repository gateway with session policy, transactions and audit evidence."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from .parser import Directive, parse as parse_directive
from .policy import PolicyDenied, PolicyEngine, PROTECTED_COMPONENTS
from .registry import CommandContext, CommandRegistry, line_range, read_text
from .result_store import ResultStore, MAX_PAGE_CHARS
from .session import PathEscapeError, RepositorySession, SessionManager
from .transactions import TransactionManager
from .git_adapter import GitAdapter


def estimate_tokens(text: str) -> int:
    return (len(text or "") + 3) // 4


class AgentConsoleBridge:
    @staticmethod
    def show(agent_id: str, directive: Directive, status: str, extra: str = "") -> None:
        print(f"[OMA COMMAND] Agent: {agent_id} Operation: {directive.operation} Status: {status} {extra}".strip(),
              flush=True)


class CommandGateway:
    def __init__(self, repository_root: Path, event_sink=None, *, execution=None, profiles=None):
        self.root = Path(repository_root).resolve()
        from workspace.docker_runner import settings
        self.execution, self.profiles = settings(execution), profiles
        self.sessions = SessionManager(self.root)
        self.policy = PolicyEngine()
        self.registry = CommandRegistry()
        self.txns = TransactionManager()
        self.results = ResultStore()
        self.audit: List[Dict[str, Any]] = []
        self.event_sink = event_sink
        self.command_count = self.read_bytes = self.returned_tokens = 0
        self.cache_hits = self.artifact_reuse = 0
        self._git_adapters: Dict[str, GitAdapter] = {}
        self._lock = asyncio.Lock()
        self._idempotency: Dict[tuple, tuple] = {}
        for op in ("PATCH", "W", "DIFF", "STATUS", "BRANCH", "CHECKPOINT", "ROLLBACK", "NEXT", "RART",
                   "GIT_DIFF", "GIT_STATUS"):
            self.registry.register(op, _GatewayCommand(self, op))

    def _git(self, session: RepositorySession) -> GitAdapter:
        key = str(session.repository_root)
        if key not in self._git_adapters:
            self._git_adapters[key] = GitAdapter(session.repository_root)
        return self._git_adapters[key]

    def open_session(self, **kw) -> RepositorySession:
        return self.sessions.open(**kw)

    def close_session(self, session: RepositorySession) -> None:
        self.results.close_session(session)
        self.sessions.sessions.pop(session.session_id, None)
        self._idempotency = {k: v for k, v in self._idempotency.items() if k[0] != session.session_id}

    def stage_patch(self, session: RepositorySession, patch_text: str) -> str:
        if len(patch_text.encode("utf-8")) > 1_000_000:
            raise ValueError("patch exceeds byte budget")
        return session.register_alias("P", patch_text)

    def stage_artifact(self, session: RepositorySession, content: str) -> str:
        if len(content.encode("utf-8")) > 1_000_000:
            raise ValueError("artifact exceeds byte budget")
        return session.register_alias("A", content)

    def _audit(self, session, agent_id, task_id, directive, status, result=""):
        txn = self.txns._txns.get(session.transaction_id) if directive.operation in {"PATCH", "W", "ROLLBACK"} else None
        entry = {
            "event": "REPOSITORY_COMMAND", "agent_id": agent_id, "task_id": task_id,
            "session_id": session.session_id, "operation": directive.operation,
            "target": "|".join(directive.args[:2]), "timestamp": time.time(), "status": status,
            "transaction_id": txn.transaction_id if txn else None,
            "before_hash": txn.before if txn else None, "after_hash": txn.after if txn else None,
            "result_hash": hashlib.sha256(result.encode("utf-8")).hexdigest(),
            "returned_chars": len(result),
        }
        self.audit.append(entry)
        # Persist only metadata/hashes: source and credentials are not copied to logs.
        directory = self.root / ".oma"
        if directory.is_symlink() or directory.resolve().parent != self.root:
            raise PolicyDenied("audit directory must be local to the repository")
        directory.mkdir(exist_ok=True)
        journal = directory / "repository-events.jsonl"
        if journal.is_symlink() or (journal.exists() and journal.stat().st_nlink > 1):
            raise PolicyDenied("audit journal may not be a link")
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")
        if self.event_sink:
            self.event_sink(entry)

    async def execute(self, session: RepositorySession, text: str, agent_id: str = "executor",
                      task_id: str = "T-000", role: str = "executor",
                      idempotency_key: str | None = None) -> str:
        # Serializes shared aliases, transactions and retries for this gateway.
        async with self._lock:
            return await self._execute(session, text, agent_id, task_id, role, idempotency_key)

    async def _execute(self, session, text, agent_id, task_id, role, idempotency_key):
        if self.sessions.sessions.get(session.session_id) is not session:
            return "ERROR DENIED: unknown repository session"
        session.touch()
        directive = parse_directive(text)
        if directive is None:
            directive = Directive("INVALID", [], "", known=False)
            result = "ERROR: invalid directive (expected a single [[OP|args]] line)"
            self._audit(session, agent_id, task_id, directive, "DENIED", result)
            return result
        AgentConsoleBridge.show(agent_id, directive, "EXECUTING")
        self.command_count += 1
        status = "SUCCESS"
        result = ""
        try:
            protected = self._touches_protected(session, directive)
            self.policy.validate(role, directive, targets_protected=protected, session=session)
            handler = self.registry.get(directive.operation)
            if handler is None:
                raise PolicyDenied(f"UNKNOWN_OPERATION: {directive.operation}")
            key = None
            if idempotency_key is not None:
                if not idempotency_key or len(idempotency_key) > 128 or not all(
                        c.isascii() and (c.isalnum() or c in "-_.:") for c in idempotency_key):
                    raise PolicyDenied("invalid idempotency key")
                key = (session.session_id, task_id, agent_id, idempotency_key)
                fingerprint = hashlib.sha256((role + "\n" + text).encode("utf-8")).hexdigest()
                if key in self._idempotency:
                    prior_hash, prior_result = self._idempotency[key]
                    if prior_hash != fingerprint:
                        raise PolicyDenied("idempotency key reused with a different operation")
                    self._audit(session, agent_id, task_id, directive, "REPLAY", prior_result)
                    return prior_result
            if directive.operation in {"PATCH", "W", "ROLLBACK"}:
                session.transaction_id = None
            ctx = CommandContext(session, agent_id, task_id, gateway=self)
            timeout = 605 if directive.operation in {"TEST", "BUILD", "LINT", "TYPECHECK", "BENCH"} else 60
            result = await asyncio.wait_for(handler.execute(directive, ctx), timeout)
            if result.startswith("CACHE_HIT"):
                self.cache_hits += 1
            if result.startswith("ERROR") or " FAIL " in result.split("\n", 1)[0] or result.startswith("PATCH FAIL"):
                status = "FAILED"
            self.read_bytes += len(result.encode("utf-8"))
            if len(result.splitlines()) > 200 or len(result) > MAX_PAGE_CHARS:
                _, result, _ = self.results.store(result, session, summary=f"{directive.operation} paged")
            if protected and directive.operation in {"PATCH", "W"} and status == "SUCCESS":
                result += "\nPROTECTED_CANDIDATE: external promotion authorization required"
            if key is not None:
                self._idempotency[key] = (fingerprint, result)
        except asyncio.CancelledError:
            self._audit(session, agent_id, task_id, directive, "CANCELLED")
            raise
        except TimeoutError:
            status, result = "TIMEOUT", f"ERROR TIMEOUT: {directive.operation} exceeded deadline"
        except (PolicyDenied, PathEscapeError) as exc:
            status, result = "DENIED", f"ERROR DENIED: {exc}"
        except Exception as exc:
            status, result = "FAILED", f"ERROR: {exc}"
        self.returned_tokens += estimate_tokens(result)
        self._audit(session, agent_id, task_id, directive, status, result)
        AgentConsoleBridge.show(agent_id, directive, status)
        return result

    def _touches_protected(self, session: RepositorySession, directive: Directive) -> bool:
        from workspace.patch_manager import PatchManager
        paths = []
        if directive.operation == "PATCH" and directive.args:
            patch = session.patch_registry.get(directive.args[0], "")
            if patch:
                paths = [p.path for p in PatchManager.parse_files(patch)]
        elif directive.operation in {"W", "R"} and directive.args:
            paths = [directive.args[0]]
        return any(session.resolve_path(p).relative_to(session.repository_root).as_posix()
                   in PROTECTED_COMPONENTS for p in paths)

    def efficiency_report(self) -> Dict[str, Any]:
        # Source bytes are not a measured no-gateway baseline. Do not invent savings.
        return {"command_count": self.command_count, "read_bytes": self.read_bytes,
                "returned_tokens": self.returned_tokens, "token_count_kind": "character_estimate",
                "tokens_without_gateway_est": None, "tokens_saved_est": None,
                "cache_hits": self.cache_hits, "artifact_reuse": self.artifact_reuse}


class _GatewayCommand:
    def __init__(self, gateway, operation):
        self.gw, self.operation = gateway, operation

    async def execute(self, directive, ctx):
        return await getattr(self, "_" + self.operation.lower())(directive.args, ctx)

    async def _patch(self, args, ctx):
        from workspace.patch_manager import PatchManager
        if len(args) != 1 or args[0] not in ctx.session.patch_registry:
            return "ERROR: usage [[PATCH|staged Pxx]]"
        patch = ctx.session.patch_registry[args[0]]
        targets = [ctx.session.resolve_path(p.path) for p in PatchManager.parse_files(patch)]
        txn = self.gw.txns.begin(ctx.agent_id, ctx.task_id, targets, ctx.session.session_id)
        ctx.session.transaction_id = txn.transaction_id
        res = PatchManager.apply_patch(ctx.session.repository_root, patch)
        if not res["success"]:
            self.gw.txns.rollback(txn)
            return f"PATCH FAIL ROLLBACK txn={txn.transaction_id}: {res['error']}"
        try:
            for path in targets:
                if path.suffix == ".py" and path.exists():
                    compile(path.read_bytes(), str(path), "exec")
        except Exception as exc:
            self.gw.txns.rollback(txn)
            return f"PATCH FAIL syntax invalid, ROLLBACK txn={txn.transaction_id}: {exc}"
        self.gw.txns.commit(txn, targets)
        alias = ctx.session.register_alias("T", txn.transaction_id)
        return (f"PATCH OK txn={txn.transaction_id} ({alias}) files={res['applied_files']}\n"
                f"BEFORE {txn.before}\nAFTER {txn.after}")

    async def _w(self, args, ctx):
        from workspace.patch_manager import _atomic_write
        if len(args) != 2 or args[1] not in ctx.session.artifact_aliases:
            return "ERROR: usage [[W|path|staged Axx]]"
        target = ctx.session.resolve_path(args[0])
        content = ctx.session.artifact_aliases[args[1]].encode("utf-8")
        if target.suffix == ".py":
            compile(content, str(target), "exec")
        txn = self.gw.txns.begin(ctx.agent_id, ctx.task_id, [target], ctx.session.session_id)
        ctx.session.transaction_id = txn.transaction_id
        try:
            _atomic_write(target, content, target.stat().st_mode if target.exists() else None)
            self.gw.txns.commit(txn, [target])
        except BaseException:
            self.gw.txns.rollback(txn)
            raise
        alias = ctx.session.register_alias("T", txn.transaction_id)
        return f"WRITE OK txn={txn.transaction_id} ({alias}) file={args[0]}"

    async def _rollback(self, args, ctx):
        if len(args) != 1:
            return "ERROR: usage [[ROLLBACK|Txx]]"
        txn_id = ctx.session.transaction_aliases.get(args[0], args[0])
        txn = self.gw.txns._txns.get(txn_id)
        if txn is None or txn.session_id != ctx.session.session_id or txn.task_id != ctx.task_id:
            raise PolicyDenied("transaction not found in this session/task")
        self.gw.txns.rollback(txn)
        ctx.session.transaction_id = txn.transaction_id
        return f"ROLLBACK OK txn={txn_id}"

    async def _diff(self, args, ctx):
        if len(args) > 1:
            return "ERROR: DIFF accepts one path"
        path = ctx.session.resolve_path(args[0]).relative_to(ctx.session.repository_root).as_posix() if args else ""
        return self.gw._git(ctx.session).diff(path) or "NO_DIFF"

    _git_diff = _diff

    async def _status(self, args, ctx):
        if args:
            return "ERROR: STATUS accepts no arguments"
        return self.gw._git(ctx.session).status() or "CLEAN"

    _git_status = _status

    async def _branch(self, args, ctx):
        if len(args) != 1:
            return "ERROR: usage [[BRANCH|name]]"
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,100}", args[0]):
            return "ERROR: invalid branch name"
        return self.gw._git(ctx.session).branch(args[0])

    async def _checkpoint(self, args, ctx):
        if len(args) > 1:
            return "ERROR: CHECKPOINT accepts one message"
        paths = set()
        for txn in self.gw.txns._txns.values():
            if txn.session_id == ctx.session.session_id and txn.status == "COMMITTED":
                paths.update(Path(p).relative_to(ctx.session.repository_root).as_posix() for p in txn.files)
        return self.gw._git(ctx.session).checkpoint(args[0] if args else f"OMA {ctx.task_id}", sorted(paths))

    async def _next(self, args, ctx):
        if not 1 <= len(args) <= 2:
            return "ERROR: usage [[NEXT|Rxx|offset]]"
        rid = ctx.session.result_registry.get(args[0], args[0])
        offset = int(args[1]) if len(args) == 2 else None
        return self.gw.results.next_page(rid, offset, session=ctx.session)[0]

    async def _rart(self, args, ctx):
        if not args:
            return "ERROR: usage [[RART|Axx or Rxx|start|end]]"
        start, end = line_range(args)
        if args[0] in ctx.session.artifact_aliases:
            content = ctx.session.artifact_aliases[args[0]]
        else:
            rid = ctx.session.result_registry.get(args[0], args[0])
            stored = self.gw.results.get(rid, session=ctx.session)
            if stored is None:
                return "ERROR: artifact not found in this session"
            content = "\n".join(stored.lines)
        self.gw.artifact_reuse += 1
        return "\n".join(content.splitlines()[start - 1:end])
