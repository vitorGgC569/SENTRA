"""Peer gateway for one SENTRA installation.

Two installations recognize each other only after both confirm the same
pairing code. Messages, canvas projections and delegation requests then go
to this installation's Control Plane. A VPN address, a discovered peer and a
paired identity do not authorize execution. Intents that lose their receipt
stay uncertain and are not sent again.

The listener binds to loopback or a documented private network. The channel
is mutual TLS on a single websocket path. SQLite is not served.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import threading
import uuid

from sentra_collab.authority import CollaborationDenied, validate_presentation
from sentra_collab.scope import ScopeDenied, parse_scope
from sentra_collab.teams import TeamDenied
from sentra_mcp.services.control_plane import ControlPlaneService

from .bind import BindRefused, assert_destination, assert_private_bind, host_class
from .errors import FederationDenied, FederationUncertain
from .executor import assert_unresolved_receipt, execute_delegation, verify_result_receipt
from .journal import Journal
from .protocol import (
    FrameReader,
    accept_key,
    canonical,
    confirmation_code,
    decode_frame,
    encode_frame,
    message_target,
    node_id_for,
    reject_secrets,
    signed_frame,
    verify_known,
)
from .identity import fingerprint_of_pem

INTENT = re.compile(r"^intent-[0-9a-f]{32}$")
_INSTALLER_MARKERS = ("installer/windows", "installer\\windows", "sentra-installer")


def _refuse_image_installer(value):
    """The click-and-install image belongs to Latch. This gateway does not run it."""
    if not isinstance(value, str):
        return
    lowered = value.lower()
    if any(marker in lowered for marker in _INSTALLER_MARKERS):
        raise FederationDenied("image installer belongs to Latch")


def new_intent():
    return "intent-" + uuid.uuid4().hex


class PeerGateway:
    def __init__(self, *, identity, control, owner, principal_id, journal_dir,
                 principal_type="user", teams=None, documented_networks=(), clock=None,
                 bound_project_id=None, task_executor=None):
        if not isinstance(control, ControlPlaneService):
            raise TypeError("the installation Control Plane is required")
        if not owner or not principal_id:
            raise ValueError("owner and principal required")
        if principal_type not in {"user", "agent"}:
            raise FederationDenied("invalid principal type")
        self.identity = identity
        self.control = control
        self.owner = owner
        self.principal_id = principal_id
        self.principal_type = principal_type
        self.bound_project_id = bound_project_id
        from .task_runtime import FederatedMachineExecutor
        if task_executor is not None and (not isinstance(task_executor, FederatedMachineExecutor)
                or task_executor.control is not control or task_executor.owner != owner
                or bound_project_id not in (None, task_executor.project_id)):
            raise ValueError("task executor must share the installation authority")
        self.task_executor = task_executor
        self.teams = teams
        self.documented = tuple(documented_networks)
        self.clock = clock or __import__("time").time
        self.journal = Journal(journal_dir, owner=owner, node_id=identity.node_id)
        self.peers = self.journal.peers()
        for peer in self.peers.values():
            fingerprint, _ = fingerprint_of_pem(peer.get("cert_pem"))
            if fingerprint != peer.get("fingerprint") or node_id_for(fingerprint) != peer.get("node_id"):
                raise FederationDenied("stored peer identity binding rejected")
            # Persisted pairing is not evidence of current connectivity.
            peer["transport"] = "disconnected"
        self.candidates = {}
        self.drop_before_send = False
        self.drop_before_receipt = False
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(8)
        self._stop = threading.Event()
        self._sock = None
        self._thread = None
        self._server_ctx = None
        self.bound_host = None
        self.bound_port = None
        self._host_class = None

    def discover(self, address, port):
        """Record a VPN or private address. Reachability is not a grant."""
        host, port = assert_destination(address, port, self.documented)
        record = {
            "address": host,
            "port": port,
            "state": "discovered",
            "paired": False,
            "execution_authorized": False,
            "vpn_is_authorization": False,
            "automatic_resend": False,
            "network_reachable": False,
        }
        with self._lock:
            self.candidates[f"{host}:{port}"] = record
        return dict(record)

    def listen(self, host="127.0.0.1", port=0):
        if self._thread is not None:
            raise FederationDenied("peer gateway is already listening")
        normalized = assert_private_bind(host, self.documented)
        if type(port) is not int or not 0 <= port <= 65535:
            raise BindRefused("invalid peer port")
        family = socket.AF_INET6 if ":" in normalized else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((normalized, port))
        sock.listen(8)
        sock.settimeout(0.3)
        self._sock = sock
        self.bound_host = sock.getsockname()[0]
        self.bound_port = sock.getsockname()[1]
        self._host_class = host_class(normalized, self.documented)
        self._server_ctx = self._server_context()
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept, name="sentra-peer", daemon=True)
        self._thread.start()
        return {"host": self.bound_host, "port": self.bound_port, "host_class": self._host_class}

    def close(self):
        self._stop.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2)

    def exchange_hello(self, address, port):
        host, port = assert_destination(address, port, self.documented)
        frame = signed_frame(self.identity, {
            "kind": "hello",
            "to": "bootstrap",
            "body": {"cert_pem": self.identity.cert_pem, "fingerprint": self.identity.fingerprint},
        }, self.clock)
        response, tls_fingerprint = self._request(host, port, frame, pinned_pem=None)
        fingerprint, _cert = fingerprint_of_pem(response.get("body", {}).get("cert_pem", ""))
        if tls_fingerprint != fingerprint or response.get("from") != node_id_for(fingerprint):
            raise FederationDenied("identity binding")
        if response.get("body", {}).get("fingerprint") != fingerprint:
            raise FederationDenied("identity binding")
        verify_known(response, response["body"]["cert_pem"], clock=self.clock)
        if response.get("body", {}).get("execution_authorized") is not False:
            raise FederationDenied("discovery tried to authorize execution")
        self._remember(response["from"], fingerprint, response["body"]["cert_pem"], host, port)
        return self._public_peer(self._peer(response["from"]))

    def confirmation_code_for(self, node_id):
        peer = self._peer(node_id)
        return confirmation_code(self.identity.fingerprint, peer["fingerprint"])

    def confirm(self, node_id, code):
        peer = self._peer(node_id)
        if peer.get("revoked"):
            raise FederationDenied("pairing revoked")
        expected = confirmation_code(self.identity.fingerprint, peer["fingerprint"])
        if not isinstance(code, str) or code != expected:
            raise FederationDenied("confirmation code mismatch")
        with self._lock:
            peer["local_confirmed"] = True
            self._refresh(peer)
        response = self._call(peer, "pair.confirm", {"code": code}, intent_id=new_intent(), admit=False)
        if response.get("local_confirmed") is True:
            with self._lock:
                peer["remote_confirmed"] = True
                self._refresh(peer)
        return self._public_peer(peer)

    def revoke(self, node_id):
        peer = self._peer(node_id)
        with self._lock:
            peer["revoked"] = True
            peer["pair_state"] = "revoked"
            peer["cert_pinned"] = False
            peer["execution_authorized"] = False
            self.journal.save_peer(peer)
        self._cancel_peer_tasks(node_id)
        try:
            if peer.get("transport") == "up":
                self._call(peer, "revoke", {}, intent_id=new_intent(), admit=False)
        except (FederationDenied, FederationUncertain, OSError):
            pass
        return self._public_peer(peer)

    def link_lost(self, node_id):
        peer = self._peer(node_id)
        with self._lock:
            peer["transport"] = "disconnected"
        for intent_id, record in self.journal.intents().items():
            if record.get("peer") != node_id or record.get("state") not in {"RECORDED", "DISPATCHED"}:
                continue
            self._lose_operation(record.get("operation_id"), intent_id)
            self.journal.mark(intent_id, "UNCERTAIN")
        return self._public_peer(peer)

    def restore_link(self, node_id):
        """Mark the transport usable again. Does not resend an intent."""
        peer = self._peer(node_id)
        if peer.get("revoked"):
            raise FederationDenied("pairing revoked")
        with self._lock:
            peer["transport"] = "up"
        return self._public_peer(peer)

    def send_chat(self, node_id, text, scope, *, intent_id=None, vpn_member=False):
        del vpn_member
        return self._deliver(
            node_id, "chat", "federation.conversation", scope, intent_id,
            self._text(text), settle_remote="recorded",
        )

    def project_canvas(self, node_id, scope, presentation, *, intent_id=None, vpn_member=False):
        del vpn_member
        try:
            clean = validate_presentation(presentation)
        except CollaborationDenied as exc:
            raise FederationDenied("canvas projection is presentation only") from exc
        return self._deliver(
            node_id, "canvas", "federation.canvas.project", scope, intent_id,
            clean, settle_remote="recorded",
        )

    def delegate(self, node_id, scope, objective, *, intent_id=None, vpn_member=False):
        del vpn_member
        objective = self._task(objective)
        return self._deliver(
            node_id, "delegate", "federation.delegate", scope, intent_id,
            objective, settle_remote="admitted",
        )

    def review(self, node_id, intent_id, decision="approved"):
        """Accept a Dot result that is already in review. Does not run the task again."""
        peer = self._ready(node_id)
        intent = self.journal.get(intent_id)
        if intent is None or not (intent.get("receipt") or {}).get("result_ready"):
            raise FederationDenied("nothing to review")
        if intent.get("peer") != node_id:
            raise FederationDenied("intent belongs to another peer")
        self._require_grant("federation.review", intent["scope"]["project_id"])
        self._require_membership(intent["scope"])
        if intent["receipt"].get("executed") is True:
            return intent["receipt"]
        if intent["state"] in {"REVIEW_DISPATCHED", "REVIEW_UNCERTAIN"}:
            raise FederationUncertain("observe the existing review before submitting another decision")
        if decision != "approved":
            raise FederationDenied("review decision refused")
        # Reserve before network I/O so even abrupt sender termination cannot
        # turn a lost review response into an automatic second decision.
        self.journal.mark(intent_id, "REVIEW_DISPATCHED")
        try:
            receipt = self._call(
                peer, "review", {"intent_id": intent_id, "decision": decision},
                intent_id=intent_id, admit=False,
            )
        except FederationUncertain:
            self.journal.mark(intent_id, "REVIEW_UNCERTAIN")
            raise
        except FederationDenied:
            self.journal.mark(intent_id, intent["state"])
            raise
        verify_result_receipt(receipt, objective=intent.get("task"), scope=intent["scope"])
        if receipt.get("executed") is not True or receipt.get("work_item_state") != "COMPLETED":
            raise FederationDenied("review did not close the dot result")
        if receipt.get("artifact_sha256") != intent["receipt"].get("artifact_sha256"):
            raise FederationDenied("review changed the artifact")
        operation = self.control.durable.operation_status(intent["operation_id"], self.owner)
        if operation["state"] == "SUCCEEDED":
            self._move(operation, "SUCCEEDED", intent_id, result={
                "intent_id": intent_id, "executed": True, "verified": True, "automatic_resend": False,
                "artifact_id": receipt.get("artifact_id"), "artifact_sha256": receipt.get("artifact_sha256"),
            })
        self.journal.mark(intent_id, "CLOSED", receipt=receipt, executed=True)
        return receipt

    def reconcile(self, node_id, intent_id):
        peer = self._peer(node_id)
        intent = self.journal.get(intent_id)
        if intent is None:
            raise FederationDenied("unknown intent")
        if intent.get("peer") != node_id:
            raise FederationDenied("intent belongs to another peer")
        scope = intent.get("scope")
        capability = {"delegate": "federation.delegate", "chat": "federation.conversation",
                      "canvas": "federation.canvas.project"}.get(intent.get("kind"))
        if capability is None:
            raise FederationDenied("unknown intent action")
        self._require_grant(capability, scope["project_id"])
        self._require_membership(scope)
        reviewing = intent["state"] in {"REVIEW_DISPATCHED", "REVIEW_UNCERTAIN"}
        if intent["state"] not in {"UNCERTAIN", "DISPATCHED"} and not reviewing:
            return {
                "disposition": "already_settled",
                "state": intent["state"],
                "executed": False,
                "automatic_resend": False,
            }
        if peer.get("transport") == "disconnected":
            raise FederationUncertain("peer disconnected; restore the link before reconciliation")
        saved_send, saved_receipt = self.drop_before_send, self.drop_before_receipt
        self.drop_before_send = False
        self.drop_before_receipt = False
        try:
            body = self._call(peer, "reconcile", {"intent_id": intent_id}, intent_id=intent_id, admit=False)
        finally:
            self.drop_before_send = saved_send
            self.drop_before_receipt = saved_receipt
        disposition = body.get("disposition")
        operation = self.control.durable.operation_status(intent["operation_id"], self.owner)
        receipt = body.get("receipt") or {}
        executed = False
        if disposition == "pending":
            # A known intent without a final receipt is never proof of absence.
            # Observation may be repeated; no task or prompt is dispatched.
            return {"disposition": "pending", "executed": False, "verified": False,
                    "automatic_resend": False, "remote_state": body.get("remote_state", "UNCERTAIN")}
        if reviewing:
            # The sender's delivery Operation already succeeded. Observation
            # repairs only its review projection, never repeats a decision.
            if disposition != "found" or operation["state"] != "SUCCEEDED":
                raise FederationUncertain("review outcome requires observation; no decision is repeated")
            verify_result_receipt(receipt, objective=intent.get("task"), scope=scope)
            previous = intent["receipt"]
            if any(receipt.get(key) != previous.get(key) for key in
                   ("intent_id", "operation_id", "work_item_id", "artifact_id", "artifact_sha256")):
                raise FederationDenied("review observation changed the original result")
            executed = receipt.get("executed") is True
            if executed:
                self._move(operation, "SUCCEEDED", intent_id, result={
                    "intent_id": intent_id, "executed": True, "verified": True, "automatic_resend": False,
                    "artifact_id": receipt["artifact_id"], "artifact_sha256": receipt["artifact_sha256"],
                })
            self.journal.mark(intent_id, "CLOSED" if executed else "ADMITTED", receipt=receipt, executed=executed)
            return {"disposition": "found", "executed": executed, "verified": True,
                    "review_pending": not executed, "automatic_resend": False}
        if disposition == "found" and operation["state"] == "UNCERTAIN":
            if intent.get("kind") != "delegate":
                if (receipt.get("intent_id") != intent_id or receipt.get("recorded") is not True
                        or receipt.get("executed") is not False or receipt.get("automatic_resend") is not False
                        or receipt.get("remote_state") != "SUCCEEDED"):
                    raise FederationDenied("recorded conversation/projection receipt did not verify")
                self._move(operation, "SUCCEEDED", intent_id, result={"intent_id": intent_id,
                    "recorded": True, "executed": False, "verified": True, "automatic_resend": False})
                self.journal.mark(intent_id, "RECONCILED", receipt=receipt)
                return {"disposition": "found", "executed": False, "verified": True, "automatic_resend": False}
            if receipt.get("result_ready") is True:
                try:
                    verify_result_receipt(receipt, objective=intent.get("task"), scope=intent.get("scope"))
                except FederationDenied as exc:
                    self._move(operation, "FAILED", intent_id, error={
                        "executed": False, "verified": False, "automatic_resend": False,
                        "reason": str(exc)[:160],
                    })
                    self.journal.mark(intent_id, "FAILED")
                    raise
                executed = receipt.get("executed") is True
                self._move(operation, "SUCCEEDED", intent_id, result={
                    "intent_id": intent_id,
                    "executed": executed,
                    "verified": True,
                    "automatic_resend": False,
                    "admission": "reconciled",
                    "remote_operation_id": receipt.get("operation_id"),
                    "result_sha256": receipt.get("result_sha256"),
                })
                self.journal.mark(intent_id, "RECONCILED", receipt=receipt)
            else:
                assert_unresolved_receipt(receipt, objective=intent.get("task"), scope=intent.get("scope"))
                if receipt.get("remote_state") == "UNCERTAIN":
                    self.journal.mark(intent_id, "UNCERTAIN", receipt=receipt)
                    return {"disposition": "pending", "executed": False, "verified": False,
                            "automatic_resend": False, "remote_state": "UNCERTAIN"}
                self._move(operation, "FAILED", intent_id, error={
                    "executed": False,
                    "verified": False,
                    "automatic_resend": False,
                    "reason": "dot result is not a completed delivery",
                })
                self.journal.mark(intent_id, "UNRESOLVED", receipt=receipt)
        elif disposition == "absent" and operation["state"] == "UNCERTAIN":
            self._move(operation, "FAILED", intent_id, error={
                "executed": False, "reason": "remote intent absent", "automatic_resend": False,
            })
            self.journal.mark(intent_id, "FAILED")
        elif disposition not in {"found", "absent"}:
            raise FederationDenied("reconciliation receipt rejected")
        return {"disposition": disposition, "executed": executed, "automatic_resend": False, "verified": executed}

    def history(self, node_id):
        self._peer(node_id)
        return self.journal.messages(node_id)

    def canvas_view(self, scope):
        scope = parse_scope(scope)
        return self.journal.projection(json.dumps(scope, sort_keys=True, separators=(",", ":")))

    def status(self):
        with self._lock:
            peers = [self._public_peer(peer) for peer in self.peers.values()]
            candidates = [dict(item) for item in self.candidates.values()]
        return {
            "node_id": self.identity.node_id,
            "fingerprint": self.identity.fingerprint,
            "port": self.bound_port,
            "host_class": self._host_class,
            "public_bind": False,
            "vpn_is_authorization": False,
            "execution_authorized": False,
            "physical_proof": False,
            "image_installer": False,
            "automatic_resend": False,
            "listening": bool(self._thread is not None and self._thread.is_alive()),
            "peers": peers,
            "candidates": candidates,
        }

    def _deliver(self, node_id, kind, capability, scope, intent_id, body, *, settle_remote):
        peer = self._ready(node_id)
        scope = parse_scope(scope)
        decision = self._require_grant(capability, scope["project_id"])
        self._require_membership(scope)
        intent_id = intent_id or new_intent()
        if not INTENT.fullmatch(intent_id):
            raise FederationDenied("invalid intent")
        if self.journal.get(intent_id) is not None:
            raise FederationUncertain("existing intent is not re-executed")
        objective = self._objective(kind, intent_id)
        self.journal.put({
            "intent_id": intent_id,
            "kind": kind,
            "peer": node_id,
            "state": "RECORDED",
            "executed": False,
            "automatic_resend": False,
            "grant_id": decision["grant_id"],
        })
        _run, item, operation = self._admit(
            kind=capability, intent_id=intent_id, project_id=scope["project_id"],
            objective=objective, metadata=self._metadata(intent_id, scope, node_id), settle=None,
        )
        self.journal.mark(
            intent_id, "DISPATCHED",
            operation_id=operation["operation_id"], work_item_id=item["work_item_id"],
            task=body if kind == "delegate" else None, scope=scope,
        )
        payload = {"scope": scope, "body": body, "settle": settle_remote}
        try:
            if self.drop_before_send:
                raise FederationUncertain("link lost before dispatch")
            receipt = self._call(peer, kind, payload, intent_id=intent_id, admit=False)
        except FederationUncertain:
            self._lose_operation(operation["operation_id"], intent_id)
            with self._lock:
                peer["transport"] = "disconnected"
            self.journal.mark(intent_id, "UNCERTAIN")
            raise
        except FederationDenied as exc:
            if operation.get("state") == "WAITING_EXTERNAL":
                self._move(operation, "FAILED", intent_id, error={
                    "executed": False, "automatic_resend": False, "reason": str(exc)[:160],
                })
            self.journal.mark(intent_id, "FAILED")
            raise
        executed = False
        if kind == "delegate":
            if receipt.get("result_ready") is True:
                try:
                    verify_result_receipt(receipt, objective=body, scope=scope)
                except FederationDenied as exc:
                    self._move(operation, "FAILED", intent_id, error={
                        "executed": False, "verified": False, "automatic_resend": False,
                        "reason": str(exc)[:160],
                    })
                    self.journal.mark(intent_id, "FAILED")
                    raise
            elif receipt.get("result_ready") is False:
                assert_unresolved_receipt(receipt, objective=body, scope=scope)
                uncertain = receipt.get("remote_state") == "UNCERTAIN"
                if uncertain:
                    self._lose_operation(operation["operation_id"], intent_id)
                self.journal.mark(intent_id, "UNCERTAIN" if uncertain else "UNRESOLVED", receipt=receipt)
                return receipt
            else:
                raise FederationDenied("dot result is not ready")
        elif receipt.get("executed") is not False or receipt.get("automatic_resend") is not False:
            self._lose_operation(operation["operation_id"], intent_id)
            self.journal.mark(intent_id, "UNCERTAIN")
            raise FederationUncertain("receipt did not prove the effect was withheld")
        self._move(operation, "SUCCEEDED", intent_id, result={
            "intent_id": intent_id,
            "executed": executed,
            "verified": True,
            "automatic_resend": False,
            "remote_operation_id": receipt.get("operation_id"),
            "remote_work_item_id": receipt.get("work_item_id"),
            "grant_id": receipt.get("grant_id"),
            "remote_state": receipt.get("remote_state"),
            "result_sha256": receipt.get("result_sha256"),
        })
        self.journal.mark(intent_id, "ADMITTED", receipt=receipt)
        if kind == "chat":
            self.journal.add_message({"peer": node_id, "text": body, "intent_id": intent_id, "scope": scope})
        if kind == "canvas":
            self.journal.add_projection({
                "scope_key": json.dumps(scope, sort_keys=True, separators=(",", ":")),
                "presentation": body,
                "intent_id": intent_id,
                "executed": False,
            })
        return receipt

    def _call(self, peer, kind, body, *, intent_id, admit):
        del admit
        frame = signed_frame(self.identity, {
            "kind": kind,
            "intent_id": intent_id,
            "to": peer["node_id"],
            "body": body,
        }, self.clock)
        response, tls_fingerprint = self._request(
            peer["address"], peer["port"], frame, pinned_pem=peer.get("cert_pem"),
        )
        if tls_fingerprint != peer["fingerprint"]:
            raise FederationDenied("peer certificate pin rejected")
        verify_known(response, peer["cert_pem"], clock=self.clock)
        if (response.get("to") != self.identity.node_id or response.get("kind") != kind
                or response.get("intent_id") != intent_id):
            raise FederationUncertain("peer response does not match this request; reconcile without resending")
        if response.get("from") != peer["node_id"] or response.get("ok") is not True:
            reason = (response.get("body") or {}).get("error") or "denied"
            raise FederationDenied(reason)
        response_body = response.get("body") or {}
        reject_secrets(response_body)
        return response_body

    def _request(self, host, port, frame, *, pinned_pem):
        if self.drop_before_receipt and pinned_pem is not None and frame.get("kind") != "hello":
            # The drop is applied after the bytes are written, below.
            pass
        raw = socket.create_connection((host, port), timeout=5)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        tls = self._client_context(pinned_pem).wrap_socket(raw, server_hostname=None)
        try:
            key = __import__("base64").b64encode(__import__("os").urandom(16)).decode("ascii")
            tls.sendall(
                (
                    "GET /sentra-peer HTTP/1.1\r\n"
                    "Host: sentra-peer\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode("ascii")
            )
            reader = FrameReader(tls)
            head = reader.read_until(b"\r\n\r\n", 4096)
            status_line = head.split(b"\r\n", 1)[0]
            if not status_line.startswith(b"HTTP/1.1 101"):
                raise FederationDenied("peer gateway refused the message channel")
            if accept_key(key) not in head.decode("ascii", "replace"):
                raise FederationDenied("websocket accept mismatch")
            der = tls.getpeercert(binary_form=True)
            if not der:
                raise FederationDenied("server certificate missing")
            tls_fingerprint = hashlib.sha256(der).hexdigest()
            if pinned_pem is not None:
                pinned_fingerprint, _cert = fingerprint_of_pem(pinned_pem)
                if tls_fingerprint != pinned_fingerprint:
                    raise FederationDenied("peer certificate pin rejected")
            tls.sendall(encode_frame(canonical(frame), mask=True))
            if self.drop_before_receipt and frame.get("kind") not in {"hello", "pair.confirm", "reconcile", "revoke"}:
                raise FederationUncertain("link lost before receipt")
            payload = decode_frame(reader, expect_mask=False)
            response = json.loads(payload.decode("utf-8"))
            if not isinstance(response, dict):
                raise FederationDenied("peer response rejected")
            return response, tls_fingerprint
        except FederationUncertain:
            raise
        except FederationDenied:
            raise
        except (OSError, ssl.SSLError, TimeoutError, json.JSONDecodeError, UnicodeError) as exc:
            raise FederationUncertain("link lost before receipt") from exc
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def _accept(self):
        while not self._stop.is_set():
            try:
                client, _address = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            if not self._slots.acquire(blocking=False):
                client.close()
                continue
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client):
        try:
            tls = self._server_ctx.wrap_socket(client, server_side=True)
        except ssl.SSLError:
            client.close()
            self._slots.release()
            return
        try:
            self._serve(tls)
        finally:
            try:
                tls.close()
            except OSError:
                pass
            self._slots.release()

    def _serve(self, tls):
        reader = FrameReader(tls)
        try:
            head = reader.read_until(b"\r\n\r\n", 4096)
        except (FederationDenied, FederationUncertain, OSError, UnicodeError):
            return
        if not self._accept_handshake(tls, head):
            return
        der = tls.getpeercert(binary_form=True)
        tls_fingerprint = hashlib.sha256(der).hexdigest() if der else None
        try:
            payload = decode_frame(reader, expect_mask=True)
            frame = json.loads(payload.decode("utf-8"))
            if frame.get("kind") != "hello" and tls_fingerprint is None:
                return
            response = self._dispatch(frame, tls_fingerprint)
            encoded = encode_frame(
                canonical(response),
                mask=False,
            )
            self._authorize_response(frame, response)
            tls.sendall(encoded)
        except (FederationDenied, FederationUncertain, OSError, ssl.SSLError, json.JSONDecodeError, UnicodeError, ValueError):
            return

    def _authorize_response(self, frame, response):
        """Last host-owned checkpoint before exposing persisted results.

        A late denial must close the link as uncertain. A signed denial saying
        executed=False would incorrectly erase effects that already happened.
        Reconnection only observes the original intent under current authority.
        """
        kind = frame.get("kind")
        if response.get("ok") is not True or kind not in {"delegate", "chat", "canvas", "review", "reconcile"}:
            return
        try:
            if self._stop.is_set():
                raise FederationDenied("installation is stopping")
            self._ready(frame["from"])
            intent = self.journal.get(frame["intent_id"])
            if kind == "reconcile" and intent is None:
                # An absence response has no task content or scope to authorize.
                if (response.get("body") or {}).get("disposition") != "absent":
                    raise FederationDenied("unknown reconciliation intent")
                return
            expected = "delegate" if kind == "review" else kind
            if kind == "reconcile" and intent:
                expected = intent.get("kind")
            capability = "federation.review" if kind == "review" else {
                "delegate": "federation.delegate", "chat": "federation.conversation",
                "canvas": "federation.canvas.project",
            }.get(expected)
            if capability is None:
                raise FederationDenied("unknown intent action")
            self._authorize_incoming_intent(frame, intent, capability, expected_kind=expected)
        except (FederationDenied, TeamDenied, CollaborationDenied, ScopeDenied) as exc:
            raise FederationUncertain("result delivery requires observation under current authority; no resend") from exc

    def _accept_handshake(self, tls, head):
        text = head.decode("ascii", "replace")
        lines = text.split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) < 2 or parts[0] != "GET":
            self._reject_http(tls)
            return False
        try:
            message_target(parts[1])
        except FederationDenied:
            self._reject_http(tls)
            return False
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        client_key = headers.get("sec-websocket-key")
        if not client_key or headers.get("upgrade", "").lower() != "websocket":
            self._reject_http(tls)
            return False
        tls.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n\r\n"
            ).encode("ascii")
        )
        return True

    @staticmethod
    def _reject_http(tls):
        try:
            tls.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass

    def _dispatch(self, frame, tls_fingerprint):
        if not isinstance(frame, dict) or frame.get("kind") == "hello":
            fingerprint, _cert = fingerprint_of_pem((frame.get("body") or {}).get("cert_pem", ""))
            verify_known(frame, frame["body"]["cert_pem"], clock=self.clock)
            if frame.get("from") != node_id_for(fingerprint):
                raise FederationDenied("identity binding")
            if tls_fingerprint is not None and tls_fingerprint != fingerprint:
                raise FederationDenied("identity binding")
            if frame.get("body", {}).get("execution_authorized") not in (None, False):
                raise FederationDenied("discovery tried to authorize execution")
            self._remember(frame["from"], fingerprint, frame["body"]["cert_pem"], None, None)
            return signed_frame(self.identity, {
                "kind": "hello",
                "to": frame["from"],
                "ok": True,
                "body": {
                    "cert_pem": self.identity.cert_pem,
                    "fingerprint": self.identity.fingerprint,
                    "execution_authorized": False,
                    "vpn_is_authorization": False,
                },
            }, self.clock)
        peer = self._peer_by_fingerprint(tls_fingerprint)
        if peer is None or peer["fingerprint"] != tls_fingerprint:
            raise FederationDenied("unknown peer")
        verify_known(frame, peer["cert_pem"], clock=self.clock)
        if frame.get("from") != peer["node_id"]:
            raise FederationDenied("identity binding")
        try:
            body = self._application(peer, frame)
            return signed_frame(self.identity, {
                "kind": frame["kind"],
                "intent_id": frame.get("intent_id"),
                "to": peer["node_id"],
                "ok": True,
                "body": body,
            }, self.clock)
        except (FederationDenied, TeamDenied, CollaborationDenied, ScopeDenied) as exc:
            # A duplicate may arrive after the original executed and its Grant
            # expired. Denying that request cannot prove the original had no
            # effects, nor may it reveal its protected result without authority.
            known = self.journal.get(frame.get("intent_id")) if frame.get("kind") == "delegate" else None
            if known and known.get("kind") == "delegate" and known.get("peer") == peer["node_id"]:
                raise FederationUncertain("existing delegation requires observation; no resend") from exc
            return signed_frame(self.identity, {
                "kind": frame["kind"] if frame.get("kind") in {"pair.confirm", "chat", "canvas", "delegate", "review", "reconcile", "revoke"} else "revoke",
                "intent_id": frame.get("intent_id") if INTENT.fullmatch(str(frame.get("intent_id") or "")) else new_intent(),
                "to": peer["node_id"],
                "ok": False,
                "body": {"error": str(exc)[:160], "executed": False, "automatic_resend": False},
            }, self.clock)

    def _application(self, peer, frame):
        if peer.get("revoked"):
            raise FederationDenied("pairing revoked")
        if peer.get("transport") == "disconnected":
            raise FederationDenied("peer disconnected")
        kind = frame.get("kind")
        intent_id = frame.get("intent_id")
        if kind != "pair.confirm" and (not isinstance(intent_id, str) or not INTENT.fullmatch(intent_id)):
            raise FederationDenied("invalid intent")
        if kind == "pair.confirm":
            return self._on_confirm(peer, frame)
        if peer.get("pair_state") != "paired":
            raise FederationDenied("not paired")
        if kind == "review":
            return self._on_review(frame)
        if kind == "revoke":
            with self._lock:
                peer["revoked"] = True
                peer["pair_state"] = "revoked"
                peer["cert_pinned"] = False
                self.journal.save_peer(peer)
            self._cancel_peer_tasks(peer["node_id"])
            return {"revoked": True, "executed": False, "automatic_resend": False}
        if kind == "reconcile":
            return self._on_reconcile(frame)
        if kind in {"chat", "canvas", "delegate"}:
            return self._on_delivery(peer, frame)
        raise FederationDenied("unknown message kind")

    def _on_confirm(self, peer, frame):
        code = (frame.get("body") or {}).get("code")
        expected = confirmation_code(self.identity.fingerprint, peer["fingerprint"])
        if code != expected:
            raise FederationDenied("confirmation code mismatch")
        with self._lock:
            peer["remote_confirmed"] = True
            self._refresh(peer)
            local_confirmed = peer["local_confirmed"]
            state = peer["pair_state"]
        return {
            "local_confirmed": local_confirmed,
            "remote_confirmed": True,
            "state": state,
            "execution_authorized": False,
            "automatic_resend": False,
        }

    def _on_review(self, frame):
        body = frame.get("body") or {}
        intent_id = body.get("intent_id") or frame.get("intent_id")
        if intent_id != frame.get("intent_id"):
            raise FederationDenied("review intent mismatch")
        if body.get("decision") != "approved":
            raise FederationDenied("review decision refused")
        intent = self.journal.get(intent_id)
        receipt = (intent or {}).get("receipt") or {}
        self._authorize_incoming_intent(frame, intent, "federation.review")
        if receipt.get("result_ready") is not True:
            raise FederationDenied("nothing to review")
        if receipt.get("executed") is True:
            return receipt
        def authorize_review():
            # Once review starts, a revoked authority can leave some decisions
            # committed. Preserve those decisions and reconcile, never replay I/O.
            try:
                if self._stop.is_set():
                    raise FederationDenied("installation is stopping")
                self._ready(frame["from"])
                self._authorize_incoming_intent(frame, intent, "federation.review")
            except (FederationDenied, TeamDenied, CollaborationDenied, ScopeDenied) as exc:
                raise FederationUncertain("review interrupted; observe the existing task without resending") from exc
        if receipt.get("executor") == "central-machine-task-v1":
            if self.task_executor is None:
                raise FederationDenied("installation task executor is not configured")
            verify_result_receipt(receipt, objective=intent["task"], scope=intent["request_scope"])
            # Check the stored artifact bytes, not only the peer projection.
            if self.control.durable.read_artifact(receipt["artifact_id"], max_bytes=65536) != receipt["result_document"].encode("utf-8"):
                raise FederationDenied("stored task artifact did not verify")
            self.task_executor.approve(receipt, actor_type=self.principal_type, actor_id=self.principal_id,
                                       authorize=authorize_review)
        authorize_review()
        work = self.control.work_item_info(receipt["work_item_id"], self.owner)
        if work["state"] == "IN_REVIEW":
            authorize_review()
            decided = self.control.governance.decide_policy_stage(
                receipt["work_item_id"], self.owner,
                actor_type=self.principal_type, actor_id=self.principal_id,
                decision="approved", comment="federation review",
                evidence=[receipt["artifact_id"]],
            )
            work = decided["work_item"]
        if work["state"] not in {"READY_FOR_PROMOTION", "COMPLETED"}:
            raise FederationDenied("review did not accept the dot result")
        if work["state"] != "COMPLETED":
            authorize_review()
            work = self.control.transition_work_item(
                receipt["work_item_id"], self.owner, "COMPLETED", reason="federated review accepted",
            )
        operation = self.control.durable.operation_status(receipt["operation_id"], self.owner)
        closed = {
            **receipt,
            "executed": True,
            "result_ready": True,
            "work_item_state": work["state"],
            "remote_state": "SUCCEEDED",
            "automatic_resend": False,
            "review_approved": True,
        }
        authorize_review()
        self._move(operation, "SUCCEEDED", intent_id, result=closed, effect_started=True)
        authorize_review()
        self.journal.mark(intent_id, "CLOSED", receipt=closed, executed=True)
        return closed

    def _on_reconcile(self, frame):
        if (frame.get("body") or {}).get("intent_id") != frame.get("intent_id"):
            raise FederationDenied("reconciliation intent mismatch")
        intent = self.journal.get(frame["intent_id"])
        if not intent:
            return {"disposition": "absent", "executed": False, "automatic_resend": False}
        capability = {"delegate": "federation.delegate", "chat": "federation.conversation",
                      "canvas": "federation.canvas.project"}.get(intent.get("kind"))
        if capability is None:
            raise FederationDenied("unknown intent action")
        self._authorize_incoming_intent(frame, intent, capability, expected_kind=intent["kind"])
        if isinstance(intent.get("task"), dict) or not intent.get("receipt"):
            observed = self.task_executor.observe(peer=frame["from"], intent_id=frame["intent_id"]) if self.task_executor else None
            if observed and observed.get("executor") == "central-machine-task-v1":
                state = "CLOSED" if observed.get("executed") else "IN_REVIEW" if observed.get("result_ready") else "UNCERTAIN"
                self.journal.mark(frame["intent_id"], state, receipt=observed, executed=observed.get("executed") is True)
                intent = self.journal.get(frame["intent_id"])
            else:
                return {"disposition": "pending", "executed": False, "automatic_resend": False,
                        "remote_state": (observed or {}).get("remote_state", "UNCERTAIN")}
        receipt = intent["receipt"]
        return {
            "disposition": "found",
            "executed": receipt.get("executed") is True,
            "automatic_resend": False,
            "receipt": receipt,
        }

    def _authorize_incoming_intent(self, frame, intent, capability, *, expected_kind="delegate"):
        if not intent or intent.get("peer") != frame["from"] or intent.get("kind") != expected_kind:
            raise FederationDenied("intent belongs to another peer or action")
        scope = parse_scope(intent.get("scope"))
        self._require_grant(capability, scope["project_id"])
        self._require_membership(scope)

    def _cancel_peer_tasks(self, node_id):
        if self.task_executor is None:
            return
        for intent_id, intent in self.journal.intents().items():
            if intent.get("peer") != node_id or not isinstance(intent.get("task"), dict):
                continue
            receipt = self.task_executor.observe(peer=node_id, intent_id=intent_id)
            if not receipt or receipt.get("result_ready") is True:
                continue
            for oid in receipt.get("step_operation_ids", []):
                try:
                    operation = self.control.durable.operation_status(oid, self.owner)
                except FileNotFoundError:
                    continue
                if operation["state"] in {"STARTING", "RUNNING", "WAITING_EXTERNAL"}:
                    self.control.durable.request_cancel(oid, self.owner, side_effect_may_have_started=True)

    def _on_delivery(self, peer, frame):
        kind = frame["kind"]
        body = frame.get("body") or {}
        scope = parse_scope(body.get("scope"))
        request_scope = scope
        if self.bound_project_id and scope["kind"] != "project":
            raise FederationDenied("remote subproject scope needs an explicit local mapping")
        if self.bound_project_id:
            scope = {"kind": "project", "project_id": self.bound_project_id, "space_id": None, "document_id": None}
        capability = {
            "chat": "federation.conversation",
            "canvas": "federation.canvas.project",
            "delegate": "federation.delegate",
        }[kind]
        decision = self._require_grant(capability, scope["project_id"])
        self._require_membership(scope)
        content = body.get("body")
        if kind == "chat":
            content = self._text(content)
        elif kind == "canvas":
            try:
                content = validate_presentation(content)
            except CollaborationDenied as exc:
                raise FederationDenied("canvas projection is presentation only") from exc
        elif kind == "delegate":
            content = self._task(content)
        existing = self.journal.get(frame["intent_id"])
        if existing:
            if (existing.get("peer") != frame["from"] or existing.get("kind") != kind
                    or existing.get("scope") != scope
                    or existing.get("request_scope", request_scope) != request_scope
                    or kind == "delegate" and existing.get("task") != content):
                raise FederationDenied("intent belongs to a different peer, scope, or task")
            if existing.get("receipt"):
                return existing["receipt"]
            raise FederationUncertain("existing remote intent is observed and is not restarted")
        if kind == "delegate":
            if isinstance(content, dict):
                if self.task_executor is None:
                    raise FederationDenied("installation task executor is not configured")
                self.journal.put({"intent_id": frame["intent_id"], "kind": kind,
                    "peer": frame["from"], "scope": scope, "request_scope": request_scope,
                    "task": content, "state": "DISPATCHED", "executed": False, "automatic_resend": False})
                def authorize_step():
                    if self._stop.is_set() or peer.get("revoked") or peer.get("pair_state") != "paired":
                        raise FederationDenied("task peer is no longer authorized")
                    self._require_grant("federation.delegate", scope["project_id"])
                    self._require_membership(scope)
                receipt = self.task_executor.execute(intent_id=frame["intent_id"], task=content,
                    scope=scope, request_scope=request_scope, grant_id=decision["grant_id"],
                    peer=frame["from"], artifact_dir=self.journal.artifact_dir, authorize=authorize_step)
            else:
                receipt = execute_delegation(
                    self.control, owner=self.owner, intent_id=frame["intent_id"],
                    objective=content, scope=scope, grant_id=decision["grant_id"], peer=frame["from"],
                    artifact_dir=self.journal.artifact_dir,
                )
            self.journal.put({
                "intent_id": frame["intent_id"],
                "kind": kind,
                "peer": frame["from"],
                "state": "IN_REVIEW" if receipt.get("result_ready") is True else "UNRESOLVED",
                "executed": False,
                "automatic_resend": False,
                "operation_id": receipt["operation_id"],
                "work_item_id": receipt["work_item_id"],
                "grant_id": decision["grant_id"],
                "task": content,
                "scope": scope,
                "request_scope": request_scope,
                "receipt": receipt,
            })
            return receipt
        settle = "recorded" if kind in {"chat", "canvas"} else None
        _run, item, operation = self._admit(
            kind=capability, intent_id=frame["intent_id"], project_id=scope["project_id"],
            objective=self._objective(kind, frame["intent_id"]),
            metadata=self._metadata(frame["intent_id"], scope, frame["from"]),
            settle=settle,
        )
        receipt = {
            "intent_id": frame["intent_id"],
            "operation_id": operation["operation_id"],
            "work_item_id": item["work_item_id"],
            "run_id": item["run_id"],
            "grant_id": decision["grant_id"],
            "executed": False,
            "automatic_resend": False,
            "recorded": kind != "delegate",
            "remote_state": operation["state"],
            "work_item_state": item["state"],
        }
        self.journal.put({
            "intent_id": frame["intent_id"],
            "kind": kind,
            "peer": frame["from"],
            "state": "ADMITTED",
            "executed": False,
            "automatic_resend": False,
            "operation_id": operation["operation_id"],
            "work_item_id": item["work_item_id"],
            "grant_id": decision["grant_id"],
            "scope": scope,
            "request_scope": request_scope,
            "receipt": receipt,
        })
        if kind == "chat":
            self.journal.add_message({
                "peer": frame["from"], "text": content, "intent_id": frame["intent_id"], "scope": scope,
            })
        if kind == "canvas":
            self.journal.add_projection({
                "scope_key": json.dumps(scope, sort_keys=True, separators=(",", ":")),
                "presentation": content,
                "intent_id": frame["intent_id"],
                "executed": False,
            })
        return receipt

    def _require_grant(self, capability, project_id):
        decision = self.control.authorization.authorize(
            self.owner,
            principal_type=self.principal_type,
            principal_id=self.principal_id,
            capability=capability,
            scope_type="project",
            scope_id=project_id,
            context={"actual_cost": 0.0},
            local_owner=False,
        )
        if decision.get("allowed") is not True or not decision.get("grant_id"):
            raise FederationDenied("control plane grant missing")
        return decision

    def _require_membership(self, scope):
        if self.teams is None:
            return
        self.teams.assert_member_scope(self.principal_id, scope)

    def _admit(self, *, kind, intent_id, project_id, objective, metadata, settle):
        run = self.control.durable.create_run(
            self.owner,
            workspace=project_id,
            idempotency_key=f"federation:{self.owner}:{project_id}",
            required_capabilities=[
                "federation.conversation", "federation.canvas.project", "federation.delegate",
            ],
        )
        item = self.control.create_work_item(
            run["run_id"], self.owner,
            objective=objective,
            external_key=intent_id,
            required_capabilities=[kind],
            metadata=metadata,
            side_effect_scope="none",
        )
        operation = self.control.durable.create_operation(
            run["run_id"], self.owner,
            kind=kind,
            idempotency_key=intent_id,
            initial_state="QUEUED",
        )
        if operation.get("state") == "QUEUED":
            operation = self._move(operation, "STARTING", intent_id)
            operation = self._move(operation, "WAITING_EXTERNAL", intent_id)
        if settle == "recorded" and operation.get("state") == "WAITING_EXTERNAL":
            operation = self._move(operation, "SUCCEEDED", intent_id, result={
                "intent_id": intent_id,
                "executed": False,
                "automatic_resend": False,
                "recorded": True,
            })
        return run, item, operation

    def _move(self, operation, state, intent_id, result=None, error=None, effect_started=False):
        return self.control.durable.update_operation(
            operation["operation_id"], self.owner,
            state=state,
            progress={
                "intent_id": intent_id,
                "executed": False,
                "automatic_resend": False,
                "effect_started": bool(effect_started),
                "phase": "waiting_review" if state == "WAITING_EXTERNAL" and effect_started else "recorded",
            },
            result=result,
            error=error,
        )

    def _lose_operation(self, operation_id, intent_id):
        if not operation_id:
            return
        operation = self.control.durable.operation_status(operation_id, self.owner)
        if operation["state"] in {"QUEUED", "STARTING", "RUNNING", "WAITING_EXTERNAL"}:
            if operation["state"] == "QUEUED":
                operation = self._move(operation, "STARTING", intent_id)
            self._move(operation, "UNCERTAIN", intent_id)

    def _remember(self, node_id, fingerprint, cert_pem, host, port):
        with self._lock:
            current = self.peers.get(node_id, {})
            if current.get("revoked"):
                raise FederationDenied("pairing revoked")
            if current.get("fingerprint") not in (None, fingerprint):
                raise FederationDenied("identity binding")
            current.update({
                "node_id": node_id,
                "fingerprint": fingerprint,
                "cert_pem": cert_pem,
                "local_confirmed": current.get("local_confirmed", False),
                "remote_confirmed": current.get("remote_confirmed", False),
                "revoked": False,
                "transport": "up",
                "execution_authorized": False,
                "vpn_is_authorization": False,
                "automatic_resend": False,
            })
            if host is not None:
                current["address"] = host
                current["port"] = port
            self.peers[node_id] = current
            self._refresh(current)
            if self.bound_port is not None:
                self._server_ctx = self._server_context()

    def _refresh(self, peer):
        if peer.get("revoked"):
            peer["pair_state"] = "revoked"
        elif peer.get("local_confirmed") and peer.get("remote_confirmed"):
            peer["pair_state"] = "paired"
            peer["cert_pinned"] = True
        elif peer.get("local_confirmed"):
            peer["pair_state"] = "local_confirmed"
        elif peer.get("remote_confirmed"):
            peer["pair_state"] = "remote_confirmed"
        else:
            peer["pair_state"] = "discovered"
        peer["execution_authorized"] = False
        peer["vpn_is_authorization"] = False
        peer["automatic_resend"] = False
        self.journal.save_peer(peer)

    def _peer(self, node_id):
        with self._lock:
            peer = self.peers.get(node_id)
            if peer is None:
                raise FederationDenied("unknown peer")
            return peer

    def _peer_by_fingerprint(self, fingerprint):
        with self._lock:
            for peer in self.peers.values():
                if peer.get("fingerprint") == fingerprint:
                    return peer
        return None

    def _ready(self, node_id):
        peer = self._peer(node_id)
        if peer.get("revoked"):
            raise FederationDenied("pairing revoked")
        if peer.get("transport") == "disconnected":
            raise FederationUncertain("peer disconnected")
        if peer.get("pair_state") != "paired":
            raise FederationDenied("not paired")
        return peer

    def _server_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(self.identity.cert_path), keyfile=str(self.identity.key_path))
        context.check_hostname = False
        context.verify_mode = ssl.CERT_OPTIONAL
        pems = [peer["cert_pem"] for peer in self.peers.values() if peer.get("cert_pem")]
        if pems:
            context.load_verify_locations(cadata="".join(pems))
        return context

    def _client_context(self, pinned_pem):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        if pinned_pem:
            context.load_cert_chain(certfile=str(self.identity.cert_path), keyfile=str(self.identity.key_path))
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(cadata=pinned_pem)
        else:
            context.verify_mode = ssl.CERT_NONE
        return context

    @staticmethod
    def _task(value):
        from .task_runtime import validate_task
        if isinstance(value, dict):
            clean = validate_task(value)
            _refuse_image_installer(json.dumps(clean))
            return clean
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise FederationDenied("invalid delegation objective")
        _refuse_image_installer(value)
        reject_secrets({"objective": value})
        return value.strip()

    @staticmethod
    def _text(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 8000:
            raise FederationDenied("invalid message")
        reject_secrets({"text": value})
        return value.strip()

    @staticmethod
    def _objective(kind, intent_id):
        return f"Federated {kind} admission {intent_id}"

    @staticmethod
    def _metadata(intent_id, scope, peer):
        return {
            "federation": {
                "intent_id": intent_id,
                "scope": scope,
                "peer": peer,
                "executed": False,
                "automatic_resend": False,
            }
        }

    @staticmethod
    def _public_peer(peer):
        visible = "disconnected" if peer.get("transport") == "disconnected" else peer.get("pair_state")
        return {
            "node_id": peer.get("node_id"),
            "fingerprint": peer.get("fingerprint"),
            "state": visible,
            "pair_state": peer.get("pair_state"),
            "paired": peer.get("pair_state") == "paired" and not peer.get("revoked"),
            "execution_authorized": False,
            "vpn_is_authorization": False,
            "automatic_resend": False,
            "network_reachable": peer.get("transport") == "up",
        }
