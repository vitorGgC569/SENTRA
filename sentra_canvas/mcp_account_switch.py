"""Owner-driven ChatGPT MCP plugin account migration assistant.

This cannot authenticate or change the identity of a ChatGPT account. The
account connection lives in the ChatGPT service, not in the local SENTRA
tunnel/runtime key. The assistant records a non-secret migration *intent* and
compares local MCP call observations without attributing them to a plan.
Never touches cookies, browser profiles, platform credentials, tunnel keys,
OAuth tokens, grants, or the old account's remote plugin installation.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from sentra_remote.connector_proof import ConnectorProof

_MAX_AGE = 7 * 24 * 3600


class MCPAccountSwitch:
    def __init__(self, state_root: str | Path):
        self.root = Path(state_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "mcp-account-switch.sqlite3"
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS chatgpt_mcp_switches(
                owner TEXT PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                tunnel_hash TEXT NOT NULL,
                target_plan TEXT NOT NULL,
                started REAL NOT NULL,
                baseline_json TEXT NOT NULL,
                operator_confirmed INTEGER NOT NULL DEFAULT 0,
                cancelled INTEGER NOT NULL DEFAULT 0
            )""")

    def _db(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _counts(proof):
        return {str(s["name"]): int(s["calls"])
                for s in proof.get("surfaces", [])
                if isinstance(s, dict) and isinstance(s.get("name"), str)
                and type(s.get("calls")) is int and s["calls"] >= 0}

    def _snapshot(self):
        proof_service = ConnectorProof(self.root)
        return proof_service, proof_service.status()

    def status(self, owner: str):
        if not isinstance(owner, str) or not owner or len(owner) > 256:
            raise ValueError("valid local owner required")
        proof_service, proof = self._snapshot()
        tunnel = proof_service.configured_tunnel_id()
        fingerprint = hashlib.sha256(tunnel.encode("ascii")).hexdigest() if tunnel else ""
        with self._db() as db:
            row = db.execute("SELECT * FROM chatgpt_mcp_switches WHERE owner=?",
                             (owner,)).fetchone()
        active = bool(row and not row["cancelled"] and
                      time.time() - float(row["started"]) < _MAX_AGE and
                      row["tunnel_hash"] == fingerprint and bool(fingerprint))
        baseline = json.loads(row["baseline_json"]) if active else {}
        counts = self._counts(proof)
        delta = {name: count - baseline.get(name, 0) for name, count in counts.items()
                 if count > baseline.get(name, 0)}
        return {
            "tunnel_configured": bool(tunnel),
            # Tunnel ID is an enrollment identifier, NOT the runtime/API key.
            # This field is served exclusively by authenticated Canvas GET.
            "tunnel_id": tunnel,
            "active": active,
            "attempt_id": row["attempt_id"] if active else None,
            "requested_plan": "Plus" if active else None,
            "operator_steps_completed": bool(row["operator_confirmed"]) if active else False,
            "new_mcp_activity_observed": bool(delta) if active else False,
            "new_mcp_activity_surfaces": sorted(delta) if active else [],
            "chatgpt_account_verified": False,
            "chatgpt_plan_verified": False,
            "chatgpt_plugin_installation_verified": False,
            "old_free_connection_revoked": "unverified",
            "safe_to_claim_plus_active": False,
            "tunnel_health_inferred_from_account": False,
            "guidance_url": "https://chatgpt.com/",
            "instructions": [
                "Abra o ChatGPT da conta Plus, vá em Configurações > Plugins e procure SENTRA.",
                "Conecte/instale SENTRA nessa conta e revise as permissões. Se necessário, reutilize o Tunnel ID desta instalação; não altere a chave.",
                "Na conta Free, desconecte o plugin SENTRA separadamente se quiser impedir novos acessos por ela.",
                "Faça uma chamada de teste ao plugin SENTRA na conta Plus e clique em Verificar. Uma chamada local não comprova qual conta ou plano a originou.",
            ],
            "evidence": {
                "mcp_tool_observed": bool(proof.get("mcp_tool_observed")),
                "authenticated_tool_observed": bool(proof.get("authenticated_tool_observed")),
                "remote_account_identity": "unknown",
                "last_local_schema_changed": bool(proof.get("local_schema_changed_since_authenticated_call")),
            },
        }

    def begin(self, owner: str, *, approved: bool = False):
        if approved is not True:
            raise PermissionError("owner must explicitly start MCP account migration")
        _ = self.status(owner)
        proof_service, proof = self._snapshot()
        tunnel = proof_service.configured_tunnel_id()
        if not tunnel:
            raise ValueError("Configure o Secure MCP Tunnel antes de trocar a conta do plugin.")
        fingerprint = hashlib.sha256(tunnel.encode("ascii")).hexdigest()
        baseline = json.dumps(self._counts(proof), separators=(",", ":"), sort_keys=True)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM chatgpt_mcp_switches WHERE owner=?", (owner,)).fetchone()
            if (row and not row["cancelled"] and row["tunnel_hash"] == fingerprint
                    and time.time() - float(row["started"]) < _MAX_AGE):
                return self.status(owner)
            db.execute("""INSERT INTO chatgpt_mcp_switches(
                owner,attempt_id,tunnel_hash,target_plan,started,baseline_json,
                operator_confirmed,cancelled) VALUES(?,?,?,?,?,?,0,0)
                ON CONFLICT(owner) DO UPDATE SET
                attempt_id=excluded.attempt_id,tunnel_hash=excluded.tunnel_hash,
                target_plan=excluded.target_plan,started=excluded.started,
                baseline_json=excluded.baseline_json,operator_confirmed=0,cancelled=0""",
                (owner, secrets.token_urlsafe(20), fingerprint, "Plus", time.time(), baseline))
        return self.status(owner)

    def mark_steps(self, owner: str, attempt_id: str, *, approved: bool = False):
        if approved is not True:
            raise PermissionError("explicit owner confirmation required")
        if not isinstance(attempt_id, str) or len(attempt_id) > 128:
            raise ValueError("valid migration attempt required")
        if self.status(owner)["attempt_id"] != attempt_id:
            raise PermissionError("migration attempt is not current")
        with self._db() as db:
            cursor = db.execute("""UPDATE chatgpt_mcp_switches SET operator_confirmed=1
                WHERE owner=? AND attempt_id=? AND cancelled=0""", (owner, attempt_id))
            if cursor.rowcount != 1:
                raise PermissionError("migration attempt no longer active")
        return self.status(owner)

    def cancel(self, owner: str, attempt_id: str, *, approved: bool = False):
        if approved is not True:
            raise PermissionError("explicit owner confirmation required")
        if self.status(owner)["attempt_id"] != attempt_id:
            raise PermissionError("migration attempt is not current")
        with self._db() as db:
            cursor = db.execute("""UPDATE chatgpt_mcp_switches SET cancelled=1
                WHERE owner=? AND attempt_id=? AND cancelled=0""", (owner, attempt_id))
            if cursor.rowcount != 1:
                raise PermissionError("migration attempt no longer active")
        return self.status(owner)
