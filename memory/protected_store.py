"""Scoped protected memory on the selected Control Plane; knowledge only."""
import math
import re
import time

from sentra_quality.protected_state import digest, canonical, StateConflict


class ProtectedMemoryStore:
    def __init__(self, state):
        self.state = state.scoped("selo.memory")

    @staticmethod
    def _key(namespace, key, context):
        if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", v) for v in (namespace, key)):
            raise ValueError("invalid scoped memory key")
        return "entry:" + digest(context.request.work_item_id) + ":" + namespace + ":" + key

    def put(self, *, namespace, key, body, expected_revision, context, ttl_s=30 * 86400):
        record_key = self._key(namespace, key, context)
        if (not isinstance(body, dict) or len(canonical(body).encode()) > 65536
                or type(ttl_s) not in {int, float} or not math.isfinite(ttl_s) or not 1 <= ttl_s <= 365 * 86400):
            raise ValueError("invalid memory body/validity")
        value = {"body": body, "body_sha256": digest(body), "namespace": namespace, "key": key,
                 "operation_id": context.receipt.operation_id, "run_id": context.receipt.run_id,
                 "work_item_id": context.request.work_item_id,
                 "expires_at": self.state.clock() + ttl_s, "updated_at": self.state.clock()}
        revision = self.state.put(record_key, value, expected_revision=expected_revision)
        return {"key": key, "namespace": namespace, "revision": revision,
                "body_sha256": value["body_sha256"], "authorizes_effects": False}

    def get(self, *, namespace, key, context):
        row = self.state.get(self._key(namespace, key, context))
        if row is None or row["value"]["expires_at"] <= self.state.clock():
            raise FileNotFoundError("memory absent or expired")
        return {**row["value"], "revision": row["revision"], "authorizes_effects": False}

    def delete(self, *, namespace, key, expected_revision, context):
        with self.state.transaction() as tx:
            tx.delete(self._key(namespace, key, context), expected_revision=expected_revision)
        return {"deleted": True, "authorizes_effects": False}

    def list(self, *, namespace, context, limit=100, offset=0):
        self._key(namespace, "page", context)
        if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or offset < 0:
            raise ValueError("invalid memory page")
        values = [{**row["value"], "revision": row["revision"]}
                  for _, row in self.state.records("entry:" + digest(context.request.work_item_id) + ":" + namespace + ":")
                  if row["value"]["expires_at"] > self.state.clock()]
        return {"items": values[offset:offset + limit], "total": len(values), "authorizes_effects": False}
