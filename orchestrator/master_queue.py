"""Project queue over IntegratedRun: atomic claims, frozen budgets, final inbox.

SQLite/checkpoint patterns were studied in Auxiliares; this is an original,
stdlib-only implementation. No model directive can enqueue, acknowledge or promote.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from .central_exchange import canonical, digest, verified_handoff
from .scale_gates import evaluate_scale


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}", value):
        raise ValueError("queue IDs require 1..60 letters, digits, underscores or hyphens")
    return value


def positive(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer 1..{maximum}")
    return value


def frozen_config(config):
    data = deepcopy(config)
    # Persist references to credentials, never credentials/browser storage paths.
    data["browser"] = {k: v for k, v in data.get("browser", {}).items()
                       if k in {"relay_base", "timeout_seconds"}}
    data["routing"] = {k: v for k, v in data.get("routing", {}).items()
                       if k in {"worker", "reviewer", "fallback", "roles", "openai_model", "openai_key_env"}}
    local = data.get("local_model", {})
    if local.get("api_key") not in (None, "local"):
        raise ValueError("use local_model.api_key_env; secrets cannot enter MASTER_QUEUE")
    local.pop("api_key", None)
    allowed = {"browser", "local_model", "routing", "validation", "oma", "orchestrator",
               "default_acceptance_criteria"}
    return {k: v for k, v in data.items() if k in allowed}


def control_fingerprint(config):
    from .agents.contracts import VERSION
    root = Path(__file__).parent
    sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
               ("engine.py", "quality_gate.py", "configuration.py", "master_queue.py",
                "scale_gates.py", "conversation_pool.py", "agents/contracts.py", "agents/master.py")}
    comparable = deepcopy(config)
    comparable.get("oma", {}).pop("max_seats", None)
    comparable.get("oma", {}).get("compute_policy", {}).pop("max_agents", None)
    return digest({"source": sources, "config": comparable, "prompts": VERSION})


class MasterQueue:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve(strict=True)
        self.root = self.workspace / ".oma" / "master-queue"
        for path in (self.workspace / ".oma", self.root):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("queue storage cannot be a filesystem link")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "queue.sqlite3"
        if self.db.is_symlink():
            raise ValueError("queue database cannot be a symlink")
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, spec TEXT NOT NULL, config TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    result TEXT, measurement TEXT);
                CREATE TABLE IF NOT EXISTS inbox (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id), digest TEXT NOT NULL,
                    context TEXT NOT NULL, imported REAL NOT NULL, acknowledged REAL,
                    consumer TEXT);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, manifest, config):
        """All-or-nothing import; reimport is idempotent, never resets budgets."""
        from .configuration import engine_options
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("jobs"), list):
            raise ValueError("MASTER_QUEUE schema_version=1 and jobs list required")
        limits = manifest.get("limits", {})
        positive(limits.get("total_tokens"), "queue total_tokens", 100_000_000)
        positive(limits.get("total_seconds"), "queue total_seconds", 86400 * 7)
        frozen = frozen_config(config)
        engine_options(frozen)  # operator config must be valid before admission
        specs = {}
        for item in manifest["jobs"]:
            spec = deepcopy(item)
            key = identifier(spec.get("id"))
            if key in specs or not isinstance(spec.get("objective"), str) or not spec["objective"].strip():
                raise ValueError("duplicate job or missing objective")
            if len(spec["objective"]) > 12000:
                raise ValueError("objective exceeds context budget")
            spec.setdefault("depends_on", [])
            if (not isinstance(spec["depends_on"], list) or key in spec["depends_on"]
                    or len(set(spec["depends_on"])) != len(spec["depends_on"])):
                raise ValueError("invalid dependencies")
            for dep in spec["depends_on"]:
                identifier(dep)
            spec.setdefault("priority", 0)
            if type(spec["priority"]) is not int or not 0 <= spec["priority"] <= 100:
                raise ValueError("priority must be 0..100")
            spec.setdefault("agents", 6)
            evaluate_scale(spec["agents"], [], "")
            budget = spec.get("budget", {})
            for bucket in ("master", "secondary", "task"):
                positive(budget.get(bucket), bucket, 10_000_000)
            positive(budget.get("seconds"), "seconds", 3600)
            specs[key] = spec
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {row["id"]: row for row in db.execute("SELECT * FROM jobs")}
            all_specs = {key: json.loads(row["spec"]) for key, row in existing.items()} | specs
            visiting, visited = set(), set()
            def visit(key):
                if key not in all_specs or key in visiting:
                    raise ValueError("missing dependency or cycle in MASTER_QUEUE")
                if key in visited:
                    return
                visiting.add(key)
                for dep in all_specs[key]["depends_on"]:
                    visit(dep)
                visiting.remove(key)
                visited.add(key)
            for key in all_specs:
                visit(key)
            saved = db.execute("SELECT value FROM settings WHERE key='limits'").fetchone()
            if saved and json.loads(saved[0]) != limits:
                raise ValueError("queue limits are immutable; reimport cannot increase/reset them")
            token_allocation = sum(s["budget"]["master"] + s["budget"]["secondary"] for s in all_specs.values())
            time_allocation = sum(s["budget"]["seconds"] for s in all_specs.values())
            if token_allocation > limits["total_tokens"] or time_allocation > limits["total_seconds"]:
                raise ValueError("queue allocation exceeds project budget")
            for key, spec in specs.items():
                if key in existing:
                    if existing[key]["spec"] != canonical(spec) or existing[key]["config"] != canonical(frozen):
                        raise ValueError("existing job is immutable; use a new ID")
                else:
                    now = time.time()
                    db.execute("INSERT INTO jobs(id,spec,config,state,created,updated) VALUES(?,?,?,'PENDING',?,?)",
                               (key, canonical(spec), canonical(frozen), now, now))
            db.execute("INSERT OR IGNORE INTO settings VALUES('limits', ?)", (canonical(limits),))
        return self.status()

    def status(self):
        with self.connection() as db:
            rows = list(db.execute("SELECT * FROM jobs ORDER BY created,id"))
            limits = db.execute("SELECT value FROM settings WHERE key='limits'").fetchone()
        return {"limits": json.loads(limits[0]) if limits else None,
                "jobs": [{"id": r["id"], "state": r["state"], "spec": json.loads(r["spec"]),
                          "result": json.loads(r["result"]) if r["result"] else None} for r in rows],
                "recovery": "RUNNING after process death requires operator reconciliation; never auto-replayed"}

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = list(db.execute("SELECT * FROM jobs"))
            if any(r["state"] in {"RUNNING", "BLOCKED"} for r in rows):
                raise ValueError("queue blocked: unfinished/uncertain run requires operator attention")
            ready = []
            for row in rows:
                if row["state"] != "PENDING":
                    continue
                spec = json.loads(row["spec"])
                # A ready candidate or central acknowledgement does NOT mean its code exists.
                for dep in spec["depends_on"]:
                    path = self.workspace / "runs" / ("mq-" + dep) / "handoff.json"
                    if not path.exists() or json.loads(path.read_text(encoding="utf-8")).get("status") != "APPLIED":
                        break
                else:
                    ready.append((row, spec))
            if not ready:
                return None
            row, spec = min(ready, key=lambda pair: (-pair[1]["priority"], pair[0]["created"], pair[0]["id"]))
            db.execute("UPDATE jobs SET state='RUNNING',updated=? WHERE id=? AND state='PENDING'",
                       (time.time(), row["id"]))
            return spec, json.loads(row["config"])

    async def run_next(self, *, trust_workspace=False):
        from .configuration import build_router, close_router, engine_options
        from .conversation_pool import inspect_conversations
        from .runtime import IntegratedRun, RunLock
        # OS lock protects the WHOLE operation, not just the claim transaction.
        with RunLock(self.root / "worker.lock"):
            claimed = self.claim()
            if claimed is None:
                return {"status": "IDLE_OR_WAITING_FOR_DEPENDENCY_PROMOTION"}
            spec, config = claimed
            key, started = spec["id"], time.monotonic()
            router, measurement = None, None
            try:
                options = engine_options(config)
                if options["execution"]["backend"] == "host" and not trust_workspace:
                    raise ValueError("queue candidate execution requires Docker or explicit --trust-workspace")
                policy_hash = control_fingerprint(config)
                with self.connection() as db:
                    measurements = [json.loads(r[0]) for r in db.execute(
                        "SELECT measurement FROM jobs WHERE measurement IS NOT NULL")]
                gate = evaluate_scale(spec["agents"], measurements, policy_hash)
                if not gate["allowed"]:
                    raise ValueError("SCALE_GATE: " + "; ".join(gate["reasons"]))
                pool_dir = self.root / "conversations"
                pool = inspect_conversations(pool_dir, "master-queue")
                if pool["state"] not in {"ABSENT", "IDLE"}:
                    raise ValueError("persistent project conversations require reconciliation")
                budget = spec["budget"]
                options.update(token_budget_master=budget["master"], token_budget_secondary=budget["secondary"],
                    task_token_budget=budget["task"], fixed_conversations=True, max_seats=spec["agents"],
                    max_parallel_workers=1, conversation_pool_dir=pool_dir, conversation_namespace="master-queue")
                if options["compute_policy"] is not None:
                    options["compute_policy"].max_agents = spec["agents"]
                router = build_router(config)
                result = await asyncio.wait_for(IntegratedRun(self.workspace, "mq-" + key,
                    spec["objective"], router, **options).run(), timeout=budget["seconds"])
                # Do not admit another job while a previous external delivery is unresolved.
                after_pool = inspect_conversations(pool_dir, "master-queue")
                if after_pool["state"] not in {"IDLE", "ABSENT"}:
                    raise ValueError("run ended with unresolved conversation delivery")
                state = "CANDIDATE_READY" if result["status"] == "CANDIDATE_READY" else "FAILED"
                accounting = result.get("metrics", {}).get("budget_accounting", {})
                used = accounting.get("used", {})
                # Count conversations used in THIS run, not historical pool seats.
                turns = [e.get("payload", {}) for e in result.get("conversation_events", [])]
                urls = {t.get("conversation", {}).get("conversation_url") for t in turns if t.get("success")}
                urls.discard(None)
                seats = [s for s in after_pool.get("seats", {}).values() if s.get("url") in urls]
                from .providers.mock_provider import MockProvider
                live = all(not isinstance(p, MockProvider) for p in router.providers.values())
                measurement = {"run_id": result["run_id"], "created_at": time.time(),
                    "policy_hash": policy_hash, "live": live, "success": state == "CANDIDATE_READY",
                    "elapsed_s": time.monotonic() - started, "seats_observed": len(seats),
                    "identity_complete": bool(seats) and all(s.get("state") == "CONFIRMED" for s in seats),
                    "uncertain": accounting.get("accounting", {}).get("uncertain", 1),
                    "budget_overrun": any(used.get(b, budget[b] + 1) > budget[b] for b in ("master", "secondary"))}
                summary = {"status": state, "run_id": result["run_id"],
                           "handoff_path": result["handoff_path"], "budget_accounting": accounting,
                           "scale_gate": gate, "errors": result.get("errors", [])}
            except (Exception, asyncio.CancelledError) as exc:
                state = "BLOCKED"
                summary = {"status": state, "error": type(exc).__name__ + ": " + str(exc)[:500],
                           "replay_allowed": False}
                self._finish(key, state, summary, measurement)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return summary
            finally:
                if router is not None:
                    await close_router(router)
            self._finish(key, state, summary, measurement)
            if state == "CANDIDATE_READY":
                self.import_final(key)
            return summary

    def _finish(self, key, state, result, measurement):
        with self.connection() as db:
            changed = db.execute("UPDATE jobs SET state=?,result=?,measurement=?,updated=? WHERE id=? AND state='RUNNING'",
                (state, canonical(result), canonical(measurement) if measurement else None, time.time(), key)).rowcount
            if changed != 1:
                raise ValueError("queue claim lost; refusing to overwrite final state")

    def import_final(self, key):
        key = identifier(key)
        context = verified_handoff(self.workspace / "runs" / ("mq-" + key))
        checksum = digest(context)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT state FROM jobs WHERE id=?", (key,)).fetchone()
            if not job or job[0] != "CANDIDATE_READY":
                raise ValueError("job has no final candidate to import")
            old = db.execute("SELECT digest FROM inbox WHERE job_id=?", (key,)).fetchone()
            if old and old[0] != checksum:
                raise ValueError("imported candidate changed; refuse context overwrite")
            db.execute("INSERT OR IGNORE INTO inbox(job_id,digest,context,imported) VALUES(?,?,?,?)",
                       (key, checksum, canonical(context), time.time()))
        return {"job_id": key, "digest": checksum, "delivery": "LOCAL_INBOX"}

    def inbox(self):
        with self.connection() as db:
            return [{"job_id": r["job_id"], "digest": r["digest"], "context": json.loads(r["context"]),
                     "acknowledged": r["acknowledged"], "consumer": r["consumer"]}
                    for r in db.execute("SELECT * FROM inbox ORDER BY imported")]

    def acknowledge(self, key, checksum, consumer):
        identifier(key)
        identifier(consumer)
        with self.connection() as db:
            row = db.execute("SELECT * FROM inbox WHERE job_id=? AND digest=?", (key, checksum)).fetchone()
            if row is None or (row["consumer"] is not None and row["consumer"] != consumer):
                raise ValueError("acknowledgement must name the exact imported context and consumer")
            db.execute("UPDATE inbox SET acknowledged=COALESCE(acknowledged,?),consumer=? WHERE job_id=?",
                       (time.time(), consumer, key))
        return {"job_id": key, "acknowledged": True, "promoted": False}

    def abandon(self, key, reason):
        """Explicit operator closure, never a replay or refund of allocations."""
        from .runtime import RunLock
        identifier(key)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError("operator reason (1..1000 characters) required")
        with RunLock(self.root / "worker.lock"), self.connection() as db:
            row = db.execute("SELECT state,result FROM jobs WHERE id=?", (key,)).fetchone()
            if row is None or row["state"] not in {"RUNNING", "BLOCKED", "PENDING"}:
                raise ValueError("only unfinished jobs may be explicitly abandoned")
            record = {"status": "FAILED", "abandoned_by_operator": True, "reason": reason,
                      "previous_state": row["state"], "previous_result": json.loads(row["result"]) if row["result"] else None,
                      "replay_allowed": False, "allocation_refunded": False}
            db.execute("UPDATE jobs SET state='FAILED',result=?,updated=? WHERE id=?",
                       (canonical(record), time.time(), key))
        return record
