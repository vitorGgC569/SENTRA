"""Isolated two-process Federation evidence; never targets an installed service.

Run: python -B tests/qa/astra_federation_task.py
The explicit typed task executes real central workspace-file adapters. This is
not model inference, a Windows guest installation, or installed-Setup proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sentra_federation.errors import FederationDenied, FederationUncertain
from sentra_federation.executor import verify_result_receipt
from sentra_federation.gateway import PeerGateway
from sentra_federation.identity import InstallationIdentity
from sentra_federation.task_runtime import FederatedMachineExecutor
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.machine_host import MachineHost

PROJECT = "federation-qa-project"
SCOPE = {"kind": "project", "project_id": PROJECT}
CONTENT = "Entrega remota persistente — ação e 漢字.\n"


def _grant(control, owner, capability, agent=None):
    return control.authorization.grant(owner, principal_type="agent" if agent else "user",
        principal_id=agent or owner, capability=capability,
        scope_type="workspace" if agent else "project", scope_id=PROJECT)


def _gateway(root, label, *, executable=False):
    owner = "qa-" + label
    control = ControlPlaneService.from_store(root / "control")
    run = control.durable.create_run(owner, workspace=PROJECT, idempotency_key="qa-root")
    if not run.get("idempotent_replay"):
        for cap in ("federation.delegate", "federation.review"):
            _grant(control, owner, cap)
    host = runtime = None
    if executable:
        control.ensure_agent(run["run_id"], owner, agent_id="qa-remote-dot", role="worker")
        workspace = root / "workspace"; workspace.mkdir(exist_ok=True)
        host = MachineHost(control, owner=owner)
        host.configure_workspace_files(workspace_id=PROJECT, workspace_root=str(workspace), agent_id="qa-remote-dot")
        if not run.get("idempotent_replay"):
            for cap in ("workspace:file.read", "workspace:file.write"):
                _grant(control, owner, cap, "qa-remote-dot")
        runtime = FederatedMachineExecutor(host, project_id=PROJECT, agent_id="qa-remote-dot", run_id=run["run_id"])
    peer = PeerGateway(identity=InstallationIdentity.load_or_create(root / "identity"),
        control=control, owner=owner, principal_id=owner, journal_dir=root / "journal", task_executor=runtime)
    peer.listen()
    return control, peer, host


def worker(root):
    control, peer, host = _gateway(root, "receiver", executable=True)
    def emit(value):
        print(json.dumps(value, ensure_ascii=True), flush=True)
    emit({"ready": True, "port": peer.bound_port, "node_id": peer.identity.node_id, "pid": os.getpid()})
    try:
        for line in sys.stdin:
            p = json.loads(line); action = p["action"]
            if action == "stop":
                emit({"stopped": True}); break
            if action == "hello":
                peer.exchange_hello("127.0.0.1", p["port"])
                value = {"code": peer.confirmation_code_for(p["node_id"])}
            elif action == "confirm":
                value = peer.confirm(p["node_id"], p["code"])
            elif action == "snapshot":
                intent = peer.journal.get(p["intent_id"])
                receipt = (intent or {}).get("receipt") or {}
                work = control.work_item_info(receipt["work_item_id"], peer.owner) if receipt else {}
                file = root / "workspace" / "entrega.txt"
                value = {"receipt": receipt, "work_item_state": work.get("state"),
                    "step_states": [control.work_item_info(wi, peer.owner)["state"] for wi in receipt.get("step_work_item_ids", [])],
                    "file_sha256": hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None,
                    "file_mtime_ns": file.stat().st_mtime_ns if file.exists() else None,
                    "operations": control.durable.list_operations(receipt["run_id"], peer.owner)["page"]["total"] if receipt else None}
            elif action == "revoke_write":
                grants = control.authorization.list_grants(peer.owner)["items"]
                for grant in grants:
                    if grant["capability"] == "workspace:file.write" and grant.get("revoked_at") is None:
                        control.authorization.revoke(grant["grant_id"], peer.owner)
                value = {"revoked": True}
            else:
                raise ValueError("unknown QA control action")
            emit(value)
    finally:
        peer.close(); host.close(); control.durable.close()


class Worker:
    def __init__(self, root):
        self.output = queue.Queue()
        self.process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(root)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def read():
            for line in self.process.stdout:
                self.output.put(line)
        threading.Thread(target=read, daemon=True).start()
        self.ready = self.receive()
        if not self.ready.get("ready"):
            raise RuntimeError("QA receiver did not start")

    def receive(self):
        try:
            return json.loads(self.output.get(timeout=30))
        except queue.Empty as exc:
            state = self.process.poll()
            raise RuntimeError("QA receiver reply missing; exit=" + str(state)) from exc

    def call(self, action, **params):
        self.process.stdin.write(json.dumps({"action": action, **params}) + "\n")
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        if self.process.poll() is None:
            self.call("stop")
            self.process.wait(timeout=15)
        if self.process.returncode != 0:
            raise RuntimeError("isolated QA receiver failed: " + self.process.stderr.read()[-2000:])


def run(output, *, lose_review_receipt=False):
    output.mkdir(parents=True, exist_ok=True)
    state = output / ("state-" + uuid.uuid4().hex)
    state.mkdir()
    left_root = state / "sender"; left_root.mkdir()
    right_root = state / "receiver"; right_root.mkdir()
    control, left, _ = _gateway(left_root, "sender")
    right = Worker(right_root)
    request = {"schema": 1, "objective": "Criar e verificar uma entrega no workspace remoto",
        "steps": [
            {"machine_kind": "workspace-files", "capability_id": "workspace:file.write",
             "arguments": {"action": "write", "path": "entrega.txt", "content": CONTENT}},
            {"machine_kind": "workspace-files", "capability_id": "workspace:file.read",
             "arguments": {"action": "read", "path": "entrega.txt"}},
        ]}
    try:
        left.exchange_hello("127.0.0.1", right.ready["port"])
        code = right.call("hello", port=left.bound_port, node_id=left.identity.node_id)["code"]
        left.confirm(right.ready["node_id"], code)
        assert right.call("confirm", node_id=left.identity.node_id, code=code)["paired"] is True
        intent_id = "intent-" + uuid.uuid4().hex
        left.drop_before_receipt = True
        try:
            left.delegate(right.ready["node_id"], SCOPE, request, intent_id=intent_id)
            raise AssertionError("induced receipt loss was not observed")
        except FederationUncertain:
            pass
        until = time.monotonic() + 30
        while True:
            before = right.call("snapshot", intent_id=intent_id)
            if before["receipt"].get("result_ready"): break
            assert time.monotonic() < until, before
            time.sleep(.1)
        pid_before = right.ready["pid"]
        right.close()
        right = Worker(right_root)
        assert right.ready["pid"] != pid_before
        left.drop_before_receipt = False
        # Re-observe the exact certificate at the new listening port. Pairing
        # is retained; this handshake does not submit or continue any task.
        left.exchange_hello("127.0.0.1", right.ready["port"])
        settled = left.reconcile(right.ready["node_id"], intent_id)
        assert settled["disposition"] == "found", settled
        receipt = left.journal.get(intent_id)["receipt"]
        assert verify_result_receipt(receipt, objective=request, scope=SCOPE) == receipt["artifact_sha256"]
        if lose_review_receipt:
            left.drop_before_receipt = True
            try:
                left.review(right.ready["node_id"], intent_id)
                raise AssertionError("induced review receipt loss was not observed")
            except FederationUncertain:
                pass
            finally:
                left.drop_before_receipt = False
            assert left.journal.get(intent_id)["state"] == "REVIEW_UNCERTAIN"
            until = time.monotonic() + 30
            while True:
                reviewed = right.call("snapshot", intent_id=intent_id)
                if reviewed["receipt"].get("review_approved"): break
                assert time.monotonic() < until, reviewed
                time.sleep(.1)
            review_pid = right.ready["pid"]
            right.close()
            right = Worker(right_root)
            assert right.ready["pid"] != review_pid
            left.exchange_hello("127.0.0.1", right.ready["port"])
            observed_review = left.reconcile(right.ready["node_id"], intent_id)
            assert observed_review["verified"] is True and observed_review["executed"] is True
            closed = left.journal.get(intent_id)["receipt"]
            assert closed["review_approved"] is True
            assert verify_result_receipt(closed, objective=request, scope=SCOPE) == receipt["artifact_sha256"]
        else:
            closed = left.review(right.ready["node_id"], intent_id)
        after = right.call("snapshot", intent_id=intent_id)
        assert after["work_item_state"] == "COMPLETED" and after["step_states"] == ["COMPLETED", "COMPLETED"]
        assert before["file_mtime_ns"] == after["file_mtime_ns"]
        assert before["operations"] == after["operations"] == 3
        assert after["file_sha256"] == hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
        try:
            left.delegate(right.ready["node_id"], SCOPE, request, intent_id=intent_id)
            raise AssertionError("existing intent was replayed")
        except FederationUncertain:
            pass
        right.call("revoke_write")
        refused = json.loads(json.dumps(request)); refused["steps"][0]["arguments"]["path"] = "blocked.txt"
        denied = left.delegate(right.ready["node_id"], SCOPE, refused)
        assert denied["result_ready"] is False and not right_root.joinpath("workspace", "blocked.txt").exists()
        report = {"schema": 1, "producer": "two independent Python processes and Control Planes",
            "installed_setup": False, "windows_guest": False, "model_inference": False,
            "mutual_tls": True, "signed_frames": True, "paired_identity_survived_process_restart": True,
            "receipt_loss_reconciled": True, "automatic_resend": False, "file_rewritten_after_restart": False,
            "review_receipt_loss_reconciled": lose_review_receipt,
            "receiver_restarted_after_review_commit": lose_review_receipt,
            "review_resubmitted": False,
            "task_operation_id": receipt["operation_id"], "work_item_id": receipt["work_item_id"],
            "step_operation_ids": receipt["step_operation_ids"], "step_work_item_ids": receipt["step_work_item_ids"],
            "artifact_id": receipt["artifact_id"], "artifact_sha256": receipt["artifact_sha256"],
            "file_sha256": after["file_sha256"], "work_item_state": closed["work_item_state"],
            "capability_revocation_denied_new_write": True, "operations_for_completed_task": after["operations"],
            "evidence_state": str(state), "timestamp_unix": time.time()}
        path = output / "report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        right.close(); left.close(); control.durable.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp" / "astra-federation-qa")
    parser.add_argument("--lose-review-receipt", action="store_true")
    args = parser.parse_args()
    worker(args.worker) if args.worker else run(args.output, lose_review_receipt=args.lose_review_receipt)
