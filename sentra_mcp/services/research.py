"""Bounded temporary-chat research orchestration over SENTRA Edge workers."""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from ..audit import AuditLogger
from ..config import MCPConfig
from .browser import BrowserControlService

_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}


def _bounded(text: str, limit: int = 12000) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "\n[TRUNCATED]"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


class ResearchService:
    """Run bounded subagent research using fresh ChatGPT relay conversations.

    The mcts strategy is explicitly a bounded MCTS-inspired beam search:
    independent branches are expanded, a separate judge selects the beam, and
    surviving paths are expanded again. It is not a claim of full UCT/MCTS.
    """

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        browser: BrowserControlService,
        *,
        durable: object | None = None,
        control_plane: object | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.browser = browser
        self.durable = durable
        self.control_plane = control_plane
        self.db_path = Path(
            db_path or (config.state_root / "research.sqlite3")
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.done: dict[str, asyncio.Event] = {}
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_runs(
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                objective TEXT NOT NULL,
                strategy TEXT NOT NULL,
                temporary INTEGER NOT NULL,
                branches INTEGER NOT NULL,
                max_depth INTEGER NOT NULL,
                beam_width INTEGER NOT NULL,
                operation_id TEXT,
                idempotency_key TEXT,
                state TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_research_owner_created
                ON research_runs(owner, created DESC);
            """
        )
        existing_columns = {
            str(row["name"])
            for row in self.db.execute("PRAGMA table_info(research_runs)").fetchall()
        }
        for column in ("operation_id", "idempotency_key"):
            if column not in existing_columns:
                self.db.execute(
                    f"ALTER TABLE research_runs ADD COLUMN {column} TEXT"
                )
        self.db.execute(
            "UPDATE research_runs SET state='INTERRUPTED',"
            "error='server restarted during research',updated=? "
            "WHERE state IN ('PENDING','RUNNING','CANCELLING')",
            (time.time(),),
        )
        self.db.commit()
        self.closed = False

    def update_config(self, config: MCPConfig) -> None:
        self.config = config

    def _set(
        self,
        run_id: str,
        state: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        payload = json.dumps(result, ensure_ascii=False) if result is not None else None
        if payload and len(payload.encode("utf-8")) > self.config.max_output_bytes:
            compact = dict(result or {})
            compact["nodes"] = [
                {
                    **{key: value for key, value in node.items() if key != "text"},
                    "text": _bounded(node.get("text", ""), 4000),
                }
                for node in compact.get("nodes", [])
            ]
            if "answer" in compact:
                compact["answer"] = _bounded(
                    compact["answer"],
                    max(4000, self.config.max_output_bytes // 2),
                )
            compact["output_truncated"] = True
            payload = json.dumps(compact, ensure_ascii=False)

        now = time.time()
        self.db.execute(
            "UPDATE research_runs SET state=?,result_json=?,error=?,updated=? WHERE id=?",
            (state, payload, error, now, run_id),
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT owner,operation_id FROM research_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if self.durable is not None and row is not None and row["operation_id"]:
            mapped = {
                "PENDING": "QUEUED",
                "RUNNING": "RUNNING",
                "CANCELLING": "CANCEL_REQUESTED",
                "COMPLETED": "SUCCEEDED",
                "FAILED": "FAILED",
                "CANCELLED": "CANCELLED",
                "INTERRUPTED": "UNCERTAIN",
            }.get(state)
            if mapped is not None:
                try:
                    self.durable.update_operation(
                        str(row["operation_id"]),
                        str(row["owner"]),
                        state=mapped,
                        readiness="PRODUCT_READY" if mapped == "SUCCEEDED" else None,
                        progress={
                            "stage": state,
                            "research_run_id": run_id,
                            "updated_at": now,
                        },
                        event_type=f"RESEARCH_{state}",
                        result=(
                            json.loads(payload)
                            if mapped == "SUCCEEDED" and payload
                            else None
                        ),
                        error=(
                            {
                                "code": (
                                    "RESEARCH_INTERRUPTED"
                                    if mapped == "UNCERTAIN"
                                    else "RESEARCH_FAILED"
                                ),
                                "message": str(error or "")[:1000],
                            }
                            if mapped in {"FAILED", "UNCERTAIN"} else None
                        ),
                    )
                except Exception:
                    pass
        event = self.done.get(run_id)
        if state in _TERMINAL and event is not None:
            event.set()

    async def _chat_start_retry(
        self,
        owner: str,
        prompt: str,
        *,
        timeout_s: int,
        availability_timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + availability_timeout_s
        while True:
            try:
                return await self.browser.chat_start(
                    owner,
                    prompt,
                    timeout_s=min(timeout_s, 120),
                )
            except RuntimeError as exc:
                if (
                    "no READY Edge worker" not in str(exc)
                    or time.monotonic() >= deadline
                ):
                    raise
                await asyncio.sleep(0.25)

    async def _chat_collect_retry(
        self,
        owner: str,
        conversation_url: str,
        *,
        timeout_s: int,
        availability_timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + availability_timeout_s
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self.browser.chat_collect(
                    owner,
                    conversation_url,
                    timeout_s=timeout_s,
                )
            except RuntimeError as exc:
                message = str(exc)
                lowered = message.casefold()
                transient = (
                    "no READY Edge worker" in message
                    or "back/forward cache" in lowered
                    or "message channel is closed" in lowered
                    or "receiving end does not exist" in lowered
                    or "could not establish connection" in lowered
                    or "content-script não respondeu" in lowered
                    or "content-script nao respondeu" in lowered
                )
                if not transient or time.monotonic() >= deadline:
                    raise
                # CHAT_COLLECT is read-only/idempotent by explicit conversation URL.
                # Retrying it cannot resend a prompt or duplicate a generation.
                await asyncio.sleep(min(1.0, 0.25 * attempt))

    async def _chat_retry(
        self,
        owner: str,
        prompt: str,
        *,
        timeout_s: int,
        availability_timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        started = await self._chat_start_retry(
            owner,
            prompt,
            timeout_s=timeout_s,
            availability_timeout_s=availability_timeout_s,
        )
        url = str(started.get("conversation_url") or "")
        if not url:
            raise RuntimeError("CHAT_START returned no conversation_url")
        return await self._chat_collect_retry(
            owner,
            url,
            timeout_s=timeout_s,
            availability_timeout_s=availability_timeout_s,
        )

    async def _parallel_chat_batch(
        self,
        owner: str,
        prompts: list[str],
        *,
        timeout_s: int,
    ) -> list[dict[str, Any]]:
        """Start every branch first, then collect by conversation id.

        Only one controller tab is required. Each generation continues
        server-side after CHAT_START, so logical parallelism does not require
        one browser tab per subagent.
        """
        started: list[dict[str, Any]] = []
        for prompt in prompts:
            started.append(
                await self._chat_start_retry(
                    owner,
                    prompt,
                    timeout_s=timeout_s,
                )
            )

        results: list[dict[str, Any]] = []
        for item in started:
            url = str(item.get("conversation_url") or "")
            if not url:
                raise RuntimeError("CHAT_START returned no conversation_url")
            collected = await self._chat_collect_retry(
                owner,
                url,
                timeout_s=timeout_s,
            )
            collected.setdefault("conversation_url", url)
            collected.setdefault("conversation_id", item.get("conversation_id"))
            results.append(collected)
        return results

    async def _delete_chat_retry(
        self,
        owner: str,
        conversation_url: str,
        *,
        availability_timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        """Delete a temporary chat, tolerating transient READY-worker gaps."""
        deadline = time.monotonic() + availability_timeout_s
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await self.browser.delete_chat(
                    owner,
                    conversation_url,
                    timeout_s=45,
                )
                return {
                    "conversation_url": conversation_url,
                    "deleted": True,
                    "attempts": attempt,
                    "result": result,
                }
            except RuntimeError as exc:
                transient = "no READY Edge worker" in str(exc)
                if not transient or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(min(1.0, 0.25 * attempt))

    async def _cleanup_chats(
        self,
        owner: str,
        urls: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        unique = list(dict.fromkeys(url for url in urls if url))
        for url in unique:
            try:
                item = await self._delete_chat_retry(owner, url)
            except Exception as exc:
                results.append(
                    {
                        "conversation_url": url,
                        "deleted": False,
                        "error": str(exc)[:500],
                    }
                )
            else:
                results.append(item)
        return results

    def _bind_research_chat(
        self,
        run_id: str,
        owner: str,
        *,
        node_id: str,
        role: str,
        conversation_id: str | None,
        conversation_url: str | None,
    ) -> tuple[str | None, str | None]:
        if self.durable is None:
            return None, None
        safe_run = "".join(ch for ch in run_id if ch.isalnum() or ch in "_.:-")[-40:]
        safe_node = "".join(ch for ch in node_id if ch.isalnum() or ch in "_.:-")[:40]
        agent_id = f"agent-{safe_run}-{safe_node}"
        chat_id = f"chat-{safe_run}-{safe_node}"
        agent = self.durable.assign_agent(
            run_id,
            owner,
            role=role,
            task_id=f"research:{node_id}",
            agent_id=agent_id,
            state="ACTIVE",
            desired_state="ACTIVE",
            metadata={"research_node_id": node_id},
        )
        chat = self.durable.bind_chat(
            run_id,
            owner,
            agent_id=agent["agent_id"],
            provider="chatgpt",
            conversation_id=str(conversation_id) if conversation_id else None,
            conversation_url=str(conversation_url) if conversation_url else None,
            title=f"[SENTRA] {node_id} - {role}",
            chat_id=chat_id,
            state="READY",
            desired_state="READY",
            metadata={"research_node_id": node_id},
        )
        return str(agent["agent_id"]), str(chat["chat_id"])

    async def _parallel(
        self,
        run_id: str,
        objective: str,
        owner: str,
        branches: int,
        timeout_s: int,
        urls: list[str],
    ) -> tuple[list[dict[str, Any]], str]:
        roles = [
            "evidence-focused researcher",
            "skeptical adversarial reviewer",
            "implementation and practicality researcher",
            "alternative-hypothesis researcher",
        ]
        prompts = [
            (
                f"You are independent subagent {index + 1}/{branches}, acting as a "
                f"{roles[index % len(roles)]}.\n\n"
                f"Research objective:\n{objective}\n\n"
                "Work independently. State concrete evidence, assumptions, uncertainties, "
                "failure modes, and what another agent should verify. Do not coordinate "
                "with the other branches and do not merely restate the objective."
            )
            for index in range(branches)
        ]
        raw = await self._parallel_chat_batch(
            owner,
            prompts,
            timeout_s=timeout_s,
        )
        nodes: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            url = item.get("conversation_url")
            if url:
                urls.append(str(url))
            node = {
                "id": f"branch-{index + 1}",
                "depth": 1,
                "kind": "branch",
                "role": roles[index % len(roles)],
                "text": str(item.get("text") or ""),
                "conversation_url": url,
                "conversation_id": item.get("conversation_id"),
            }
            agent_id, chat_id = self._bind_research_chat(
                run_id,
                owner,
                node_id=node["id"],
                role=node["role"],
                conversation_id=node["conversation_id"],
                conversation_url=node["conversation_url"],
            )
            node["agent_id"] = agent_id
            node["chat_id"] = chat_id
            if self.control_plane is not None:
                published = self.control_plane.publish_context(
                    run_id,
                    owner,
                    event_type="RESULT",
                    subject=f"research.branch.{index + 1}",
                    payload={
                        "node_id": node["id"],
                        "role": node["role"],
                        "text": node["text"],
                        "conversation_id": node["conversation_id"],
                        "conversation_url": node["conversation_url"],
                    },
                    evidence=[],
                    confidence=None,
                    supersedes=[],
                    task_id=f"research:{node['id']}",
                    agent_id=agent_id,
                    idempotency_key=f"research-branch-{index + 1}",
                )
                node["context_event_id"] = published["event_id"]
            nodes.append(node)

        shared_nodes = nodes
        if self.control_plane is not None:
            shared = self.control_plane.read_context(
                run_id,
                owner,
                after_seq=0,
                types=["RESULT"],
                subject_prefixes=["research.branch."],
                limit=max(1, branches),
            )
            by_id = {
                str(item.get("payload", {}).get("node_id")): item
                for item in shared.get("items", [])
            }
            shared_nodes = []
            for node in nodes:
                event = by_id.get(node["id"])
                payload = event.get("payload", {}) if event else {}
                shared_nodes.append({
                    **node,
                    "text": str(payload.get("text") or node["text"]),
                    "role": str(payload.get("role") or node["role"]),
                })

        synthesis_prompt = (
            "Act as the master research synthesizer. Reconcile the independent "
            "branches below. Separate agreement, disagreement, evidence gaps, and "
            "uncertainty. Produce a concrete integrated answer rather than concatenating "
            "the branch outputs.\n\nOBJECTIVE:\n"
            + objective
            + "\n\nSHARED CONTEXT BRANCH RESULTS:\n"
            + "\n\n".join(
                f"[{node['id']} | {node.get('role', 'agent')}]\n{_bounded(node['text'])}"
                for node in shared_nodes
            )
        )
        synthesis = await self._chat_retry(
            owner,
            synthesis_prompt,
            timeout_s=timeout_s,
        )
        url = synthesis.get("conversation_url")
        if url:
            urls.append(str(url))
        synthesis_node = {
            "id": "synthesis",
            "depth": 2,
            "kind": "synthesis",
            "role": "master research synthesizer",
            "text": str(synthesis.get("text") or ""),
            "conversation_url": url,
            "conversation_id": synthesis.get("conversation_id"),
        }
        synthesis_agent_id, synthesis_chat_id = self._bind_research_chat(
            run_id,
            owner,
            node_id="synthesis",
            role=synthesis_node["role"],
            conversation_id=synthesis_node["conversation_id"],
            conversation_url=synthesis_node["conversation_url"],
        )
        synthesis_node["agent_id"] = synthesis_agent_id
        synthesis_node["chat_id"] = synthesis_chat_id
        if self.control_plane is not None:
            published = self.control_plane.publish_context(
                run_id,
                owner,
                event_type="DECISION",
                subject="research.synthesis",
                payload={
                    "node_id": "synthesis",
                    "text": synthesis_node["text"],
                    "conversation_id": synthesis_node["conversation_id"],
                    "conversation_url": synthesis_node["conversation_url"],
                },
                evidence=[
                    str(node["context_event_id"])
                    for node in nodes
                    if node.get("context_event_id")
                ],
                confidence=None,
                supersedes=[],
                task_id="research:synthesis",
                agent_id=synthesis_agent_id,
                idempotency_key="research-synthesis",
            )
            synthesis_node["context_event_id"] = published["event_id"]
        nodes.append(synthesis_node)
        return nodes, str(synthesis.get("text") or "")

    async def _mcts(
        self,
        objective: str,
        owner: str,
        branches: int,
        max_depth: int,
        beam_width: int,
        timeout_s: int,
        urls: list[str],
    ) -> tuple[list[dict[str, Any]], str]:
        nodes: list[dict[str, Any]] = []
        active: list[dict[str, Any]] = [{"id": "root", "text": objective}]
        node_counter = 0

        for depth in range(1, max_depth + 1):
            prompts: list[str] = []
            parents: list[dict[str, Any]] = []
            for index in range(branches):
                parent = active[index % len(active)]
                parents.append(parent)
                prompts.append(
                    "Explore one distinct research path for the objective below. Treat "
                    "the parent path as context, but actively search for a better, competing, "
                    "or falsifying explanation. Return evidence, weaknesses, next checks, "
                    "and a concise candidate conclusion.\n\n"
                    f"OBJECTIVE:\n{objective}\n\n"
                    f"PARENT PATH:\n{_bounded(parent['text'], 10000)}\n\n"
                    f"DEPTH: {depth}; VARIANT: {index + 1}/{branches}"
                )

            outputs = await self._parallel_chat_batch(
                owner,
                prompts,
                timeout_s=timeout_s,
            )

            candidates: list[dict[str, Any]] = []
            for parent, item in zip(parents, outputs):
                node_counter += 1
                url = item.get("conversation_url")
                if url:
                    urls.append(str(url))
                node = {
                    "id": f"node-{node_counter}",
                    "parent": parent["id"],
                    "depth": depth,
                    "kind": "branch",
                    "text": str(item.get("text") or ""),
                    "conversation_url": url,
                    "conversation_id": item.get("conversation_id"),
                }
                nodes.append(node)
                candidates.append(node)

            select_count = min(beam_width, len(candidates))
            judge_prompt = (
                "You are a research tree judge. Select the strongest candidate paths "
                "for further expansion. Return STRICT JSON only in this shape: "
                "{\"selected\":[0,1],\"reason\":\"...\"}. "
                f"Select exactly {select_count} distinct zero-based indices. "
                "Prefer evidential strength, novelty, falsifiability, and relevance; "
                "do not reward confidence alone.\n\n"
                f"OBJECTIVE:\n{objective}\n\nCANDIDATES:\n"
                + "\n\n".join(
                    f"INDEX {idx}\n{_bounded(node['text'], 7000)}"
                    for idx, node in enumerate(candidates)
                )
            )
            judge = await self._chat_retry(
                owner,
                judge_prompt,
                timeout_s=timeout_s,
            )
            judge_url = judge.get("conversation_url")
            if judge_url:
                urls.append(str(judge_url))
            parsed = _extract_json_object(str(judge.get("text") or "")) or {}
            selected = parsed.get("selected")
            valid: list[int] = []
            if isinstance(selected, list):
                for value in selected:
                    if (
                        isinstance(value, int)
                        and 0 <= value < len(candidates)
                        and value not in valid
                    ):
                        valid.append(value)
                    if len(valid) >= select_count:
                        break
            if len(valid) < select_count:
                for index in range(len(candidates)):
                    if index not in valid:
                        valid.append(index)
                    if len(valid) >= select_count:
                        break
            active = [candidates[index] for index in valid]
            for node in active:
                node["selected"] = True
            nodes.append(
                {
                    "id": f"judge-depth-{depth}",
                    "depth": depth,
                    "kind": "judge",
                    "text": str(judge.get("text") or ""),
                    "selected_indices": valid,
                    "conversation_url": judge_url,
                    "conversation_id": judge.get("conversation_id"),
                }
            )

        final_prompt = (
            "Synthesize the final research result from the surviving paths of a "
            "bounded MCTS-inspired beam search. Explicitly state uncertainty, unresolved "
            "conflicts, strongest evidence, and concrete next steps.\n\n"
            f"OBJECTIVE:\n{objective}\n\nSURVIVING PATHS:\n"
            + "\n\n".join(
                f"[{node['id']}]\n{_bounded(node['text'], 12000)}"
                for node in active
            )
        )
        final = await self._chat_retry(
            owner,
            final_prompt,
            timeout_s=timeout_s,
        )
        final_url = final.get("conversation_url")
        if final_url:
            urls.append(str(final_url))
        nodes.append(
            {
                "id": "final-synthesis",
                "depth": max_depth + 1,
                "kind": "synthesis",
                "text": str(final.get("text") or ""),
                "conversation_url": final_url,
                "conversation_id": final.get("conversation_id"),
            }
        )
        return nodes, str(final.get("text") or "")

    async def _run(
        self,
        run_id: str,
        *,
        owner: str,
        objective: str,
        strategy: str,
        temporary: bool,
        branches: int,
        max_depth: int,
        beam_width: int,
        timeout_s: int,
    ) -> None:
        urls: list[str] = []
        cleanup: list[dict[str, Any]] = []
        self._set(run_id, "RUNNING")
        try:
            if strategy == "single":
                item = await self._chat_retry(
                    owner,
                    objective,
                    timeout_s=timeout_s,
                )
                url = item.get("conversation_url")
                if url:
                    urls.append(str(url))
                nodes = [
                    {
                        "id": "single-1",
                        "depth": 1,
                        "kind": "branch",
                        "text": str(item.get("text") or ""),
                        "conversation_url": url,
                        "conversation_id": item.get("conversation_id"),
                    }
                ]
                answer = str(item.get("text") or "")
                algorithm = "single-temporary-chat"
            elif strategy == "parallel":
                nodes, answer = await self._parallel(
                    run_id,
                    objective,
                    owner,
                    branches,
                    timeout_s,
                    urls,
                )
                algorithm = "bounded-parallel-subagents"
            else:
                nodes, answer = await self._mcts(
                    objective,
                    owner,
                    branches,
                    max_depth,
                    beam_width,
                    timeout_s,
                    urls,
                )
                algorithm = "bounded-mcts-inspired-beam-search"

            if temporary:
                cleanup = await self._cleanup_chats(owner, urls)
            result = {
                "run_id": run_id,
                "objective": objective,
                "strategy": strategy,
                "algorithm": algorithm,
                "temporary": temporary,
                "answer": answer,
                "nodes": nodes,
                "conversations_created": len(dict.fromkeys(urls)),
                "cleanup": cleanup,
            }
            self._set(run_id, "COMPLETED", result=result)
            self.audit.emit(
                "research.complete",
                "ok",
                {
                    "run_id": run_id,
                    "owner": owner,
                    "strategy": strategy,
                    "nodes": len(nodes),
                    "temporary": temporary,
                },
            )
        except asyncio.CancelledError:
            if temporary and urls:
                try:
                    cleanup = await self._cleanup_chats(owner, urls)
                except Exception:
                    pass
            self._set(
                run_id,
                "CANCELLED",
                result={"cleanup": cleanup} if cleanup else None,
                error="research cancelled",
            )
            raise
        except Exception as exc:
            if temporary and urls:
                try:
                    cleanup = await self._cleanup_chats(owner, urls)
                except Exception:
                    pass
            self._set(
                run_id,
                "FAILED",
                result={"cleanup": cleanup} if cleanup else None,
                error=str(exc)[:4000],
            )

    async def start(
        self,
        objective: str,
        owner: str,
        *,
        strategy: str = "parallel",
        temporary: bool = True,
        branches: int = 3,
        max_depth: int = 2,
        beam_width: int = 2,
        timeout_s: int = 300,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if self.closed:
            raise RuntimeError("research service is shut down")
        if not objective or len(objective) > 100_000:
            raise ValueError("objective must be 1..100000 characters")
        strategy = strategy.strip().lower()
        if strategy not in {"single", "parallel", "mcts"}:
            raise ValueError("strategy must be single, parallel or mcts")
        if not 1 <= branches <= 4:
            raise ValueError("branches must be 1..4")
        if strategy in {"parallel", "mcts"} and branches < 2:
            raise ValueError(f"{strategy} requires at least 2 branches")
        if not 1 <= max_depth <= 3:
            raise ValueError("max_depth must be 1..3")
        if not 1 <= beam_width <= min(3, branches):
            raise ValueError("beam_width must be between 1 and min(3, branches)")
        if not 30 <= timeout_s <= 600:
            raise ValueError("timeout_s must be 30..600")

        key = str(idempotency_key or "").strip() or (
            "research:" + uuid.uuid4().hex
        )
        operation_id: str | None = None
        if self.durable is not None:
            durable_run = self.durable.create_run(
                owner,
                idempotency_key=key,
                required_capabilities=[
                    "browser.chat_start",
                    "browser.chat_collect",
                ],
            )
            run_id = str(durable_run["run_id"])
            if durable_run.get("idempotent_replay"):
                existing = self.db.execute(
                    "SELECT * FROM research_runs WHERE id=? AND owner=?",
                    (run_id, owner),
                ).fetchone()
                if existing is not None:
                    data = self._view(
                        existing,
                        include_result=existing["state"] in _TERMINAL,
                    )
                    data["idempotent_replay"] = True
                    return data
            durable_operation = self.durable.create_operation(
                run_id,
                owner,
                kind=f"research.{strategy}",
                idempotency_key=f"execute:{key}",
            )
            operation_id = str(durable_operation["operation_id"])
            try:
                self.durable.record_capabilities_used(
                    run_id,
                    owner,
                    ["browser.chat_start", "browser.chat_collect"],
                )
            except Exception:
                pass
        else:
            run_id = str(uuid.uuid4())

        now = time.time()
        self.db.execute(
            "INSERT INTO research_runs("
            "id,owner,objective,strategy,temporary,branches,max_depth,beam_width,"
            "operation_id,idempotency_key,state,created,updated) "
            "VALUES(?,?,?,?,?,?,?,?,?,?, 'PENDING',?,?)",
            (
                run_id,
                owner,
                objective,
                strategy,
                int(temporary),
                branches,
                max_depth,
                beam_width,
                operation_id,
                key,
                now,
                now,
            ),
        )
        self.db.commit()
        self.done[run_id] = asyncio.Event()
        if self.durable is not None and operation_id:
            try:
                self.durable.update_operation(
                    operation_id,
                    owner,
                    state="STARTING",
                    progress={
                        "stage": "STARTING",
                        "research_run_id": run_id,
                        "strategy": strategy,
                        "branches": branches,
                    },
                    event_type="RESEARCH_STARTING",
                )
            except Exception:
                pass
        task = asyncio.create_task(
            self._run(
                run_id,
                owner=owner,
                objective=objective,
                strategy=strategy,
                temporary=temporary,
                branches=branches,
                max_depth=max_depth,
                beam_width=beam_width,
                timeout_s=timeout_s,
            ),
            name=f"sentra-research-{run_id[:8]}",
        )
        self.tasks[run_id] = task

        def _cleanup_task(_task: asyncio.Task[Any]) -> None:
            self.tasks.pop(run_id, None)

        task.add_done_callback(_cleanup_task)
        self.audit.emit(
            "research.start",
            "ok",
            {
                "run_id": run_id,
                "operation_id": operation_id,
                "idempotency_key": key,
                "owner": owner,
                "strategy": strategy,
                "temporary": temporary,
                "branches": branches,
                "max_depth": max_depth,
                "beam_width": beam_width,
            },
        )
        return {
            "run_id": run_id,
            "operation_id": operation_id,
            "idempotency_key": key,
            "state": "PENDING",
            "strategy": strategy,
            "temporary": temporary,
            "branches": branches,
            "max_depth": max_depth,
            "beam_width": beam_width,
        }

    def _row(self, run_id: str, owner: str) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM research_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError("research run not found")
        if row["owner"] != owner:
            raise PermissionError("research run belongs to another MCP session")
        return row

    @staticmethod
    def _view(row: sqlite3.Row, include_result: bool = False) -> dict[str, Any]:
        data = {
            "run_id": row["id"],
            "operation_id": row["operation_id"],
            "idempotency_key": row["idempotency_key"],
            "strategy": row["strategy"],
            "temporary": bool(row["temporary"]),
            "branches": row["branches"],
            "max_depth": row["max_depth"],
            "beam_width": row["beam_width"],
            "state": row["state"],
            "error": row["error"],
            "created": row["created"],
            "updated": row["updated"],
        }
        if include_result:
            data["result"] = (
                json.loads(row["result_json"]) if row["result_json"] else None
            )
        return data

    def status(self, run_id: str, owner: str) -> dict[str, Any]:
        return self._view(self._row(run_id, owner))

    def result(self, run_id: str, owner: str) -> dict[str, Any]:
        row = self._row(run_id, owner)
        if row["state"] not in _TERMINAL:
            raise RuntimeError("research run is not finished")
        return self._view(row, True)

    async def wait(
        self,
        run_id: str,
        owner: str,
        timeout_s: float = 5.0,
    ) -> dict[str, Any]:
        if not 0 < timeout_s <= 25:
            raise ValueError("timeout_s must be >0 and <=25")
        row = self._row(run_id, owner)
        if row["state"] in _TERMINAL:
            data = self._view(row, True)
            data["timed_out"] = False
            data["next_poll_after_ms"] = None
            return data

        event = self.done.setdefault(run_id, asyncio.Event())
        timed_out = False
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except TimeoutError:
            timed_out = True
        row = self._row(run_id, owner)
        data = self._view(row, row["state"] in _TERMINAL)
        data["timed_out"] = timed_out and row["state"] not in _TERMINAL
        data["next_poll_after_ms"] = (
            500 if row["state"] not in _TERMINAL else None
        )
        if data["timed_out"]:
            data["semantic_status"] = "OPERATION_STILL_RUNNING"
        return data

    def cancel(self, run_id: str, owner: str) -> dict[str, Any]:
        row = self._row(run_id, owner)
        if row["state"] in _TERMINAL:
            return self._view(row)
        self.db.execute(
            "UPDATE research_runs SET state='CANCELLING',updated=? WHERE id=?",
            (time.time(), run_id),
        )
        self.db.commit()
        task = self.tasks.get(run_id)
        if task is not None:
            task.cancel()
        if self.durable is not None and row["operation_id"]:
            try:
                self.durable.request_cancel(
                    str(row["operation_id"]),
                    owner,
                    side_effect_may_have_started=True,
                )
            except Exception:
                pass
        return {
            "run_id": run_id,
            "operation_id": row["operation_id"],
            "state": "CANCELLING",
        }

    def list_runs(
        self,
        owner: str,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be >=0 and limit must be 1..1000")
        total = int(self.db.execute(
            "SELECT COUNT(*) FROM research_runs WHERE owner=?",
            (owner,),
        ).fetchone()[0])
        rows = self.db.execute(
            "SELECT * FROM research_runs WHERE owner=? "
            "ORDER BY created DESC LIMIT ? OFFSET ?",
            (owner, limit, offset),
        ).fetchall()
        items = [self._view(row) for row in rows]
        next_offset = offset + len(items)
        return {
            "items": items,
            "runs": items,
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "total": total,
                "next_offset": next_offset if next_offset < total else None,
            },
        }

    async def close(self) -> None:
        self.closed = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.db.close()
