"""Read-only native model preview. Never a transcript, receipt, or authority.

Per-turn files are created by the Canvas owner, only for its native CLI child.
The renderer can only poll scoped ephemeral content; no replay or execution.
"""
from __future__ import annotations
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

class ShellLivePreviews:
    def __init__(self, directory):
        self._directory = Path(directory).resolve()
        self._lock = threading.RLock()
        self._current = {}

    def begin(self, *, project_id, conversation_id, operation_id):
        fd, filename = tempfile.mkstemp(prefix="model-preview-", suffix=".jsonl", dir=self._directory)
        os.close(fd)
        record = {
            "project_id": project_id, "conversation_id": conversation_id,
            "operation_id": operation_id, "nonce": secrets.token_hex(16),
            "path": Path(filename), "offset": 0, "pending": b"", "text": "",
            "phase": "generating", "done": False,
            "started": time.monotonic(), "timings_ms": {},
        }
        with self._lock:
            self._current[conversation_id] = record
        return record

    def environment(self, record):
        return {"SENTRA_SHELL_PREVIEW_PATH": str(record["path"]),
                "SENTRA_SHELL_PREVIEW_NONCE": record["nonce"]}

    def update(self, record):
        with self._lock:
            if self._current.get(record["conversation_id"]) is not record or record["done"]:
                return
            path = record["path"]
            try:
                if path.is_symlink() or path.stat().st_size > 512000:
                    record["phase"] = "preview_unavailable"
                    return
                with path.open("rb") as stream:
                    stream.seek(record["offset"])
                    chunk = stream.read(65536)
                    record["offset"] = stream.tell()
            except OSError:
                return
            parts = (record["pending"] + chunk).split(b"\n")
            record["pending"] = parts.pop()[:8192]
            for line in parts:
                if len(line) > 8192:
                    continue
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if type(value) is not dict or value.get("nonce") != record["nonce"]:
                    continue
                if value.get("kind") == "activity":
                    elapsed = round((time.monotonic() - record['started']) * 1000)
                    if value.get('phase') == 'provider_submitted':
                        record['activity'] = 'Aguardando ChatGPT'
                        record['text'] = ''  # A new provider round supersedes its earlier tool prose.
                        record['timings_ms'].setdefault('provider_submitted', elapsed)
                    elif value.get('phase') == 'response_complete':
                        record['activity'] = 'Confirmando entrega'
                        record['timings_ms']['response_complete'] = elapsed
                    if value.get("phase") == "tool_call":
                        name = str(value.get("tool", ""))[:48]
                        record["activity"] = "Executando ferramenta " + name
                    elif value.get("phase") == "tool_result":
                        record["activity"] = "Resultado da ferramenta recebido"
                    continue
                if value.get("kind") != "delta" or not isinstance(value.get("text"), str):
                    continue
                if value['text'].strip():
                    record["activity"] = "Recebendo resposta"
                    record['timings_ms'].setdefault('first_fragment', round((time.monotonic() - record['started']) * 1000))
                # Show at most 32K of incomplete prose; never claim finality.
                record["text"] = (record["text"] + value["text"])[:32768]

    def view(self, project_id, conversation_id):
        with self._lock:
            record = self._current.get(conversation_id)
            if record is None or record["project_id"] != project_id:
                return {"status": "idle"}
            self.update(record)
            return {"status": record["phase"], "operation_id": record["operation_id"],
                    "content": record["text"].split('[[', 1)[0], "activity": record.get("activity", "Aguardando modelo"),
                    "partial": True, "authoritative": False, "timings_ms": dict(record['timings_ms'])}

    def close(self, record):
        with self._lock:
            if self._current.get(record["conversation_id"]) is record:
                self._current.pop(record["conversation_id"], None)
            record["done"] = True
        try:
            record["path"].unlink(missing_ok=True)
        except OSError:
            pass
