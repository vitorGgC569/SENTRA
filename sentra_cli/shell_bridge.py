"""Shell bridge client for SENTRA CLI: Home/Dots/Spaces/conversations.

Uses the single authoritative route ``POST /api/shell/bridge`` composed by
the principal (Codex). The CLI never creates authority: it derives identity
and scope from the authenticated local session, sends an allowlisted
``action`` with ``request_key``/``project_id`` (``ws`` accepted as legacy
input alias), and surfaces the canonical envelope.

Fail closed when the local broker is unavailable or an optional service is
not configured.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
import hashlib

from sentra_core.conversations import _encode, _decode

BRIDGE_ROUTE = "/api/shell/bridge"

READ_ACTIONS = frozenset({
    "home", "space_list", "space_get", "dot_list",
    "access_status", "goal_status", "dot_canvas_get", "dot_computer_get", "dot_computer_read",
    "dot_vm_status", "dot_vm_frame",
    "conversation_list", "message_list", "events",
    "document_list", "document_get", "document_history", "document_diff", "document_export",
    "project_file_list", "project_file_preview", "project_file_diff", "project_file_pdf_text", "project_file_pdf_visual",
    "project_watch_start", "project_watch_poll", "project_watch_close", "attachment_upload_status",
    "turn_permission_list",
})
WRITE_ACTIONS = frozenset({
    "dot_computer_action",
    "dot_vm_configure", "dot_vm_execute", "dot_vm_input", "dot_vm_handoff",
    "space_create", "dot_create", "dot_update", "conversation_create",
    "access_set", "access_approve", "access_reject", "dot_canvas_terminal", "dot_canvas_terminal_close", "goal_set", "goal_stop", "goal_complete", "goal_loop_start", "goal_loop_stop", "goal_loop_step",
    "dot_canvas_move", "dot_canvas_link", "dot_canvas_unlink",
    "message_send", "coordinate",
    "document_list", "document_get", "document_create", "document_save",
    "document_history", "document_restore", "document_delete",
    "document_session", "document_session_close", "attachment_register", "attachment_upload_begin",
    "attachment_upload_chunk", "attachment_upload_complete", "attachment_upload_abort",
    "turn_permission_grant", "turn_permission_revoke",
})
WRITE_ACTIONS = WRITE_ACTIONS - READ_ACTIONS
ALLOWED_ACTIONS = READ_ACTIONS | WRITE_ACTIONS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


class ShellBridge:
    """Loopback-only client bound to the local Canvas broker credential."""

    def __init__(self, config) -> None:
        self.workspace = str(getattr(config, "workspace", "."))
        self._token = os.environ.get("SENTRA_CANVAS_BEARER", "")
        port = os.environ.get("SENTRA_CANVAS_PORT", "")
        self.port = int(port) if port.isdigit() and 1 <= int(port) <= 65535 else None
        self.is_available = bool(self.port and len(self._token) >= 32)
        self.state_root = Path(getattr(config, "state_root", Path(self.workspace) / ".sentra")).resolve()
        from sentra_runtime.provider_authority import load_provider_binding
        self.binding = load_provider_binding(self.state_root)
        self.project_id = str((self.binding or {}).get("project_id") or os.environ.get("SENTRA_CANVAS_WORKSPACE", ""))

    def _journal(self, key):
        return self.state_root / "cli-shell-requests" / (hashlib.sha256(key.encode()).hexdigest() + ".protected")

    def _authority_identity(self):
        from sentra_runtime.provider_authority import load_provider_binding
        binding = load_provider_binding(self.state_root)
        return {"capsule": {k: (binding or {}).get(k) for k in
            ("backend", "tenant_id", "principal_id", "project_id", "run_id", "work_item_id", "operation_id")},
            "broker": hashlib.sha256((str(self.port) + ':' + self._token).encode()).hexdigest()}

    def _store_request(self, key, record):
        record = {**record, "authority": self._authority_identity()}
        path = self._journal(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.parent.is_symlink():
            raise PermissionError("unsafe CLI request journal")
        temporary = path.with_suffix('.pending')
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(_encode(record)); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)

    def request_status(self, request_key):
        path = self._journal(request_key)
        if not path.is_file(): return {"status": "not_submitted", "request_key": request_key}
        if path.is_symlink(): raise PermissionError("linked CLI request journal")
        record = _decode(path.read_text(encoding='utf-8'))
        if record.get("authority") != self._authority_identity():
            raise PermissionError("CLI receipt belongs to another authority session")
        return {"status": record["status"], "request_key": request_key, "action": record["body"]["action"],
                "project_id": record["body"]["project_id"], "response": record.get("response")}

    def _request(self, body: dict) -> dict:
        if not self.is_available:
            raise RuntimeError(
                "Shell bridge unavailable: start the local SENTRA Canvas broker "
                "so the CLI shares the same agents and authoritative state."
            )
        action = body.get("action")
        if action not in ALLOWED_ACTIONS:
            raise ValueError("shell action is not allowlisted")
        raw_body = json.dumps(body, allow_nan=False).encode('utf-8')
        if len(raw_body) > 800000:
            raise ValueError("shell payload exceeds the host body limit")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{BRIDGE_ROUTE}",
            data=raw_body,
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=30) as response:
                payload = response.read(2_100_000 + 1)
                if len(payload) > 2_100_000:
                    raise RuntimeError("Shell bridge response exceeded limit")
                data = json.loads(payload)
        except urllib.error.HTTPError as exc:
            try:
                details = json.loads(exc.read(2048))
                reason = details.get("error", "") if isinstance(details, dict) else ""
            except (ValueError, OSError):
                reason = ""
            suffix = f": {reason[:160]}" if isinstance(reason, str) and reason else ""
            raise RuntimeError(f"Shell bridge rejected the operation (HTTP {exc.code}){suffix}") from None
        if not isinstance(data, dict):
            raise RuntimeError("invalid shell bridge response")
        return data

    def dispatch(
        self, action: str, *, project_id: str = "", space_id: str = "",
        conversation_id: str = "", request_key: str = "", extra: dict | None = None,
    ) -> dict:
        """Send one allowlisted shell action with deduplication identity."""
        name = (action or "").strip()
        if name not in ALLOWED_ACTIONS:
            raise ValueError("shell action is not allowlisted")
        key = (request_key or "").strip() or uuid.uuid4().hex
        body: dict = {"action": name, "request_key": key}
        if project_id.strip():
            body["project_id"] = project_id.strip()
        if space_id.strip():
            body["space_id"] = space_id.strip()
        if conversation_id.strip():
            body["conversation_id"] = conversation_id.strip()
        if extra:
            if not isinstance(extra, dict):
                raise ValueError("shell extra payload must be an object")
            forbidden = {"action", "request_key", "project_id", "space_id", "conversation_id", "owner", "principal", "principal_id", "grant", "grant_id", "permission", "run_id", "tenant_id", "dsn", "operation_id"}
            if name not in {'turn_permission_list', 'turn_permission_grant', 'turn_permission_revoke'}:
                forbidden.add('work_item_id')
            for field in forbidden:
                if field in extra:
                    raise ValueError(f"shell payload must not carry {field}")
            body.update(extra)
            if name.startswith('turn_permission_'):
                if set(extra) - {'work_item_id', 'capabilities', 'ttl_seconds'}:
                    raise ValueError('unknown scoped turn permission fields')
                if name != 'turn_permission_list' and (not space_id or not conversation_id or not extra.get('work_item_id')):
                    raise ValueError('turn permission mutation requires canonical Space/conversation/WorkItem IDs')
            if "path" in extra and not name.startswith("project_file_") and name != "project_watch_start":
                raise PermissionError("file paths are only accepted by scoped project preview reads")
        body.setdefault("project_id", self.project_id)
        if not body.get("project_id"):
            raise ValueError("an authoritative project_id is required; workspace path is not a project ID")
        if self.binding and body["project_id"] != self.binding["project_id"]:
            raise PermissionError("shell project differs from the trusted authority capsule")
        if name in WRITE_ACTIONS and "request_key" not in body:
            raise ValueError("durable shell mutations require request_key")
        if name in READ_ACTIONS:
            return self._request(body)
        from sentra_remote.product import _exclusive_registry_lock
        self._journal(key).parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_registry_lock(self._journal(key).with_suffix('.lock'), timeout_s=3):
            path = self._journal(key)
            if path.is_file():
                record = _decode(path.read_text(encoding='utf-8'))
                if record.get("authority") != self._authority_identity():
                    raise PermissionError("CLI request_key belongs to another authority session")
                if record["body"] != body: raise PermissionError("CLI request_key bound to another intent")
                if record["status"] in {"confirmed", "accepted"}: return record["response"]
                raise RuntimeError("CLI request remains pending/uncertain; consult status, never resend")
            self._store_request(key, {"body": body, "status": "pending"})
            try:
                result = self._request(body)
                if result.get("ok") is not True:
                    raise RuntimeError("shell response has no authoritative receipt envelope")
                projected = result.get("value") or {}
                status = "uncertain" if projected.get("status") in {"uncertain", "pending"} else "accepted" if projected.get("status") in {"queued", "dispatched", "waiting_approval"} else "confirmed"
                self._store_request(key, {"body": body, "status": status, "response": result})
                return result
            except Exception:
                self._store_request(key, {"body": body, "status": "uncertain"})
                raise RuntimeError(f"shell request {key} is unconfirmed; consult the original request_key without resending") from None

    def send_turn(self, content, *, project_id="", space_id, conversation_id, request_key, attachments=()):
        """Send one turn with Brisa refs; the host resolves bytes and same receipt."""
        import re
        refs = list(attachments)
        if len(refs) > 4 or any(not isinstance(ref, str) or not re.fullmatch(r"att-[a-f0-9]{32}", ref) for ref in refs):
            raise ValueError("attachments require 0..4 scoped att-* references")
        if not isinstance(content, str) or not content.strip() or not request_key:
            raise ValueError("turn content and stable request_key required")
        return self.dispatch("message_send", project_id=project_id, space_id=space_id,
            conversation_id=conversation_id, request_key=request_key, extra={"content": content, "attachments": refs})

    def status(self) -> dict:
        return {
            "route": BRIDGE_ROUTE,
            "available": self.is_available,
            "authority": "Canvas/Control Plane (principal-composed)",
        }
