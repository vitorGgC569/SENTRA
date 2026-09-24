"""Installed SENTRA Desktop product state, profiles and local operations."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .secrets import protect_secret, unprotect_secret

SAFE_TOOL_ALLOWLIST = (
    "sentra_session_open", "sentra_list_directory", "sentra_read_file",
    "sentra_read_multiple_files", "sentra_file_info", "sentra_search",
    "sentra_list_processes", "sentra_list_sessions", "sentra_read_process_output",
    "sentra_process_sandbox_status", "sentra_repo_workspaces", "sentra_repo_read",
    "sentra_repo_search", "sentra_repo_tree", "sentra_repo_symbol",
    "sentra_repo_status", "sentra_repo_diff", "sentra_get_config",
    "sentra_usage_stats", "sentra_recent_tool_calls", "sentra_audit_query",
    "sentra_document_info", "sentra_read_document", "sentra_browser_tabs",
    "sentra_browser_extract", "sentra_browser_screenshot", "sentra_workspaces",
    "sentra_pending_config", "sentra_pending_workspaces", "sentra_list_jobs",
    "sentra_job_status", "sentra_job_result", "sentra_list_searches",
    "sentra_get_search_results", "sentra_search_wait", "sentra_oma_health",
    "sentra_oma_runs", "sentra_oma_status", "sentra_oma_events",
    "sentra_oma_handoff", "sentra_oma_queue_status", "sentra_oma_reconcile_status",
    "sentra_list_research_runs", "sentra_research_status", "sentra_research_result",
)

PROFILE_POLICIES: dict[str, dict[str, Any]] = {
    "Safe": {
        "surfaces": ("core", "developer", "browser", "oma"),
        "process_mode": "sandbox",
        "tool_allowlist": SAFE_TOOL_ALLOWLIST,
    },
    "Developer": {
        "surfaces": ("core", "developer", "browser"),
        "process_mode": "workspace",
        "tool_allowlist": (),
    },
    "Full": {
        "surfaces": ("all",),
        "process_mode": "workspace",
        "tool_allowlist": (),
    },
}


@dataclass(slots=True)
class ProductPaths:
    install_dir: Path
    state_dir: Path

    @classmethod
    def default(cls, install_dir: Path | None = None) -> "ProductPaths":
        installed = Path(install_dir or Path(os.environ.get(
            "LOCALAPPDATA", str(Path.home())
        )) / "SENTRA" / "Commander").expanduser().resolve()
        state_override = os.environ.get("SENTRA_STATE_DIR", "").strip()
        state_dir = (
            Path(state_override).expanduser().resolve()
            if state_override
            else (Path.home() / ".sentra").resolve()
        )
        return cls(installed, state_dir)

    @property
    def settings(self) -> Path:
        return self.state_dir / "desktop.json"

    @property
    def tunnel_config(self) -> Path:
        return self.state_dir / "tunnel.json"

    @property
    def browser_dir(self) -> Path:
        return self.state_dir / "browser"

    @property
    def relay_token(self) -> Path:
        return self.browser_dir / "relay-token"

    @property
    def audit_log(self) -> Path:
        return self.state_dir / "mcp-audit.jsonl"
    @property
    def snapshots_dir(self) -> Path:
        return self.state_dir / "snapshots"

    @property
    def tunnel_dir(self) -> Path:
        return self.state_dir / "tunnel"

    @property
    def tunnel_client(self) -> Path:
        return self.install_dir / "tunnel-client.exe"

    @property
    def extension_dir(self) -> Path:
        return self.install_dir / "edge_extension"


@dataclass(slots=True)
class ProductSettings:
    profile: str = "Developer"
    allowed_roots: list[str] = field(default_factory=list)
    autostart_mcp: bool = True
    autostart_relay: bool = True
    autostart_tunnel: bool = True
    autostart_agent: bool = False
    update_manifest_url: str = ""
    auto_update: bool = True
    tool_allowlist: list[str] = field(default_factory=list)
    workspace_permissions: dict[str, list[str]] = field(default_factory=dict)
    mcp_port: int = 8000
    relay_port: int = 8765
    web_model_name: str = ""

    @staticmethod
    def _normalize_web_model_name(value: object) -> str:
        model = str(value or "").strip()
        if model and (
            not model.startswith("sentra/chatgpt-web/")
            or len(model) > 200
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in model)
        ):
            raise ValueError("web_model_name must use the sentra/chatgpt-web/ namespace")
        return model

    @classmethod
    def load(cls, path: Path) -> "ProductSettings":
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("desktop settings must be a JSON object")
        known = {item.name for item in cls.__dataclass_fields__.values()}
        settings = cls(**{key: value for key, value in data.items() if key in known})
        settings.web_model_name = cls._normalize_web_model_name(settings.web_model_name)
        return settings

    def save(self, path: Path) -> None:
        if self.profile not in PROFILE_POLICIES:
            raise ValueError("unknown SENTRA profile")
        for label, port in (("MCP", self.mcp_port), ("relay", self.relay_port)):
            if not isinstance(port, int) or not 1024 <= port <= 65535:
                raise ValueError(f"{label} port must be 1024..65535")
        if self.mcp_port == self.relay_port:
            raise ValueError("MCP and relay ports must be different")
        self.web_model_name = self._normalize_web_model_name(self.web_model_name)
        roots: list[str] = []
        for item in self.allowed_roots:
            root = Path(item).expanduser().resolve()
            if root.is_dir() and str(root) not in roots:
                roots.append(str(root))
        self.allowed_roots = roots
        normalized_permissions: dict[str, list[str]] = {}
        for root in roots:
            requested = self.workspace_permissions.get(root) or (
                ["read"] if self.profile == "Safe" else ["read", "write", "execute"]
            )
            permissions = [
                name for name in ("read", "write", "execute")
                if name in set(str(item).strip().lower() for item in requested)
            ]
            normalized_permissions[root] = permissions or ["read"]
        self.workspace_permissions = normalized_permissions
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temp.replace(path)

    def policy(self) -> dict[str, Any]:
        base = dict(PROFILE_POLICIES[self.profile])
        if self.tool_allowlist:
            base["tool_allowlist"] = tuple(dict.fromkeys(self.tool_allowlist))
        return base


def ensure_browser_token(paths: ProductPaths) -> str:
    paths.browser_dir.mkdir(parents=True, exist_ok=True)
    if paths.relay_token.is_file():
        token = paths.relay_token.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    paths.relay_token.write_text(token, encoding="utf-8")
    try:
        os.chmod(paths.relay_token, 0o600)
    except OSError:
        pass
    return token


def configure_tunnel(paths: ProductPaths, tunnel_id: str, runtime_key: str) -> None:
    tunnel_id = tunnel_id.strip()
    runtime_key = runtime_key.strip()
    if not tunnel_id.startswith("tunnel_") or len(tunnel_id) < 15:
        raise ValueError("tunnel_id must look like tunnel_...")
    if len(runtime_key) < 20:
        raise ValueError("Runtime API key is missing or too short")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "tunnel_id": tunnel_id,
        "runtime_key": protect_secret(runtime_key),
        "configured_at": time.time(),
    }
    temp = paths.tunnel_config.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(paths.tunnel_config)


def load_tunnel_config(paths: ProductPaths, *, reveal_secret: bool = False) -> dict[str, Any]:
    if not paths.tunnel_config.is_file():
        return {}
    data = json.loads(paths.tunnel_config.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    result = {
        "tunnel_id": str(data.get("tunnel_id", "")),
        "configured_at": data.get("configured_at"),
        "runtime_key_present": bool(data.get("runtime_key")),
    }
    if reveal_secret and data.get("runtime_key"):
        result["runtime_key"] = unprotect_secret(str(data["runtime_key"]))
    return result


def tcp_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def json_get(url: str, *, token: str = "", timeout: float = 1.0) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(1024 * 1024)
    value = json.loads(raw or b"{}")
    return value if isinstance(value, dict) else {}


def _docker_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": str(exc)[:160]}
    return {
        "ok": result.returncode == 0,
        "detail": (result.stdout or result.stderr).strip()[:160],
    }


def _git_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": str(exc)[:160]}
    return {"ok": result.returncode == 0, "detail": result.stdout.strip()[:160]}


def collect_product_status(paths: ProductPaths, settings: ProductSettings) -> dict[str, Any]:
    token = ""
    try:
        token = ensure_browser_token(paths)
    except OSError:
        pass
    instance_id = ensure_instance_id(paths)
    mcp_port_open = tcp_open("127.0.0.1", settings.mcp_port)
    mcp: dict[str, Any] = {
        "ok": False,
        "port_open": mcp_port_open,
        "endpoint": f"http://127.0.0.1:{settings.mcp_port}/mcp",
    }
    if mcp_port_open:
        try:
            health = json_get(f"http://127.0.0.1:{settings.mcp_port}/healthz")
            mcp.update({
                "ok": (
                    health.get("ok") is True
                    and health.get("service") == "sentra-mcp"
                    and health.get("instance_id") == instance_id
                ),
                "server_version": health.get("server_version"),
            })
            if not mcp["ok"]:
                mcp["detail"] = "port belongs to a different SENTRA instance"
        except Exception as exc:
            mcp["detail"] = str(exc)[:160]
    relay_port_open = tcp_open("127.0.0.1", settings.relay_port)
    relay: dict[str, Any] = {
        "ok": False,
        "port_open": relay_port_open,
        "endpoint": f"http://127.0.0.1:{settings.relay_port}",
    }
    if relay_port_open:
        try:
            health = json_get(
                f"http://127.0.0.1:{settings.relay_port}/health",
                token=token,
            )
            relay.update({
                "ok": health.get("ok") is True,
                "workers_online": health.get("workers_online", []),
                "bridge_state": health.get("state") or health.get("edge_bridge", {}).get("state"),
            })
        except Exception as exc:
            relay["ok"] = False
            relay["detail"] = str(exc)[:160]
    tunnel: dict[str, Any] = {"ok": False, "configured": bool(load_tunnel_config(paths))}
    health_file = paths.tunnel_dir / "health-url.txt"
    if health_file.is_file():
        try:
            base = health_file.read_text(encoding="utf-8").strip().rstrip("/")
            with urllib.request.urlopen(base + "/healthz", timeout=1) as response:
                tunnel["health"] = response.status
            with urllib.request.urlopen(base + "/readyz", timeout=1) as response:
                tunnel["ready"] = response.status
            tunnel["ok"] = tunnel.get("health") == 200 and tunnel.get("ready") == 200
            tunnel["ui"] = base + "/ui"
        except Exception as exc:
            tunnel["detail"] = str(exc)[:160]
    edge = {
        "ok": bool(relay.get("workers_online")),
        "workers": relay.get("workers_online", []),
        "extension_dir": str(paths.extension_dir),
    }
    remote_agent: dict[str, Any] = {"ok": False, "configured": False}
    agent_path = paths.state_dir / "agent.json"
    if agent_path.is_file():
        try:
            agent_data = json.loads(agent_path.read_text(encoding="utf-8"))
            remote_agent.update({
                "configured": True,
                "device_id": agent_data.get("device_id"),
                "name": agent_data.get("name"),
                "relay_url": agent_data.get("relay_url"),
                "process_mode": agent_data.get("process_mode"),
            })
        except (OSError, json.JSONDecodeError):
            remote_agent["detail"] = "agent config is unreadable"
    return {
        "mcp": mcp,
        "relay": relay,
        "tunnel": tunnel,
        "edge": edge,
        "remote_agent": remote_agent,
        "sandbox": _docker_status(),
        "git": _git_status(),
        "profile": settings.profile,
        "allowed_roots": list(settings.allowed_roots),
    }
def list_recent_jobs(paths: ProductPaths, limit: int = 50) -> list[dict[str, Any]]:
    database = paths.state_dir / "jobs.sqlite3"
    if not database.is_file():
        return []
    uri = database.resolve().as_uri() + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id,operation,target,workspace,state,error,created,updated "
            "FROM jobs ORDER BY created DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        db.close()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def tail_audit(paths: ProductPaths, limit: int = 100) -> list[dict[str, Any]]:
    if not paths.audit_log.is_file():
        return []
    lines = paths.audit_log.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    result: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                result.append(item)
        except json.JSONDecodeError:
            continue
    return result


def git_diff(workspace: Path, max_bytes: int = 2 * 1024 * 1024) -> str:
    root = workspace.expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--no-ext-diff", "--"],
        capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = result.stdout if result.returncode == 0 else result.stderr
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) > max_bytes:
        return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n... [truncated]"
    return output


_SNAPSHOT_EXCLUDES = {".git", ".sentra", "__pycache__", ".pytest_cache", "node_modules", "runs"}


def _snapshot_files(root: Path):
    for path in root.rglob("*"):
        if any(part in _SNAPSHOT_EXCLUDES for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            continue
        if path.is_file():
            yield path


def create_snapshot(paths: ProductPaths, workspace: Path) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError("workspace does not exist")
    paths.snapshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ident = hashlib.sha256(str(root).encode()).hexdigest()[:10]
    target = paths.snapshots_dir / f"{root.name}-{stamp}-{ident}.zip"
    manifest: dict[str, str] = {}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in _snapshot_files(root):
            relative = file.relative_to(root).as_posix()
            data = file.read_bytes()
            manifest[relative] = hashlib.sha256(data).hexdigest()
            archive.writestr("files/" + relative, data)
        archive.writestr("manifest.json", json.dumps({
            "workspace": str(root),
            "created_at": time.time(),
            "files": manifest,
        }, indent=2))
    return {"snapshot": str(target), "files": len(manifest), "workspace": str(root)}


def rollback_snapshot(snapshot: Path, workspace: Path) -> dict[str, Any]:
    archive_path = snapshot.expanduser().resolve()
    root = workspace.expanduser().resolve()
    if not archive_path.is_file() or not root.is_dir():
        raise FileNotFoundError("snapshot or workspace does not exist")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        expected = manifest.get("files", {})
        if not isinstance(expected, dict):
            raise ValueError("invalid snapshot manifest")
        staged = Path(tempfile.mkdtemp(prefix="sentra-rollback-"))
        try:
            for relative, digest in expected.items():
                member = "files/" + str(relative)
                data = archive.read(member)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("snapshot checksum mismatch")
                destination = (staged / str(relative)).resolve()
                if staged.resolve() not in destination.parents:
                    raise ValueError("unsafe snapshot path")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            for current in sorted(_snapshot_files(root), key=lambda item: len(item.parts), reverse=True):
                current.unlink()
            for source in staged.rglob("*"):
                if source.is_file():
                    destination = root / source.relative_to(staged)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        finally:
            shutil.rmtree(staged, ignore_errors=True)
    return {"restored": len(expected), "workspace": str(root), "snapshot": str(archive_path)}


def list_snapshots(paths: ProductPaths) -> list[Path]:
    if not paths.snapshots_dir.is_dir():
        return []
    return sorted(paths.snapshots_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

def _queue_db(paths: ProductPaths) -> sqlite3.Connection:
    database = paths.state_dir / "desktop-tasks.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(database))
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL,
            prompt TEXT NOT NULL,
            state TEXT NOT NULL,
            result_code INTEGER,
            error TEXT,
            created REAL NOT NULL,
            updated REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_desktop_tasks_state_created
        ON tasks(state, created);
        """
    )
    db.commit()
    return db


def enqueue_task(paths: ProductPaths, workspace: Path, prompt: str) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    text = prompt.strip()
    if not root.is_dir():
        raise FileNotFoundError("workspace does not exist")
    if not text or len(text) > 20000:
        raise ValueError("task prompt must be 1..20000 characters")
    db = _queue_db(paths)
    now = time.time()
    cur = db.execute(
        "INSERT INTO tasks(workspace,prompt,state,created,updated) VALUES(?,?,'QUEUED',?,?)",
        (str(root), text, now, now),
    )
    db.commit()
    task_id = int(cur.lastrowid)
    db.close()
    return {"task_id": task_id, "state": "QUEUED", "workspace": str(root)}


def list_tasks(paths: ProductPaths, limit: int = 100) -> list[dict[str, Any]]:
    db = _queue_db(paths)
    rows = db.execute(
        "SELECT * FROM tasks ORDER BY created DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    ).fetchall()
    db.close()
    return [dict(row) for row in rows]


def run_next_task(paths: ProductPaths, settings: ProductSettings) -> dict[str, Any] | None:
    db = _queue_db(paths)
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        "SELECT * FROM tasks WHERE state='QUEUED' ORDER BY created LIMIT 1"
    ).fetchone()
    if row is None:
        db.commit()
        db.close()
        return None
    now = time.time()
    claimed = db.execute(
        "UPDATE tasks SET state='RUNNING',updated=? WHERE id=? AND state='QUEUED'",
        (now, row["id"]),
    )
    if claimed.rowcount != 1:
        db.commit()
        db.close()
        return None
    db.commit()
    exe = paths.install_dir / "sentra-oma.exe"
    if exe.is_file():
        command = [str(exe)]
    else:
        source_main = Path(__file__).resolve().parents[1] / "main.py"
        command = [os.environ.get("PYTHON", os.sys.executable), "-B", str(source_main)]
    command += [
        "--workspace", str(row["workspace"]),
        "--provider", "extension",
        "--reviewer", "extension",
        "--workers", "1",
        "--prompt", str(row["prompt"]),
        "--sandbox", "docker",
    ]
    env = os.environ.copy()
    env["SENTRA_EDGE_RELAY_TOKEN_PATH"] = str(paths.relay_token)
    log = paths.state_dir / "logs" / f"task-{row['id']}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    try:
        result = subprocess.run(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=3600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        state = "COMPLETED" if result.returncode == 0 else "FAILED"
        error = None if result.returncode == 0 else f"exit code {result.returncode}"
        code = result.returncode
    except subprocess.TimeoutExpired:
        state, error, code = "FAILED", "task exceeded 3600 seconds", 124
    except Exception as exc:
        state, error, code = "FAILED", str(exc)[:1000], 1
    finally:
        handle.close()
    db.execute(
        "UPDATE tasks SET state=?,result_code=?,error=?,updated=? WHERE id=?",
        (state, code, error, time.time(), row["id"]),
    )
    db.commit()
    db.close()
    return {
        "task_id": int(row["id"]),
        "state": state,
        "result_code": code,
        "error": error,
        "log": str(log),
    }

def sync_workspace_registry(paths: ProductPaths, settings: ProductSettings) -> Path:
    """Persist Desktop-approved workspace permissions for the MCP registry."""
    settings.save(paths.settings)
    state_path = paths.state_dir / "workspaces.json"
    grants: list[dict[str, Any]] = []
    now = time.time()
    for index, root_text in enumerate(settings.allowed_roots):
        root = Path(root_text).expanduser().resolve()
        permissions = settings.workspace_permissions.get(str(root), ["read"])
        grants.append({
            "workspace_id": "desktop:" + hashlib.sha256(str(root).encode()).hexdigest()[:16],
            "alias": (root.name or f"workspace-{index + 1}")[:64],
            "path": str(root),
            "permissions": list(permissions),
            "scope": "permanent",
            "owner": None,
            "expires_at": None,
            "source": "approved",
            "created_at": now,
            "approved_at": now,
        })
    payload = {"version": 1, "grants": grants, "pending": {}, "history": []}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(state_path)
    return state_path

def ensure_instance_id(paths: ProductPaths) -> str:
    path = paths.state_dir / "instance-id"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        value = path.read_text(encoding="ascii", errors="ignore").strip()
        if len(value) >= 32:
            return value
    value = secrets.token_hex(24)
    temp = path.with_suffix(".tmp")
    temp.write_text(value, encoding="ascii")
    temp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value
