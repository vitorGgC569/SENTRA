"""Persistent human-facing SENTRA conversations backed only by real runtime data."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .product import (
    ProductPaths,
    ProductSettings,
    collect_product_status,
    enqueue_task,
    git_diff,
    list_recent_jobs,
    list_tasks,
    tail_audit,
)

_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "BLOCKED"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _safe_title(text: str) -> str:
    clean = " ".join(text.strip().split())
    return clean[:72] if clean else "Nova conversa"


def _tail_text(path: Path, max_bytes: int = 48 * 1024) -> str:
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, 2)
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _head_text(path: Path, max_bytes: int = 512 * 1024) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
        suffix = "\n… [truncado]" if len(data) > max_bytes else ""
        return data[:max_bytes].decode("utf-8", errors="replace") + suffix
    except OSError:
        return ""


class HumanStore:
    def __init__(self, paths: ProductPaths, settings: ProductSettings | None = None) -> None:
        self.paths = paths
        self.settings = settings or ProductSettings.load(paths.settings)
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.paths.state_dir / "human.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        db = self._connect()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                title TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_human_conversations_updated
                ON conversations(archived, updated DESC);
            CREATE TABLE IF NOT EXISTS messages(
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                kind TEXT NOT NULL,
                body TEXT NOT NULL,
                task_id INTEGER,
                run_id TEXT,
                metadata_json TEXT,
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_human_messages_conversation
                ON messages(conversation_id, created);
            CREATE INDEX IF NOT EXISTS idx_human_messages_task
                ON messages(task_id);
            """
        )
        db.commit()
        db.close()

    def _workspace_allowed(self, workspace: str | Path) -> Path:
        root = Path(workspace).expanduser().resolve()
        allowed = {str(Path(item).expanduser().resolve()) for item in self.settings.allowed_roots}
        if str(root) not in allowed:
            raise PermissionError("workspace is not approved in SENTRA Desktop")
        if not root.is_dir():
            raise FileNotFoundError("workspace no longer exists")
        return root

    def workspaces(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self.settings.allowed_roots:
            root = Path(item).expanduser().resolve()
            if not root.is_dir():
                continue
            result.append({
                "path": str(root),
                "name": root.name or str(root),
                "permissions": self.settings.workspace_permissions.get(str(root), ["read"]),
            })
        return result

    def create_conversation(self, workspace: str, title: str = "") -> dict[str, Any]:
        root = self._workspace_allowed(workspace)
        now = time.time()
        conversation_id = "conv-" + uuid.uuid4().hex[:16]
        db = self._connect()
        db.execute(
            "INSERT INTO conversations(id,workspace,title,created,updated) VALUES(?,?,?,?,?)",
            (conversation_id, str(root), _safe_title(title), now, now),
        )
        db.commit()
        db.close()
        return self.conversation(conversation_id)

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        db = self._connect()
        rows = db.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count,
                   (SELECT body FROM messages m WHERE m.conversation_id=c.id
                    ORDER BY created DESC LIMIT 1) AS last_message
            FROM conversations c
            WHERE archived=0
            ORDER BY updated DESC LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
        db.close()
        return [dict(row) for row in rows]

    def conversation(self, conversation_id: str) -> dict[str, Any]:
        db = self._connect()
        row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            db.close()
            raise FileNotFoundError("conversation not found")
        messages = db.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created",
            (conversation_id,),
        ).fetchall()
        db.close()
        data = dict(row)
        data["messages"] = [self._message_view(item) for item in messages]
        return data

    @staticmethod
    def _message_view(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = _loads(data.pop("metadata_json", None), {})
        return data

    def _append_message(
        self,
        conversation_id: str,
        role: str,
        kind: str,
        body: str,
        *,
        task_id: int | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        message_id = "msg-" + uuid.uuid4().hex[:18]
        now = time.time()
        db = self._connect()
        db.execute(
            """
            INSERT INTO messages(
                id,conversation_id,role,kind,body,task_id,run_id,metadata_json,created
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                message_id, conversation_id, role, kind, body, task_id, run_id,
                _json(metadata or {}), now,
            ),
        )
        db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conversation_id))
        db.commit()
        db.close()
        return message_id

    def send_message(self, conversation_id: str | None, workspace: str, body: str) -> dict[str, Any]:
        text = body.strip()
        if not text or len(text) > 20_000:
            raise ValueError("message must contain 1..20000 characters")
        root = self._workspace_allowed(workspace)
        if not conversation_id:
            created = self.create_conversation(str(root), _safe_title(text))
            conversation_id = str(created["id"])
        else:
            current = self.conversation(conversation_id)
            if Path(current["workspace"]).resolve() != root:
                raise ValueError("conversation belongs to another workspace")
        self._append_message(conversation_id, "user", "message", text)
        task = enqueue_task(self.paths, root, text)
        self._append_message(
            conversation_id,
            "system",
            "execution",
            f"Tarefa #{task['task_id']} adicionada à fila.",
            task_id=int(task["task_id"]),
            metadata={"state": task["state"], "workspace": task["workspace"]},
        )
        return {
            "conversation": self.conversation(conversation_id),
            "task": task,
        }

    def archive_conversation(self, conversation_id: str) -> None:
        db = self._connect()
        db.execute("UPDATE conversations SET archived=1,updated=? WHERE id=?", (time.time(), conversation_id))
        db.commit()
        db.close()

    def task_link(self, task_id: int) -> dict[str, Any] | None:
        db = self._connect()
        row = db.execute(
            "SELECT conversation_id FROM messages WHERE task_id=? ORDER BY created LIMIT 1",
            (task_id,),
        ).fetchone()
        db.close()
        return dict(row) if row else None
    def record_task_result(self, result: dict[str, Any]) -> None:
        task_id = int(result["task_id"])
        link = self.task_link(task_id)
        if not link:
            return
        conversation_id = str(link["conversation_id"])
        db = self._connect()
        existing = db.execute(
            "SELECT id FROM messages WHERE task_id=? AND kind='result' LIMIT 1",
            (task_id,),
        ).fetchone()
        db.close()
        if existing:
            return
        task_row = next(
            (item for item in list_tasks(self.paths, 500) if int(item["id"]) == task_id),
            None,
        )

        log_path = Path(str(result.get("log") or ""))
        log_text = _tail_text(log_path)
        run_id = None
        match = re.search(r"(?m)^Run:\s*([A-Za-z0-9][A-Za-z0-9_-]{0,79})\s*$", log_text)
        if match:
            run_id = match.group(1)

        workspace = Path(str(task_row["workspace"])) if task_row else None
        handoff: dict[str, Any] = {}
        handoff_path: Path | None = None
        if workspace is not None and run_id:
            candidate = workspace / "runs" / run_id / "handoff.json"
            if candidate.is_file():
                try:
                    handoff = json.loads(candidate.read_text(encoding="utf-8"))
                    handoff_path = candidate
                except (OSError, json.JSONDecodeError):
                    handoff = {}

        state = str(result.get("state") or (task_row["state"] if task_row else "UNKNOWN"))
        if handoff:
            synthesis = str(handoff.get("final_synthesis") or "").strip()
            errors = handoff.get("errors") or []
            if synthesis:
                body = synthesis
            elif errors:
                body = f"Execução finalizada com estado {handoff.get('status', state)}.\n" + "\n".join(str(x) for x in errors[:8])
            else:
                body = f"Execução finalizada com estado {handoff.get('status', state)}."
            metadata = {
                "state": handoff.get("status", state),
                "completed_tasks": handoff.get("completed_tasks"),
                "total_tasks": handoff.get("total_tasks"),
                "metrics": handoff.get("metrics") or {},
                "patch_path": handoff.get("patch_path"),
                "handoff_path": str(handoff_path) if handoff_path else None,
                "errors": errors,
                "log": str(log_path) if log_path else None,
            }
        else:
            error = str(result.get("error") or "").strip()
            body = f"Execução finalizada com estado {state}."
            if error:
                body += f"\n{error}"
            metadata = {
                "state": state,
                "result_code": result.get("result_code"),
                "log": str(log_path) if log_path else None,
            }
        self._append_message(
            conversation_id,
            "assistant",
            "result",
            body,
            task_id=task_id,
            run_id=run_id,
            metadata=metadata,
        )

    def _queue_has_tasks(self, db: sqlite3.Connection) -> bool:
        try:
            return db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'"
            ).fetchone() is not None
        except sqlite3.Error:
            return False

    def reconcile_results(self) -> None:
        tasks = {int(item["id"]): item for item in list_tasks(self.paths, 250)}
        db = self._connect()
        rows = db.execute(
            "SELECT DISTINCT task_id FROM messages WHERE task_id IS NOT NULL"
        ).fetchall()
        recorded = {
            int(row["task_id"])
            for row in db.execute("SELECT task_id FROM messages WHERE kind='result' AND task_id IS NOT NULL")
        }
        db.close()
        for row in rows:
            task_id = int(row["task_id"])
            task = tasks.get(task_id)
            if not task or task_id in recorded or task["state"] not in _TERMINAL:
                continue
            self.record_task_result({
                "task_id": task_id,
                "state": task["state"],
                "result_code": task.get("result_code"),
                "error": task.get("error"),
                "log": str(self.paths.state_dir / "logs" / f"task-{task_id}.log"),
            })

    def _research_runs(self, limit: int = 80) -> list[dict[str, Any]]:
        database = self.paths.state_dir / "research.sqlite3"
        if not database.is_file():
            return []
        try:
            uri = database.resolve().as_uri() + "?mode=ro"
            db = sqlite3.connect(uri, uri=True, timeout=1)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM research_runs ORDER BY created DESC LIMIT ?",
                (limit,),
            ).fetchall()
            db.close()
            result = []
            for row in rows:
                item = dict(row)
                item["kind"] = "research"
                item["key"] = "research:" + item["id"]
                item["title"] = item.get("objective") or "Research"
                item["result"] = _loads(item.pop("result_json", None), None)
                result.append(item)
            return result
        except sqlite3.Error:
            return []

    def _oma_runs(self, limit: int = 80) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for workspace in self.workspaces():
            root = Path(workspace["path"])
            runs_dir = root / "runs"
            if not runs_dir.is_dir():
                continue
            for handoff_path in runs_dir.glob("*/handoff.json"):
                try:
                    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                run_id = str(handoff.get("run_id") or handoff_path.parent.name)
                found.append({
                    "kind": "oma",
                    "key": f"oma:{run_id}",
                    "id": run_id,
                    "title": handoff.get("objective") or run_id,
                    "workspace": str(root),
                    "state": handoff.get("status") or "UNKNOWN",
                    "created": handoff_path.stat().st_mtime,
                    "updated": handoff_path.stat().st_mtime,
                    "completed_tasks": handoff.get("completed_tasks"),
                    "total_tasks": handoff.get("total_tasks"),
                    "metrics": handoff.get("metrics") or {},
                    "patch_path": handoff.get("patch_path"),
                    "errors": handoff.get("errors") or [],
                    "handoff_path": str(handoff_path),
                })
        found.sort(key=lambda item: float(item.get("updated") or 0), reverse=True)
        return found[:limit]

    def unified_runs(self, limit: int = 120) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for task in list_tasks(self.paths, limit):
            runs.append({
                **task,
                "kind": "task",
                "key": f"task:{task['id']}",
                "title": task.get("prompt") or f"Tarefa #{task['id']}",
            })
        for job in list_recent_jobs(self.paths, limit):
            runs.append({
                **job,
                "kind": "job",
                "key": f"job:{job['id']}",
                "title": " ".join(x for x in (job.get("operation"), job.get("target")) if x),
            })
        runs.extend(self._research_runs(limit))
        runs.extend(self._oma_runs(limit))
        runs.sort(key=lambda item: float(item.get("updated") or item.get("created") or 0), reverse=True)
        return runs[:limit]

    def run_detail(self, key: str) -> dict[str, Any]:
        if key.startswith("oma:"):
            run_id = key.split(":", 1)[1]
            match = next((item for item in self._oma_runs(250) if item["id"] == run_id), None)
            if not match:
                raise FileNotFoundError("OMA run not found")
            run_dir = Path(match["handoff_path"]).parent
            events: list[dict[str, Any]] = []
            event_path = run_dir / "events.jsonl"
            if event_path.is_file():
                for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines()[-240:]:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                        events.append({
                            "type": item.get("event_type"),
                            "producer": item.get("producer"),
                            "task_id": item.get("task_id"),
                            "candidate_id": item.get("candidate_id"),
                            "timestamp": item.get("timestamp"),
                            "summary": payload.get("reason") or payload.get("status") or payload.get("summary") or payload.get("operation"),
                        })
            patch_text = ""
            patch_value = str(match.get("patch_path") or "")
            if patch_value:
                try:
                    patch_path = Path(patch_value).expanduser().resolve()
                    if patch_path.is_relative_to(run_dir.resolve()):
                        patch_text = _head_text(patch_path)
                except (OSError, ValueError, AttributeError):
                    patch_text = ""
            return {**match, "events": events, "patch_text": patch_text, "log": ""}
        if key.startswith("task:"):
            task_id = int(key.split(":", 1)[1])
            task = next((x for x in list_tasks(self.paths, 500) if int(x["id"]) == task_id), None)
            if not task:
                raise FileNotFoundError("task not found")
            log_path = self.paths.state_dir / "logs" / f"task-{task_id}.log"
            return {**task, "kind": "task", "key": key, "log": _tail_text(log_path)}
        if key.startswith("research:"):
            run_id = key.split(":", 1)[1]
            match = next((x for x in self._research_runs(500) if x["id"] == run_id), None)
            if not match:
                raise FileNotFoundError("research run not found")
            return match
        if key.startswith("job:"):
            job_id = key.split(":", 1)[1]
            database = self.paths.state_dir / "jobs.sqlite3"
            if not database.is_file():
                raise FileNotFoundError("jobs database not found")
            uri = database.resolve().as_uri() + "?mode=ro"
            db = sqlite3.connect(uri, uri=True, timeout=1)
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            db.close()
            if not row:
                raise FileNotFoundError("job not found")
            item = dict(row)
            item["result"] = _loads(item.pop("result_json", None), None)
            item["kind"] = "job"
            item["key"] = key
            return item
        raise ValueError("unknown run key")
    def activity(self, limit: int = 160) -> list[dict[str, Any]]:
        items = tail_audit(self.paths, max(1, min(limit, 500)))
        return list(reversed(items))

    def logs(self, limit: int = 60) -> list[dict[str, Any]]:
        root = self.paths.state_dir / "logs"
        if not root.is_dir():
            return []
        files = sorted(
            (item for item in root.iterdir() if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "name": item.name,
                "size": item.stat().st_size,
                "updated": item.stat().st_mtime,
            }
            for item in files[:limit]
        ]

    def read_log(self, name: str) -> dict[str, Any]:
        if Path(name).name != name:
            raise ValueError("invalid log name")
        path = self.paths.state_dir / "logs" / name
        if not path.is_file():
            raise FileNotFoundError("log not found")
        return {"name": name, "text": _tail_text(path, 128 * 1024)}

    def diff(self, workspace: str) -> dict[str, Any]:
        root = self._workspace_allowed(workspace)
        text = git_diff(root)
        stat = subprocess.run(
            ["git", "-C", str(root), "diff", "--numstat", "--"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        files: list[dict[str, Any]] = []
        if stat.returncode == 0:
            for line in stat.stdout.splitlines():
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    files.append({"added": parts[0], "deleted": parts[1], "path": parts[2]})
        return {"workspace": str(root), "text": text, "files": files}

    def snapshot(self, conversation_id: str | None = None) -> dict[str, Any]:
        self.settings = ProductSettings.load(self.paths.settings)
        self.reconcile_results()
        conversations = self.list_conversations()
        selected = None
        if conversation_id:
            try:
                selected = self.conversation(conversation_id)
            except FileNotFoundError:
                selected = None
        if selected is None and conversations:
            selected = self.conversation(str(conversations[0]["id"]))
        return {
            "product": {
                "name": "SENTRA",
                "profile": self.settings.profile,
            },
            "status": collect_product_status(self.paths, self.settings),
            "workspaces": self.workspaces(),
            "conversations": conversations,
            "conversation": selected,
            "runs": self.unified_runs(),
            "activity": self.activity(),
            "logs": self.logs(),
            "now": time.time(),
        }
