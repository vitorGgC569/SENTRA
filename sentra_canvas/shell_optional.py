"""Host-only voice and attachment composition using the shared Control Plane store."""
from contextlib import closing
import json
import os
from pathlib import Path
import threading

from .store import Denied
from sentra_core.conversations import _decode

# The Canvas selector already reads these ids from /api/models. Offering one
# is not a credential and not a completed provider turn.
UNVERIFIED_TURN_MODEL = "sentra/grok/grok-4.7"
UNVERIFIED_TURN_REASON = "sentra/grok/grok-4.7 is listed and access is unverified"
CATALOG_SELECTABLE_MODELS = (UNVERIFIED_TURN_MODEL,)


def load_shell_configuration(configuration=None, root=None):
    if configuration is not None:
        if not isinstance(configuration, dict):
            raise ValueError("shell host configuration must be an object")
        return json.loads(json.dumps(configuration, allow_nan=False))
    filename = os.environ.get("SENTRA_SHELL_CONFIG_FILE")
    if filename:
        raw = Path(filename).expanduser().read_bytes()
        if len(raw) > 65536:
            raise ValueError("shell host configuration exceeds limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("shell host configuration must be an object")
        return value
    workspace_root = Path(root or ".").resolve()
    sentra_dir = workspace_root / ".sentra"
    for candidate in (sentra_dir / "shell_config.json", sentra_dir / "shell.json", sentra_dir / "canvas" / "shell_config.json"):
        if candidate.is_file():
            raw = candidate.read_bytes()
            if len(raw) <= 65536:
                value = json.loads(raw)
                if isinstance(value, dict):
                    return value
    if sentra_dir.is_dir():
        ext_dir = workspace_root / "edge_extension"
        token_path = sentra_dir / "browser" / "relay-token"
        if not token_path.is_file():
            token_path = workspace_root / ".oma" / "relay-token"
        return {
            "web_relay": {
                "enabled": True,
                "port": 8765,
                "extension_dir": str(ext_dir) if ext_dir.is_dir() else "edge_extension",
                "token_file": str(token_path),
                "models": [
                    "sentra/chatgpt-web/gpt-6",
                    "sentra/chatgpt-web/high",
                    "sentra/chatgpt-web/gpt-5.6-sol",
                    *CATALOG_SELECTABLE_MODELS,
                    "sentra/codex/current",
                    "chatgpt",
                    "gpt-4o",
                    "gpt-4",
                    "o1",
                    "o3-mini",
                ],
            }
        }
    if os.environ.get("SENTRA_VOICE_PROVIDER_API_KEY") or os.environ.get("SENTRA_VOICE_PROVIDER_BEARER"):
        # Credentials stay in the provider's server-side environment resolver.
        return {"voice_provider": {"kind": "openai-realtime"}}
    return {}


class OptionalShellServices:
    def __init__(self, runtime):
        self.runtime = runtime
        self.control, self.canvas = runtime.control, runtime.canvas
        self.lock = threading.RLock()
        self._voice = self._attachments = None
        with closing(self.control.store.connect("shell")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS canvas_shell_upload_bindings("
                "upload_id TEXT PRIMARY KEY,owner TEXT NOT NULL,project_id TEXT NOT NULL,"
                "space_id TEXT NOT NULL,conversation_id TEXT NOT NULL,begin_key TEXT NOT NULL,"
                "UNIQUE(owner,project_id,begin_key))")

    def _attachment_store(self):
        with self.lock:
            if self._attachments is None:
                from browser.attachments import AttachmentStore
                self._attachments = AttachmentStore(self.control.durable.root / "shell-attachments",
                    store=self.control.store)
            return self._attachments

    def _voice_service(self):
        with self.lock:
            if self._voice is None:
                from browser.voice import VoiceRuntime
                self._voice = VoiceRuntime(self.control.durable.root,
                    config=self.canvas._shell_configuration, store=self.control.store)
            return self._voice

    def voice_availability(self, project_id, owner):
        self.runtime._project(project_id, owner)
        return self._voice_service().voice_availability(project_id, owner)

    def attachment_availability(self, project_id, owner):
        self.runtime._project(project_id, owner)
        return {**self._attachment_store().attachment_availability(), **self.runtime.web.availability()}

    def voice_dispatch(self, project_id, owner, action, payload, request_key):
        self.runtime._project(project_id, owner)
        payload = self._bound_payload(payload)
        service = self._voice_service()
        if action != "voice_start":
            call_id = payload.get("call_id")
            with closing(self.control.store.connect("chat_access")) as db:
                if call_id:
                    row = db.execute("SELECT * FROM voice_calls WHERE owner=? AND call_id=?",
                        (owner, call_id)).fetchone()
                else:
                    row = db.execute("SELECT * FROM voice_calls WHERE owner=? AND project_id=? "
                        "AND start_request_key=?", (owner, project_id, payload.get("start_request_key"))).fetchone()
            if row is None or (row["project_id"], row["space_id"], row["conversation_id"]) != (
                    project_id, payload["space_id"], payload["conversation_id"]):
                raise Denied("voice call is outside the project/Space/conversation")
        return service.voice_dispatch(project_id, owner, action, payload, request_key)

    def attachment_dispatch(self, project_id, owner, action, payload, request_key):
        self.runtime._project(project_id, owner)
        payload = self._bound_payload(payload)
        service = self._attachment_store()
        upload_id = payload.get("upload_id")
        if action == "attachment_upload_status" and not upload_id:
            target_key = payload.get("request_key")
            with closing(self.control.store.connect("shell")) as db:
                request = db.execute("SELECT * FROM shell_requests WHERE owner=? AND project_id=? AND request_key=?",
                    (owner, project_id, target_key)).fetchone()
                binding = db.execute("SELECT upload_id FROM canvas_shell_upload_bindings "
                    "WHERE owner=? AND project_id=? AND begin_key=?", (owner, project_id, target_key)).fetchone()
            if request is None or not request["action"].startswith("attachment_"):
                raise Denied("attachment request is outside the authenticated project")
            intent = _decode(request["protected_payload"])
            if (intent.get("space_id"), intent.get("conversation_id")) != (payload["space_id"], payload["conversation_id"]):
                raise Denied("attachment request is outside the selected conversation")
            upload_id = intent.get("upload_id") or (binding["upload_id"] if binding else None)
            if not upload_id:
                if request["protected_result"]:
                    value = _decode(request["protected_result"])["value"]
                    return {**value, "state": "complete" if value.get("attachments") else value.get("state", "uncertain")}
                return {"state": "uncertain", "request_key": target_key, "automatic_retry": False,
                    "reason": "attachment request has no confirmed storage receipt"}
            payload = {**payload, "upload_id": upload_id}
        if action not in {"attachment_register", "attachment_upload_begin"}:
            with closing(self.control.store.connect("shell")) as db:
                binding = db.execute("SELECT * FROM canvas_shell_upload_bindings WHERE upload_id=? AND owner=?",
                    (upload_id, owner)).fetchone()
            if binding is None or (binding["project_id"], binding["space_id"], binding["conversation_id"]) != (
                    project_id, payload["space_id"], payload["conversation_id"]):
                raise Denied("upload is outside the project/Space/conversation")
        value = service.attachment_dispatch(project_id, owner, action, payload, request_key)
        if action == "attachment_upload_begin":
            with closing(self.control.store.connect("shell")) as db, db:
                db.execute("INSERT INTO canvas_shell_upload_bindings VALUES(?,?,?,?,?,?)",
                    (value["upload_id"], owner, project_id, payload["space_id"], payload["conversation_id"], request_key))
        return value

    @staticmethod
    def _bound_payload(payload):
        # Brisa stores bindings from the canonical conversation. Nexo adds
        # admission IDs to the server-only callback envelope, never the browser.
        conversation = dict(payload["conversation"])
        conversation.update({name: payload[name] for name in
            ("run_id", "work_item_id", "operation_id") if name in payload})
        return {**payload, "conversation": conversation}

    def validate_attachments(self, project_id, owner, conversation, refs):
        self.runtime._project(project_id, owner)
        value = self._attachment_store().validate_attachments(owner, refs, project_id=project_id)
        for attachment in value["attachments"]:
            if (attachment.get("space_id"), attachment.get("conversation_id")) != (
                    conversation["space_id"], conversation["conversation_id"]):
                raise Denied("attachment is outside the selected Space/conversation")
        # Keep durable refs in the protected outbox. Bytes are resolved again
        # on execution, never put into a renderer-selected command or path.
        return list(refs)

    def attachment_bytes(self, project_id, owner, conversation, refs):
        self.validate_attachments(project_id, owner, conversation, refs)
        return [self._attachment_store().read_bytes(owner, ref) for ref in refs]
