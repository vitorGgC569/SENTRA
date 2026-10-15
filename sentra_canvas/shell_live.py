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
from .shell_stream import content_window
from sentra_core.model_prose import prose_prefix

class ShellLivePreviews:
    def __init__(self, directory, *, on_change=None, on_batch=None):
        self._directory = Path(directory).resolve()
        self._lock = threading.RLock()
        self._current = {}
        self._on_change = on_change
        self._on_batch = on_batch
        self._batch_pending = None

    def begin(self, *, project_id, conversation_id, operation_id, space_id=None):
        fd, filename = tempfile.mkstemp(prefix="model-preview-", suffix=".jsonl", dir=self._directory)
        # Reopening every native fragment is costly on Windows. Keep the
        # securely-created file handle for this turn, never reopen a page-
        # supplied path, and refuse replacement/truncation on every poll.
        try:
            identity = os.fstat(fd)
            reader = os.fdopen(fd, "rb", buffering=0)
        except BaseException:
            # fdopen may already have taken ownership before failing. Keep
            # the original error while attempting both cleanup operations.
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                Path(filename).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        record = {
            "project_id": project_id, "conversation_id": conversation_id, "space_id": space_id,
            "operation_id": operation_id, "nonce": secrets.token_hex(16),
            "path": Path(filename), "offset": 0, "pending": b"", "text": "",
            "phase": "generating", "done": False, "content_revision": 0,
            "started": time.monotonic(), "timings_ms": {},
            "reader": reader, "file_identity": (identity.st_dev, identity.st_ino),
        }
        with self._lock:
            previous = self._current.get(conversation_id)
            self._current[conversation_id] = record
            if previous is not None:
                # A late finally from the old operation must never touch the
                # new turn or publish an interruption under its identity.
                self._discard(previous)
        return record

    def _discard(self, record):
        record["done"] = True
        try:
            record["reader"].close()
        finally:
            try:
                record["path"].unlink(missing_ok=True)
            except OSError:
                pass

    def environment(self, record):
        return {"SENTRA_SHELL_PREVIEW_PATH": str(record["path"]),
                "SENTRA_SHELL_PREVIEW_NONCE": record["nonce"]}

    def update(self, record):
        with self._lock:
            if self._current.get(record["conversation_id"]) is not record or record["done"]:
                return
            path = record["path"]
            try:
                info = path.stat()
                size = info.st_size
                if (path.is_symlink() or (info.st_dev, info.st_ino) != record["file_identity"]
                        or size > 8_000_000 or size < record["offset"]):
                    record["phase"] = "preview_unavailable"
                    self._publish(record)
                    return
                if size == record["offset"]:
                    self._publish(record)
                    return
                stream = record["reader"]
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
                        # Keep useful prose visible while the next tool round thinks.
                        record['replace_on_delta'] = True
                        record['timings_ms'].setdefault('provider_submitted', elapsed)
                    elif value.get('phase') == 'response_complete':
                        record['activity'] = 'Confirmando entrega'
                        record['timings_ms']['response_complete'] = elapsed
                    elif value.get('phase') == 'coordinating':
                        record['activity'] = 'Coordenando'
                        record['timings_ms'].setdefault('coordinating', elapsed)
                    elif value.get('phase') == 'delivery_uncertain':
                        record['activity'] = 'Entrega incerta. Não reenvie.'
                        record['timings_ms']['delivery_uncertain'] = elapsed
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
                if record.pop('replace_on_delta', False):
                    record['text'] = ''
                    record['content_revision'] += 1
                combined = record["text"] + value["text"]
                # The input file/writer budgets remain enforced. Keep the full
                # observed round for the protected journal; only views window it.
                record["text"] = combined
            self._publish(record)

    @staticmethod
    def _snapshot(record, *, include_full=False):
        text = prose_prefix(record["text"])
        content = text if include_full else content_window(text)
        return {"status": record["phase"], "operation_id": record["operation_id"],
                "content": content, "activity": record.get("activity", "Aguardando modelo"),
                "partial": True, "authoritative": False, "closes_trio": False,
                "truncated": content != text,
                "content_revision": record["content_revision"],
                "timings_ms": dict(record['timings_ms'])}

    def _publish(self, record):
        if self._on_change is not None:
            snapshot = self._snapshot(record, include_full=True)
            if snapshot != record.get("published"):
                if self._batch_pending is not None:
                    self._batch_pending.append((record, snapshot))
                    return
                if self._on_change(record, snapshot) is not False:
                    record["published"] = snapshot

    def pump(self):
        """Ingest even when no renderer is attached to this conversation."""
        with self._lock:
            if self._on_batch is None:
                for record in list(self._current.values()):
                    self.update(record)
                return
            pending = []
            self._batch_pending = pending
            try:
                for record in list(self._current.values()):
                    self.update(record)
            finally:
                self._batch_pending = None
            if pending:
                result = self._on_batch(pending)
                accepted = result if isinstance(result, (list, tuple)) else [result is not False] * len(pending)
                for (record, snapshot), success in zip(pending, accepted):
                    if success:
                        record["published"] = snapshot

    def has_active(self, project_id=None, conversation_id=None):
        with self._lock:
            if conversation_id is not None:
                record = self._current.get(conversation_id)
                return record is not None and record["project_id"] == project_id
            return bool(self._current)

    def view(self, project_id, conversation_id):
        with self._lock:
            record = self._current.get(conversation_id)
            if record is None or record["project_id"] != project_id:
                return {"status": "idle"}
            self.update(record)
            return self._snapshot(record)

    def close(self, record):
        with self._lock:
            try:
                self.update(record)
                if self._on_change is not None and self._current.get(record["conversation_id"]) is record:
                    snapshot = {**self._snapshot(record, include_full=True), "status": "interrupted",
                                "activity": "Entrega incerta. Não reenvie."}
                    self._on_change(record, snapshot)
            finally:
                if self._current.get(record["conversation_id"]) is record:
                    self._current.pop(record["conversation_id"], None)
                self._discard(record)

    def close_all(self):
        with self._lock:
            try:
                for record in list(self._current.values()):
                    self.close(record)
            finally:
                # An exceptional callback must not leak the remaining handles.
                for record in list(self._current.values()):
                    self._current.pop(record["conversation_id"], None)
                    self._discard(record)
