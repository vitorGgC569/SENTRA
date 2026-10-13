"""Selo read guard: trusted origins/gates/costs from the SAME Control Plane.

PostgreSQL locks namespaces in sorted order and relevant rows in one native
transaction. This module neither transitions WorkItems nor manufactures proof.
"""
from contextlib import contextmanager
import json
import re
from pathlib import Path

from .protected_state import identifier, digest


class CentralReferences:
    def __init__(self, *, control, owner, workspace_id, workspace_root):
        self.control, self.owner, self.workspace_id = control, owner, workspace_id
        root = Path(workspace_root)
        if not root.is_absolute():
            raise ValueError("absolute host-derived workspace_root required")
        self.workspace_root = root.resolve()
        self.store = control.store

    def root_matches(self, workspace):
        if not isinstance(workspace, str) or not workspace:
            return False
        path = Path(workspace)
        return path.is_absolute() and path.resolve() == self.workspace_root

    def work_matches(self, work):
        metadata = work.get("metadata")
        if metadata is None and "metadata_json" in work:
            metadata = json.loads(work["metadata_json"] or "{}")
        return isinstance(metadata, dict) and metadata.get("workspace_id") == self.workspace_id

    @contextmanager
    def guard(self):
        if self.store.backend == "postgres":
            db = self.store.connect("governance")
            try:
                db._begin()
                for ns in sorted(("durable", "governance")):
                    db.raw.execute("SELECT pg_advisory_xact_lock(%s)", (self.store.lock_key(ns),))
                db._locked = True
                yield lambda ns, sql, params: db.raw.execute(
                    sql.replace("{table}", identifier(self.store.schema(ns)) + ".")
                    .replace("?", "%s"), params)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
        else:
            # Local SQLite snapshots remain projections; effect admission/fence
            # is revalidated by the enclosing CentralEffectContext.
            connections = {ns: self.store.connect(ns) for ns in ("durable", "governance")}
            try:
                for db in connections.values():
                    db.execute("BEGIN")
                yield lambda ns, sql, params: connections[ns].execute(sql.replace("{table}", ""), params)
            finally:
                for db in connections.values():
                    db.rollback()
                    db.close()

    def snapshot(self, operation_id, *, terminal=False):
        suffix = " FOR UPDATE" if self.store.backend == "postgres" else ""
        with self.guard() as query:
            operation = query("durable", "SELECT * FROM {table}operations WHERE operation_id=? AND owner=?" + suffix,
                              (operation_id, self.owner)).fetchone()
            if operation is None:
                raise FileNotFoundError("central operation not found")
            operation = dict(operation)
            progress = json.loads(operation["progress_json"] or "{}")
            work_id = progress.get("work_item_id")
            if not work_id:
                raise PermissionError("central operation has no trusted WorkItem binding")
            work = query("governance", "SELECT * FROM {table}work_items WHERE work_item_id=? AND owner=?" + suffix,
                         (work_id, self.owner)).fetchone()
            run = query("durable", "SELECT * FROM {table}runs WHERE run_id=? AND owner=?" + suffix,
                        (operation["run_id"], self.owner)).fetchone()
            if (work is None or run is None or work["run_id"] != operation["run_id"]
                    or not self.root_matches(run["workspace"]) or not self.work_matches(dict(work))):
                raise PermissionError("central origin workspace/Run/WorkItem mismatch")
            if terminal and operation["state"] not in {"SUCCEEDED", "FAILED"}:
                raise PermissionError("learning requires a completed central operation")
            if terminal and not re.fullmatch(r"[0-9a-f]{64}", str(operation.get("intent_sha256") or "")):
                raise PermissionError("learning/evaluation requires a real fenced central receipt")
            costs = query("governance", "SELECT cost_event_id,actual_cost,input_tokens,output_tokens,model,provider "
                          "FROM {table}cost_events WHERE operation_id=? AND owner=?" + suffix,
                          (operation_id, self.owner)).fetchall()
            execution = json.loads(work["execution_state_json"] or "{}")
            evidence = json.loads(operation.get("result_json") or "null")
            return {"origin": {"operation_id": operation_id, "run_id": operation["run_id"],
                "work_item_id": work_id, "intent_sha256": operation.get("intent_sha256")},
                "workspace_id": self.workspace_id, "state": operation["state"],
                "effect_started": progress.get("effect_started") is True,
                "principal_id": progress.get("principal_id"),
                "capability_id": progress.get("capability_id"),
                "required_capabilities": json.loads(work["required_capabilities_json"] or "[]"),
                "quality_gate": execution.get("quality_gate"),
                "costs": [dict(row) for row in costs],
                "evidence_sha256": evidence.get("evidence_sha256", digest(evidence)) if isinstance(evidence, dict) else digest(evidence),
                "updated_at": operation["updated_at"],
                "latency_ms": max(0, (operation["updated_at"] - operation["started_at"]) * 1000)}

    def transcript(self, operation_id, artifact_id):
        snapshot = self.snapshot(operation_id, terminal=True)
        info = self.control.durable.artifact_info(artifact_id, self.owner)
        if (info["run_id"], info["operation_id"]) != (snapshot["origin"]["run_id"], operation_id):
            raise PermissionError("transcript artifact outside central origin")
        raw = self.control.durable.read_artifact(artifact_id, max_bytes=256_000)
        if info["metadata"].get("kind") == "machine-result":
            stored = self.control.durable.operation_status(operation_id, self.owner).get("result") or {}
            if stored.get("evidence_artifact_id") != artifact_id:
                raise PermissionError("transcript must use the recorded central result artifact")
            result = self.result(operation_id)
            transcript = result.evidence.get("transcript")
            if not isinstance(transcript, str):
                raise PermissionError("central result has no original transcript")
        else:
            if info["metadata"].get("os_protected") is True:
                from sentra_remote.secrets import unprotect_secret
                raw = unprotect_secret(raw.decode()).encode()
            transcript = raw.decode("utf-8")
        if len(transcript.encode()) > 256_000:
            raise ValueError("original transcript exceeds bounded capture")
        return snapshot, transcript, {"artifact_id": artifact_id, "sha256": info["sha256"]}

    def result(self, operation_id):
        """Existing receipt + retained protected evidence; no reserve/dispatch."""
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        authority = CentralDurableIntentAuthority(self.control.durable)
        receipt = authority.receipt_for_operation(operation_id, self.owner)
        result = authority.result_for_receipt(receipt)
        if result is None:
            raise FileNotFoundError("verified central result artifact unavailable")
        return result

    def artifact(self, operation_id, artifact_id, *, max_bytes):
        snapshot = self.snapshot(operation_id, terminal=True)
        info = self.control.durable.artifact_info(artifact_id, self.owner)
        if (info["run_id"], info["operation_id"]) != (snapshot["origin"]["run_id"], operation_id):
            raise PermissionError("artifact outside central result scope")
        if info["metadata"].get("kind") == "machine-result":
            stored = self.control.durable.operation_status(operation_id, self.owner).get("result") or {}
            if stored.get("evidence_artifact_id") != artifact_id:
                raise PermissionError("artifact differs from recorded central result")
            result = self.result(operation_id)
            raw = json.dumps(dict(result.evidence), ensure_ascii=False, allow_nan=False).encode()
            if len(raw) > max_bytes: raise ValueError("decoded central result exceeds artifact limit")
            return raw
        raw = self.control.durable.read_artifact(artifact_id, max_bytes=max_bytes)
        if info["metadata"].get("os_protected") is True:
            from sentra_remote.secrets import unprotect_secret
            raw = unprotect_secret(raw.decode()).encode()
        if len(raw) > max_bytes: raise ValueError("decoded artifact exceeds configured limit")
        return raw
