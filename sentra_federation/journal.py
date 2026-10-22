"""Private admission journal.

This file records intents and receipts on the installation. It is not served
on the peer channel and it is not a second Control Plane.
"""
from __future__ import annotations

import json
import os
import threading
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from sentra_core.conversations import _decode, _encode, _lease


class Journal:
    def __init__(self, directory, *, owner, node_id):
        if not owner or not node_id:
            raise ValueError("journal installation identity required")
        self.owner, self.node_id = owner, node_id
        self._path = Path(directory) / "journal.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._locked():
            if not self._path.exists():
                self._dump({"intents": {}, "messages": [], "projections": [], "peers": {}})
            else:
                # Upgrade the previous plaintext projection in place. It never
                # granted authority and cannot restore confirmed peer pins.
                self._dump(self._load())

    @contextmanager
    def _locked(self):
        with self._lock, _lease(self._path.with_suffix(".lock")):
            yield

    def peers(self):
        with self._locked():
            return self._load().get("peers", {})

    def save_peer(self, peer):
        with self._locked():
            data = self._load()
            peers = data.setdefault("peers", {})
            if peer["node_id"] not in peers and len(peers) >= 128:
                raise RuntimeError("federation peer quota reached")
            peers[peer["node_id"]] = dict(peer)
            self._dump(data)

    @property
    def artifact_dir(self):
        path = self._path.parent / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get(self, intent_id):
        with self._locked():
            record = self._load()["intents"].get(intent_id)
            return None if record is None else json.loads(json.dumps(record))

    def intents(self):
        with self._locked():
            return json.loads(json.dumps(self._load()["intents"]))

    def put(self, record):
        intent_id = record["intent_id"]
        with self._locked():
            data = self._load()
            if intent_id not in data["intents"] and len(data["intents"]) >= 1000:
                raise RuntimeError("federation journal quota reached")
            data["intents"][intent_id] = record
            self._dump(data)
        return json.loads(json.dumps(record))

    def mark(self, intent_id, state, **fields):
        with self._locked():
            data = self._load()
            record = data["intents"][intent_id]
            record["state"] = state
            record["automatic_resend"] = False
            record["executed"] = False
            record.update(fields)
            self._dump(data)
            return json.loads(json.dumps(record))

    def add_message(self, record):
        with self._locked():
            data = self._load()
            data["messages"].append(record)
            if len(data["messages"]) > 256:
                data["messages"] = data["messages"][-256:]
            self._dump(data)

    def messages(self, peer):
        with self._locked():
            return [dict(item) for item in self._load()["messages"] if item.get("peer") == peer]

    def add_projection(self, record):
        with self._locked():
            data = self._load()
            key = record["scope_key"]
            data["projections"] = [item for item in data["projections"] if item.get("scope_key") != key]
            data["projections"].append(record)
            if len(data["projections"]) > 64:
                raise RuntimeError("federation projection quota reached")
            self._dump(data)

    def projection(self, scope_key):
        with self._locked():
            for item in self._load()["projections"]:
                if item.get("scope_key") == scope_key:
                    return dict(item)
        return None

    def _load(self):
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if value.get("schema") == 2:
            protected = _decode(value["protected"])
            if (protected.get("owner"), protected.get("node_id")) != (self.owner, self.node_id):
                raise PermissionError("journal belongs to another installation owner")
            return protected["data"]
        if set(value) - {"intents", "messages", "projections"}:
            raise PermissionError("invalid legacy federation journal")
        return value

    def _dump(self, data):
        protected = _encode({"owner": self.owner, "node_id": self.node_id, "data": data})
        raw = json.dumps({"schema": 2, "protected": protected}, separators=(",", ":")).encode("utf-8")
        descriptor, name = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=self._path.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            # Windows scanners/readers can briefly deny a rename after the
            # writer closed. Retry only publication of these same fsynced,
            # encrypted bytes while the existing journal lease remains held.
            # This never repeats a peer request or re-executes an intent.
            deadline = time.monotonic() + .75
            while True:
                try:
                    temp.replace(self._path)
                    break
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) not in {5, 32, 33} or time.monotonic() >= deadline:
                        raise
                    time.sleep(.025)
        finally:
            temp.unlink(missing_ok=True)
