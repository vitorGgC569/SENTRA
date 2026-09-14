"""Run-scoped persistent seats, durable delivery and pacing of every provider round.

Master also plans/judges; executor also repairs. Validators stay independent.
Logical dialogues (including gateway exchanges) are serialized. An interrupted
send blocks the pool: restarting is not authorization to replay a prompt.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
import time
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from .providers.base import AgentResponse

_URL = re.compile(r"https://chatgpt\.com/c/([A-Za-z0-9-]{1,128})")
_ALIASES = {"planner": "master", "judge": "master", "repair": "executor"}
_ROLES = {"master", "executor", "validator.logic", "validator.requirements",
          "validator.adversarial", "validator.edge_cases", "validator.security",
          "validator.performance"}
_BLOCKING = {"IN_FLIGHT", "UNCERTAIN", "BLOCKED"}


class FixedConversationRouter:
    FILENAME = "conversations.json"

    def __init__(self, inner, run_id: str, store_dir=None,
                 inter_call_delay_s: float = 0.0, max_seats: int = 8):
        self._inner, self._run_id = inner, run_id
        self._delay = float(inter_call_delay_s)
        if not math.isfinite(self._delay) or not 0 <= self._delay <= 600:
            raise ValueError("inter_call_delay_s must be finite and 0..600")
        if type(max_seats) is not int or max_seats < 1:
            raise ValueError("max_seats must be a positive integer")
        self._max_seats = min(max_seats, len(_ROLES))
        self._map, self._last_dispatch = {}, 0.0
        self._fatal_error = None
        self._lock = asyncio.Lock()
        self._path = Path(store_dir) / self.FILENAME if store_dir else None
        self._load()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)

    def _seat(self, role):
        role = _ALIASES.get(role, role)
        if role not in _ROLES:
            raise ValueError(f"unknown fixed conversation role: {role}")
        return f"{self._run_id}:{role}"

    def _load(self):
        if not self._path or not self._path.exists():
            return
        if self._path.is_symlink():
            raise ValueError("conversation state cannot be a symlink")
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("conversation state must be an object")
            if "schema_version" in data:
                if data["schema_version"] != 2 or data.get("run_id") != self._run_id:
                    raise ValueError("conversation schema/run mismatch")
                raw, last = data["seats"], data["last_dispatch_at"]
            else:
                raw, last = data, 0.0
            if (not isinstance(raw, dict) or type(last) not in (int, float)
                    or not math.isfinite(last) or last < 0):
                raise ValueError("invalid conversation seats/dispatch timestamp")
            mapping, urls = {}, {}
            for key, value in raw.items():
                prefix = f"{self._run_id}:"
                if not key.startswith(prefix) or not isinstance(value, dict):
                    raise ValueError("invalid entry or conversation from another run")
                seat = self._seat(key[len(prefix):])
                entry = dict(value)
                if entry.get("provider") is not None and not isinstance(entry["provider"], str):
                    raise ValueError("invalid conversation provider")
                url = entry.get("url")
                match = _URL.fullmatch(url) if isinstance(url, str) else None
                if url is not None and (not match or match[1] != entry.get("conversation_id")):
                    raise ValueError("invalid conversation URL/identity")
                state = entry.setdefault("state", "CONFIRMED" if url else "NOT_SENT")
                if state not in _BLOCKING | {"CONFIRMED", "NOT_SENT"}:
                    raise ValueError("invalid conversation delivery state")
                if state == "CONFIRMED" and not url:
                    raise ValueError("confirmed conversation has no URL")
                if seat in mapping and mapping[seat] != entry:
                    raise ValueError(f"ambiguous legacy seats for {seat}; operator reconciliation required")
                if url and url in urls and urls[url] != seat:
                    raise ValueError("independent seats cannot share a conversation")
                if url:
                    urls[url] = seat
                mapping[seat] = entry
            if len(mapping) > self._max_seats:
                raise ValueError("persisted conversation count exceeds seat cap")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid conversation state: {exc}; no chat may be opened") from exc
        self._map, self._last_dispatch = mapping, float(last)

    def _save(self):
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_symlink():
            raise ValueError("conversation state cannot be a symlink")
        fd, temporary = tempfile.mkstemp(prefix=".conversations-", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"schema_version": 2, "run_id": self._run_id,
                           "last_dispatch_at": self._last_dispatch, "seats": self._map}, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _blocked(reason, state="BLOCKED"):
        return AgentResponse(content="", success=False, error=f"[CONVERSATION_BLOCKED] {reason}",
                             metadata={"delivery_state": state, "retry_safe": False})

    async def execute(self, request, preferred_provider=None):
        async with self._lock:
            try:
                if self._fatal_error:
                    return self._blocked(self._fatal_error)
                seat = self._seat(request.role)
                if self._path:
                    from .runtime import RunLock
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    process_lock = RunLock(self._path.with_suffix(".lock"))
                else:
                    process_lock = nullcontext()
                with process_lock:
                    # Reload under the OS lock: another instance may have advanced.
                    self._load()
                    # Bloqueio POR ASSENTO (não global): um envio incerto trava
                    # apenas seu próprio assento; os demais seguem. Travar a run
                    # inteira por 1 tab converte soluço local em stall total —
                    # o operador continua vendo todos via inspect_conversations.
                    mine = self._map.get(seat, {}).get("state")
                    if mine in _BLOCKING:
                        return self._blocked(f"{seat} requires delivery reconciliation; no replay")
                    if seat not in self._map and len(self._map) >= self._max_seats:
                        return self._blocked("fixed conversation seat cap reached")
                    task_boundary = json.dumps({"role": request.role, "run_id": getattr(self._inner, "run_id", None),
                                                "task_id": request.metadata.get("task_id")})
                    system = request.system_prompt + (
                        "\nOMA TASK BOUNDARY " + task_boundary +
                        "\nUse the current task and role instructions. Earlier task drafts and repository "
                        "aliases are not current evidence; request fresh repository data as needed.")
                    metadata = {**request.metadata, "conversation_key": seat, "refresh_system_prompt": True}
                    if metadata.get("messages"):
                        metadata["messages"] = [dict(m) for m in metadata["messages"]]
                        metadata["messages"][0] = {"role": "system", "content": system}
                    request = replace(request, system_prompt=system, metadata=metadata)

                    async def boundary(turn, provider, invoke):
                        return await self._round(seat, turn, provider, invoke)

                    scope = getattr(self._inner, "provider_scope", None)
                    if callable(scope):
                        with scope(boundary):
                            return await self._inner.execute(request, preferred_provider)
                    return await boundary(request, None,
                                          lambda turn: self._inner.execute(turn, preferred_provider))
            except (OSError, ValueError) as exc:
                self._fatal_error = f"conversation persistence/policy failed: {exc}"
                return self._blocked(self._fatal_error)
            except RuntimeError as exc:
                return self._blocked(str(exc))  # OS lock busy: no side effect.

    async def _round(self, seat, request, provider_name, invoke):
        known = dict(self._map.get(seat, {}))
        providers = getattr(self._inner, "providers", {})
        provider = providers.get(provider_name)
        previous = known.get("provider")
        if previous and previous != provider_name:
            old = providers.get(previous)
            if old is None or old is not provider:
                return self._blocked("a persistent seat cannot switch providers")
        metadata = {**request.metadata, "conversation_key": seat,
                    "new_chat": not bool(known.get("url"))}
        if known.get("url"):
            metadata.update(conversation_url=known["url"], conversation_id=known["conversation_id"])
            adopt = getattr(provider, "adopt_conversations", None)
            if callable(adopt):
                adopt([known["url"]])  # Only the selected provider.
        else:
            metadata.pop("conversation_url", None)
            metadata.pop("conversation_id", None)
        request = replace(request, metadata=metadata)
        # Persisted wall time carries pacing across restarts. Clock rollback
        # waits one full delay, never an unbounded interval.
        wait = min(self._delay, max(0.0, self._last_dispatch + self._delay - time.time()))
        if wait:
            await asyncio.sleep(wait)
        entry = {**known, "state": "IN_FLIGHT", "provider": provider_name,
                 "role": request.role, "task_id": metadata.get("task_id"),
                 "request_sha256": hashlib.sha256((request.system_prompt + "\0" + request.user_prompt).encode()).hexdigest(),
                 "updated": time.time()}
        self._map[seat] = entry
        self._last_dispatch = entry["updated"]
        try:
            self._save()  # Durable intent BEFORE external send.
        except (OSError, ValueError) as exc:
            self._fatal_error = f"cannot persist delivery intent: {exc}"
            return self._blocked(self._fatal_error)
        try:
            response = await invoke(request)
        except asyncio.CancelledError:
            entry["state"] = "UNCERTAIN"
            try:
                self._save()  # On process death, durable IN_FLIGHT blocks too.
            except (OSError, ValueError) as exc:
                self._fatal_error = f"cannot persist cancelled delivery: {exc}"
            raise
        except Exception as exc:
            response = self._blocked(f"provider attempt failed: {exc}", "UNCERTAIN")
        info = response.metadata or {}
        url = info.get("conversation_url")
        if response.success and url:
            match = _URL.fullmatch(url) if isinstance(url, str) else None
            if (not match or match[1] != info.get("conversation_id") or
                    (known.get("url") and known["url"] != url) or
                    any(k != seat and v.get("url") == url for k, v in self._map.items())):
                response = self._blocked("provider returned a mismatched conversation identity", "UNCERTAIN")
            else:
                entry.update(url=url, conversation_id=info["conversation_id"],
                             worker=info.get("worker", ""), state="CONFIRMED")
        elif response.success and (known.get("url") or getattr(provider, "persistent_conversations", False)):
            response = self._blocked("persistent provider returned no conversation URL", "UNCERTAIN")
        elif response.success:
            self._map.pop(seat, None)  # Stateless providers have no remote chat.
        if not response.success:
            state = response.metadata.get("delivery_state", "UNCERTAIN")
            entry["state"] = state if state in {"NOT_SENT", "BLOCKED"} else "UNCERTAIN"
            # Failure is not permission to open another chat in a fallback.
            response.metadata.update(delivery_state=entry["state"], retry_safe=False)
        # Cooldown after completion is deliberately conservative: time spent
        # fsync'ing the intent cannot shorten the actual inter-send interval.
        self._last_dispatch = time.time()
        entry["updated"] = self._last_dispatch
        try:
            self._save()  # Every round, before gateway work or budget settlement.
        except (OSError, ValueError) as exc:
            self._fatal_error = f"cannot persist delivery result: {exc}"
            return self._blocked(self._fatal_error, "UNCERTAIN")
        return response

    def seats(self):
        return deepcopy(self._map)


def inspect_conversations(store_dir, run_id):
    """Read-only operator diagnostic. Does not adopt, migrate, lock or send."""
    path = Path(store_dir) / FixedConversationRouter.FILENAME
    if not path.exists():
        return {"state": "ABSENT", "path": str(path)}
    try:
        pool = FixedConversationRouter(None, run_id, store_dir)
    except (OSError, ValueError) as exc:
        return {"state": "INVALID", "path": str(path), "error": str(exc)}
    seats = pool.seats()
    blocked = [key for key, value in seats.items() if value.get("state") in _BLOCKING]
    return {"state": "BLOCKED" if blocked else "IDLE", "path": str(path),
            "seat_count": len(seats), "blocked_seats": blocked, "seats": seats,
            "scope": "run", "note": "IDLE is local state, not proof of browser readiness or quota."}
