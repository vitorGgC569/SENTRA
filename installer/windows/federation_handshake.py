"""Loopback handshake copied into a Next install. Does not serve SQLite."""
from __future__ import annotations

import json
import socket
import ssl
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = (ROOT / "runtime").resolve()


def use_copied_runtime() -> None:
    if not RUNTIME.is_dir():
        raise SystemExit("runtime ausente")
    kept = []
    for entry in sys.path:
        candidate = Path.cwd() if entry == "" else Path(entry)
        try:
            resolved = candidate.resolve()
        except OSError:
            kept.append(entry)
            continue
        if resolved == RUNTIME:
            continue
        if (resolved / "sentra_federation").is_dir():
            continue
        kept.append(entry)
    sys.path[:] = [str(RUNTIME), *kept]


use_copied_runtime()

from sentra_federation.errors import FederationDenied, FederationUncertain
from sentra_federation.gateway import PeerGateway
from sentra_federation.identity import InstallationIdentity
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_remote.peer_surface import PeerGatewaySurface

PROJECT = {"kind": "project", "project_id": "project-next"}


def grant(control, owner, capability):
    return control.authorization.grant(
        owner,
        principal_type="user",
        principal_id=owner,
        capability=capability,
        scope_type="project",
        scope_id="project-next",
    )


def open_peer(base: Path, name: str, owner: str):
    control = ControlPlaneService.from_store(base / name / "control")
    identity = InstallationIdentity.load_or_create(base / name / "identity")
    gateway = PeerGateway(
        identity=identity,
        control=control,
        owner=owner,
        principal_id=owner,
        journal_dir=base / name / "journal",
    )
    bound = PeerGatewaySurface(gateway).start()
    return control, gateway, bound


def sqlite_is_served(host: str, port: int) -> bool:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=3)
    tls = context.wrap_socket(raw, server_hostname=None)
    try:
        tls.sendall(b"GET /canvas.sqlite3 HTTP/1.1\r\nHost: sentra-peer\r\nConnection: close\r\n\r\n")
        data = b""
        tls.settimeout(2)
        while len(data) <= 4096:
            try:
                chunk = tls.recv(1024)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        if b"sqlite" in data.lower() or b"CREATE TABLE" in data:
            return True
        return not data.startswith(b"HTTP/1.1 404")
    finally:
        tls.close()


def main() -> int:
    base = ROOT / "federation-proof"
    left_control, left, left_bound = open_peer(base, "left", "owner-left")
    right_control, right, right_bound = open_peer(base, "right", "owner-right")
    try:
        if left_bound["host_class"] != "loopback" or right_bound["host_class"] != "loopback":
            raise SystemExit("bind was not loopback")
        if left_bound["host"] not in {"127.0.0.1", "::1"} or right_bound["host"] not in {"127.0.0.1", "::1"}:
            raise SystemExit("bind was not loopback")
        left.discover(right_bound["host"], right_bound["port"])
        right.discover(left_bound["host"], left_bound["port"])
        left.exchange_hello(right_bound["host"], right_bound["port"])
        right.exchange_hello(left_bound["host"], left_bound["port"])
        code = left.confirmation_code_for(right.identity.node_id)
        if code != right.confirmation_code_for(left.identity.node_id):
            raise SystemExit("pairing codes differ")
        if left.confirm(right.identity.node_id, code)["paired"] is not False:
            raise SystemExit("one confirmation paired the peers")
        if right.confirm(left.identity.node_id, code)["paired"] is not True:
            raise SystemExit("both confirmations did not pair")
        if left.status()["vpn_is_authorization"] is not False:
            raise SystemExit("vpn was treated as authorization")
        try:
            left.send_chat(right.identity.node_id, "before grant", PROJECT, vpn_member=True)
        except FederationDenied as exc:
            if "grant" not in str(exc).lower():
                raise SystemExit("chat without a grant was not denied by the control plane") from exc
        else:
            raise SystemExit("chat without a grant was accepted")
        grant(left_control, "owner-left", "federation.conversation")
        grant(right_control, "owner-right", "federation.conversation")
        receipt = left.send_chat(right.identity.node_id, "hello", PROJECT, vpn_member=True)
        if not receipt.get("grant_id") or receipt.get("executed") is not False or receipt.get("automatic_resend") is not False:
            raise SystemExit("message did not return a withheld receipt")
        intent_id = "intent-" + "ab" * 16
        left.drop_before_receipt = True
        try:
            left.send_chat(right.identity.node_id, "maybe", PROJECT, intent_id=intent_id)
        except FederationUncertain:
            pass
        else:
            raise SystemExit("lost receipt was not uncertain")
        lost = left.journal.get(intent_id)
        if lost is None or lost.get("state") != "UNCERTAIN" or lost.get("automatic_resend") is not False:
            raise SystemExit("lost receipt was not left UNCERTAIN")
        deadline = time.time() + 3
        remote = None
        while time.time() < deadline:
            remote = right.journal.get(intent_id)
            if remote and remote.get("receipt"):
                break
            time.sleep(0.05)
        if remote is None or not remote.get("receipt"):
            raise SystemExit("lost receipt was not admitted remotely")
        remote_messages = len(right.history(left.identity.node_id))
        try:
            left.send_chat(right.identity.node_id, "maybe", PROJECT, intent_id=intent_id)
        except FederationUncertain:
            pass
        else:
            raise SystemExit("uncertain intent was resent")
        if left.journal.get(intent_id).get("state") != "UNCERTAIN":
            raise SystemExit("uncertain intent changed state")
        if len(right.history(left.identity.node_id)) != remote_messages:
            raise SystemExit("uncertain intent was resent")
        if sqlite_is_served(left_bound["host"], left_bound["port"]) or sqlite_is_served(right_bound["host"], right_bound["port"]):
            raise SystemExit("sqlite was served")
        report = {
            "paired": True,
            "receipt": receipt.get("grant_id"),
            "grant_refused": True,
            "uncertain_not_resent": True,
            "uncertain_state": "UNCERTAIN",
            "vpn_is_authorization": False,
            "sqlite_served": False,
            "bind": left_bound["host_class"],
        }
        print("SENTRA_FEDERATION_HANDSHAKE_OK")
        print(json.dumps(report, sort_keys=True))
        return 0
    finally:
        left.close()
        right.close()
        left_control.durable.close()
        right_control.durable.close()


if __name__ == "__main__":
    raise SystemExit(main())
