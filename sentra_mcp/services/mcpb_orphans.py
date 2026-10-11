"""Docker orphan ownership ledger — contract for coordinator's sandbox.

Records an operation's unique container claim *before* launch, binds the
immutable Docker container ID after inspect, and authorizes cleanup only on
exact matching labels, image identity and stale central operation receipt.
No arbitrary PID/label-prefix cleanup or new Docker process is initiated here.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from pathlib import Path

_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER = re.compile(r"[0-9a-f]{64}\Z")


class DockerOwnershipDenied(PermissionError):
    pass


class MCPBDockerOwnership:
    def __init__(self, control):
        self.control = control
        self.store = control.store
        with self.store.connect("plugin_bundle") as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mcpb_docker_ownership(
                operation_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                workspace TEXT NOT NULL, run_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL, container_name TEXT NOT NULL UNIQUE,
                image_id TEXT NOT NULL, claim TEXT NOT NULL,
                container_id TEXT, state TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)""")

    def _operation(self, owner, workspace, run_id, work_item_id, operation_id):
        row = self.control.durable.operation_status(operation_id, owner)
        run = self.control.durable.run_status(run_id, owner)
        work = self.control.work_item_info(work_item_id, owner)
        if (row["run_id"] != run_id or
                row["progress"].get("work_item_id") != work_item_id or
                work["run_id"] != run_id or
                Path(run["workspace"]).resolve() != Path(workspace).resolve()):
            raise DockerOwnershipDenied("Docker orphan ownership mismatches central Operation")
        return row

    def prepare(self, *, owner, workspace, run_id, work_item_id, operation_id,
                image_id):
        if not _IMAGE.fullmatch(image_id or ""):
            raise DockerOwnershipDenied("immutable Docker image ID required")
        self._operation(owner, workspace, run_id, work_item_id, operation_id)
        root = str(Path(workspace).resolve(strict=True))
        name = "sentra-mcpb-" + secrets.token_hex(15)
        claim = secrets.token_hex(32)
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT 1 FROM mcpb_docker_ownership WHERE operation_id=?",
                                  (operation_id,)).fetchone()
            if previous:
                raise DockerOwnershipDenied("Docker Operation already reserved, never relaunch")
            db.execute("INSERT INTO mcpb_docker_ownership VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (operation_id, owner, root, run_id, work_item_id, name,
                        image_id, claim, None, "PREPARED", time.time(), time.time()))
        # Operator-controlled Docker launch MUST include these exact labels.
        return {"container_name": name, "image_id": image_id,
                "docker_labels": {"sentra.owner_claim": claim,
                                  "sentra.operation_id": operation_id},
                "operation_id": operation_id, "needs_durable_fence": True}

    def _row(self, owner, operation_id):
        with self.store.connect("plugin_bundle") as db:
            row = db.execute("SELECT * FROM mcpb_docker_ownership WHERE "
                             "operation_id=? AND owner=?", (operation_id, owner)).fetchone()
        if not row:
            raise DockerOwnershipDenied("Docker claim not registered for this owner")
        return dict(row)

    @staticmethod
    def _matching(row, inspect):
        if not isinstance(inspect, dict):
            raise DockerOwnershipDenied("Docker inspect evidence required")
        labels = (inspect.get("Config") or {}).get("Labels") or {}
        names = str(inspect.get("Name", "")).lstrip("/")
        image = inspect.get("Image")
        cid = inspect.get("Id")
        if (not isinstance(cid, str) or not _CONTAINER.fullmatch(cid)
                or cid != row["container_id"] and row["container_id"] is not None
                or names != row["container_name"] or image != row["image_id"]
                or labels.get("sentra.owner_claim") != row["claim"]
                or labels.get("sentra.operation_id") != row["operation_id"]):
            raise DockerOwnershipDenied("Docker container identity/labels/Image mismatch")
        return cid

    def bind(self, owner, operation_id, inspect):
        row = self._row(owner, operation_id)
        if row["state"] != "PREPARED":
            raise DockerOwnershipDenied("Docker claim already used")
        cid = self._matching(row, inspect)
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE mcpb_docker_ownership SET container_id=?,"
                "state='BOUND',updated_at=? WHERE operation_id=? AND owner=? "
                "AND state='PREPARED' AND container_id IS NULL",
                (cid, time.time(), operation_id, owner)).rowcount
            if changed != 1:
                raise DockerOwnershipDenied("Docker bind race or conflicting ownership")
        return {"container_id": cid, "bound": True}

    def cleanup_candidate(self, *, owner, operation_id, inspect,
                          approved=False, min_age_seconds=30):
        """Host supplies fresh Docker inspect; returns exact-id removal ticket.

        No executable is called and no signal is sent. Coordinator must re-
        inspect immediately before any exact-ID docker container rm --force.
        """
        row = self._row(owner, operation_id)
        if approved is not True or type(min_age_seconds) is not int or min_age_seconds < 30:
            raise DockerOwnershipDenied("operator approval and minimum stale age required")
        if row["state"] not in ("PREPARED", "BOUND"):
            raise DockerOwnershipDenied("Docker claim no longer cleanup-eligible")
        if time.time() - row["created_at"] < min_age_seconds:
            raise DockerOwnershipDenied("Docker Operation still inside lease grace")
        cid = self._matching(row, inspect)
        operation = self.control.durable.operation_status(operation_id, owner)
        if operation["state"] in ("RUNNING", "ACCEPTED") and time.time() - row["updated_at"] < min_age_seconds:
            raise DockerOwnershipDenied("active Docker Operation must not be terminated")
        return {"container_id": cid, "expected_image_id": row["image_id"],
                "expected_name": row["container_name"], "requires_fresh_inspect": True,
                "authorized_cleanup": True, "performed": False}

    def mark_cleaned(self, owner, operation_id, *, observed_absent=False):
        if observed_absent is not True:
            raise DockerOwnershipDenied("Docker exact container absence not proven")
        with self.store.connect("plugin_bundle") as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE mcpb_docker_ownership SET state='CLEANED',"
                "updated_at=? WHERE owner=? AND operation_id=? AND state IN ('PREPARED','BOUND','CLEANING')",
                (time.time(), owner, operation_id)).rowcount
        if changed != 1:
            raise DockerOwnershipDenied("Docker cleanup state conflict")
        return {"cleaned": True, "replayed_effect": False}


    async def reconcile_stopped_owned(
        self, *, owner, workspace, source_operation_id, work_item_id, agent_id,
        cleanup_operation_id, idempotency_key, approved_by_host,
        min_age_seconds=60,
    ):
        """Physically remove ONE stopped, proven-owned Docker container by exact ID.

        Source Operation must be terminal; a distinct, newly granted central
        Operation authorizes cleanup. Failed/uncertain physical observations
        remain unresolved, and no automatic retry of an ambiguous rm occurs.
        """
        import asyncio
        import json
        from sentra_interop.central import CentralInteropAdapter
        from sentra_interop.mcp_stdio import _minimal_windows_runtime_env
        from sentra_runtime.contracts import Machine, Capability, OperationRequest
        from .mcpb_sandbox import _trusted_docker

        row = self._row(owner, source_operation_id)
        root = str(Path(workspace).resolve(strict=True))
        if (row["workspace"] != root or row["work_item_id"] != work_item_id
                or row["state"] not in ("BOUND", "CLEANED") or not row["container_id"]
                or cleanup_operation_id == source_operation_id
                or not callable(approved_by_host)):
            raise DockerOwnershipDenied("Docker cleanup source/approval not admitted")
        source = self._operation(owner, root, row["run_id"], work_item_id,
                                 source_operation_id)
        if source["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}:
            raise DockerOwnershipDenied("Docker source Operation is not terminal")
        work = self.control.work_item_info(work_item_id, owner)
        if work["assignee_agent_id"] != agent_id:
            raise DockerOwnershipDenied("Docker cleanup must retain WorkItem assignee")
        self.control._agent_from_run(
            self.control.durable.run_status(row["run_id"], owner), agent_id)
        machine = Machine("mcpb-cleanup-" + row["container_name"], "mcpb", owner,
                          (Capability("mcp:container-cleanup",
                                      "Exact-ID stopped Docker container cleanup"),))
        gate = CentralInteropAdapter(control=self.control,
            run_id=row["run_id"], owner=owner, machine=machine).protocol_gate()
        request = OperationRequest(
            cleanup_operation_id, agent_id, machine.machine_id,
            "mcp:container-cleanup", work_item_id, idempotency_key,
            {"source_operation_id": source_operation_id, "container_id": row["container_id"]})
        if not (await gate.decision(request)).allowed:
            raise DockerOwnershipDenied("Docker cleanup WorkItem grant denied")
        def consent():
            try:
                return approved_by_host(owner, root, source_operation_id,
                                        row["container_id"], cleanup_operation_id) is True
            except Exception:
                return False
        if not consent():
            raise DockerOwnershipDenied("Docker cleanup operator approval missing")
        docker = _trusted_docker()

        async def cli(*argv, timeout=8):
            proc = await asyncio.create_subprocess_exec(
                docker, *argv, cwd=root, env=_minimal_windows_runtime_env(),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            try:
                out, error = await asyncio.wait_for(proc.communicate(), timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise DockerOwnershipDenied("Docker reconciliation timed out")
            if len(out) > 100_000:
                raise DockerOwnershipDenied("Docker inspection response oversized")
            return proc.returncode, out, error[:2048]

        async def effect():
            gate.physical_context(request).checkpoint()
            if (not consent() or self._row(owner, source_operation_id)["state"] != "BOUND"
                    or not (await gate.decision(request)).allowed):
                raise DockerOwnershipDenied("Docker cleanup authorization revised")
            rc, raw, _ = await cli("inspect", row["container_id"])
            if rc != 0:
                raise DockerOwnershipDenied("Docker exact-id inspect unavailable")
            try:
                inspected = json.loads(raw)[0]
            except (ValueError, IndexError, TypeError):
                raise DockerOwnershipDenied("Docker inspect evidence invalid") from None
            candidate = self.cleanup_candidate(
                owner=owner, operation_id=source_operation_id, inspect=inspected,
                approved=True, min_age_seconds=min_age_seconds)
            if (candidate["container_id"] != row["container_id"]
                    or (inspected.get("State") or {}).get("Running") is not False):
                raise DockerOwnershipDenied("Docker container still running or altered")
            gate.physical_context(request).checkpoint()
            # Re-inspect immediately before exact-ID rm, never a container name.
            rc, raw, _ = await cli("inspect", row["container_id"])
            if rc != 0:
                raise DockerOwnershipDenied("Docker container disappeared before removal")
            fresh = json.loads(raw)[0]
            self._matching(row, fresh)
            if (fresh.get("State") or {}).get("Running") is not False:
                raise DockerOwnershipDenied("Docker container became active")
            # Exclusive durable claim: two distinct cleanup Operations must
            # not concurrently send docker rm to the same container.
            with self.store.connect("plugin_bundle") as db:
                db.execute("BEGIN IMMEDIATE")
                claimed = db.execute(
                    "UPDATE mcpb_docker_ownership SET state='CLEANING',updated_at=? "
                    "WHERE operation_id=? AND owner=? AND state='BOUND' AND container_id=?",
                    (time.time(), source_operation_id, owner,
                     row["container_id"])).rowcount
            if claimed != 1:
                raise DockerOwnershipDenied("Docker cleanup already owned by another Operation")
            rc, _, _ = await cli("container", "rm", row["container_id"])
            if rc != 0:
                raise DockerOwnershipDenied("Docker container removal unconfirmed")
            # Nonzero inspect alone is ambiguous (daemon unavailable). Require
            # a healthy daemon and a specific missing-object response.
            daemon_rc, daemon_os, _ = await cli("info", "--format", "{{.OSType}}")
            if daemon_rc or daemon_os.strip() != b"linux":
                raise DockerOwnershipDenied("Docker daemon unavailable after removal")
            rc, _, detail = await cli("inspect", row["container_id"])
            missing_id = row["container_id"].encode("ascii")
            detail = detail.lower()
            if (rc == 0 or not (b"no such object: " + missing_id in detail
                                  or b"no such container: " + missing_id in detail)):
                raise DockerOwnershipDenied("Docker exact-ID absence not proven")
            self.mark_cleaned(owner, source_operation_id, observed_absent=True)
            gate.physical_context(request).checkpoint()
            return {"source_operation_id": source_operation_id,
                    "container_id": row["container_id"], "removed": True,
                    "owned_stopped_container": True, "unrelated_processes_affected": 0}

        return await gate.execute(request, effect, timeout=25)


    async def confirm_uncertain_absence(
        self, *, owner, workspace, source_operation_id, work_item_id, agent_id,
        verification_operation_id, idempotency_key, approved_by_host,
    ):
        """Post-crash read-only reconciliation for a CLEANING Docker claim.

        Does not replay docker rm, docker stop, or a tool effect. A separately
        granted central operation and fresh daemon inspect confirm absence.
        """
        import asyncio
        from sentra_interop.central import CentralInteropAdapter
        from sentra_interop.mcp_stdio import _minimal_windows_runtime_env
        from sentra_runtime.contracts import Machine, Capability, OperationRequest
        from .mcpb_sandbox import _trusted_docker

        row = self._row(owner, source_operation_id)
        root = str(Path(workspace).resolve(strict=True))
        if (row["workspace"] != root or row["work_item_id"] != work_item_id
                or row["state"] not in ("CLEANING", "CLEANED")
                or not row["container_id"]
                or verification_operation_id == source_operation_id
                or not callable(approved_by_host)):
            raise DockerOwnershipDenied("uncertain cleanup recovery not admitted")
        source = self._operation(owner, root, row["run_id"], work_item_id,
                                 source_operation_id)
        work = self.control.work_item_info(work_item_id, owner)
        if (source["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNCERTAIN"}
                or work["assignee_agent_id"] != agent_id):
            raise DockerOwnershipDenied("uncertain cleanup source or assignee mismatch")
        self.control._agent_from_run(
            self.control.durable.run_status(row["run_id"], owner), agent_id)
        machine = Machine("mcpb-cleanup-" + row["container_name"], "mcpb", owner,
                          (Capability("mcp:container-cleanup", "Verify exact-ID absence"),))
        gate = CentralInteropAdapter(control=self.control, run_id=row["run_id"],
                                     owner=owner, machine=machine).protocol_gate()
        intent = OperationRequest(
            verification_operation_id, agent_id, machine.machine_id,
            "mcp:container-cleanup", work_item_id, idempotency_key,
            {"source_operation_id": source_operation_id,
             "container_id": row["container_id"], "verify_absence_only": True})
        if not (await gate.decision(intent)).allowed:
            raise DockerOwnershipDenied("absent-container reconciliation grant denied")
        def consent():
            try:
                return approved_by_host(owner, root, source_operation_id,
                                        row["container_id"], verification_operation_id) is True
            except Exception:
                return False
        if not consent():
            raise DockerOwnershipDenied("absent-container owner consent required")
        docker = _trusted_docker()

        async def effect():
            gate.physical_context(intent).checkpoint()
            if (not consent() or not (await gate.decision(intent)).allowed
                    or self._row(owner, source_operation_id)["state"] != "CLEANING"):
                raise DockerOwnershipDenied("recovery state or authorization changed")
            async def probe(*args):
                proc = await asyncio.create_subprocess_exec(
                    docker, *args, cwd=root, env=_minimal_windows_runtime_env(),
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                try:
                    out, err = await asyncio.wait_for(proc.communicate(), timeout=8)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise DockerOwnershipDenied("Docker absence probe timed out")
                if len(out) > 4096 or len(err) > 4096:
                    raise DockerOwnershipDenied("Docker absence evidence oversized")
                return proc.returncode, out, err.lower()
            healthy, platform, _ = await probe("info", "--format", "{{.OSType}}")
            if healthy != 0 or platform.strip() != b"linux":
                raise DockerOwnershipDenied("Docker recovery daemon unhealthy")
            status, _, err = await probe("inspect", row["container_id"])
            cid = row["container_id"].encode("ascii")
            if (status == 0 or not (b"no such object: " + cid in err
                                   or b"no such container: " + cid in err)):
                raise DockerOwnershipDenied("uncertain Docker container still present or unknown")
            self.mark_cleaned(owner, source_operation_id, observed_absent=True)
            gate.physical_context(intent).checkpoint()
            return {"container_id": row["container_id"], "confirmed_absent": True,
                    "docker_remove_calls": 0, "source_operation_id": source_operation_id}
        return await gate.execute(intent, effect, timeout=20)
