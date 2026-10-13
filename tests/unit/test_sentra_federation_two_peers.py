"""Two SENTRA peers on explicit local interface addresses, mutual mesh auth.

This drives SignedPeerDirectory.start, not a fake socket. VPN membership
does not authorize execution, and an expired peer stays disconnected with
no work resend.
"""
import socket
import time

import pytest

from sentra_canvas.peer_directory import PeerNodeIdentity, SignedPeerDirectory


def _ipv4_addresses():
    # 127.0.0.1 and 127.0.0.2 are distinct addresses on this host's loopback
    # range and actually exchange UDP. Cross-interface pairs such as the
    # Radmin VPN address did not deliver datagrams to each other here.
    found = ["127.0.0.1", "127.0.0.2"]
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
        address = info[4][0]
        if address not in found:
            found.append(address)
    return found


def _bindable(addresses, port):
    usable = []
    for address in addresses:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((address, port))
        except OSError:
            continue
        else:
            usable.append(address)
        finally:
            sock.close()
    return usable


def test_expired_peer_stays_disconnected_and_work_is_not_resent(tmp_path):
    from sentra_canvas.service import Canvas
    app = Canvas(tmp_path / "project", state_dir=tmp_path / "state" / "canvas", principal="owner")
    try:
        workspace = app.create_workspace("Mesh")["id"]
        left = PeerNodeIdentity(app.store, workspace)
        other = app.create_workspace("Other")["id"]
        right_identity = PeerNodeIdentity(app.store, other)
        clock = {"now": 1000}
        left_dir = SignedPeerDirectory(
            identity=left, mesh_key="m" * 43, label="Left",
            address="192.0.2.10", target_addresses=("192.0.2.11",),
            interval_seconds=1, ttl_seconds=2, clock=lambda: clock["now"])
        right = SignedPeerDirectory(
            identity=right_identity, mesh_key="m" * 43, label="Right",
            address="192.0.2.11", target_addresses=("192.0.2.10",),
            interval_seconds=1, ttl_seconds=2, clock=lambda: clock["now"])
        peer = right.accept(left_dir.announcement(), "192.0.2.10")
        assert peer["authenticated_mesh_member"] is True
        assert peer["execution_authorized"] is False
        clock["now"] = 1003
        shown = right.status()["peers"]
        assert shown[0]["node_id"] == left.node_id
        assert shown[0]["state"] == "disconnected"
        assert shown[0]["automatic_resend"] is False
        with pytest.raises(PermissionError, match="peer disconnected does not resend work"):
            right.work_resend(left.node_id, b"retry")
        assert right.status()["peers"][0]["state"] == "disconnected"
    finally:
        app.shutdown()


def test_two_real_interface_peers_pair_without_granting_execution(tmp_path):
    addresses = _bindable(_ipv4_addresses(), 37621)
    if len(addresses) < 2:
        pytest.skip("need two bindable IPv4 interfaces for a real peer pair")
    left_ip, right_ip = addresses[0], addresses[1]
    from sentra_canvas.service import Canvas
    app = Canvas(tmp_path / "project", state_dir=tmp_path / "state" / "canvas", principal="owner")
    left = right = None
    try:
        first = app.create_workspace("Left")["id"]
        second = app.create_workspace("Right")["id"]
        left = SignedPeerDirectory(
            identity=PeerNodeIdentity(app.store, first),
            mesh_key="m" * 43, label="Left host",
            address=left_ip, port=37621, target_addresses=(right_ip,),
            interval_seconds=1, ttl_seconds=4)
        right = SignedPeerDirectory(
            identity=PeerNodeIdentity(app.store, second),
            mesh_key="m" * 43, label="Right host",
            address=right_ip, port=37621, target_addresses=(left_ip,),
            interval_seconds=1, ttl_seconds=4)
        left.start()
        right.start()
        deadline = time.time() + 8
        seen = None
        while time.time() < deadline:
            peers = right.status()["peers"]
            if peers:
                seen = peers[0]
                break
            time.sleep(0.2)
        assert seen is not None
        assert seen["authenticated_mesh_member"] is True
        assert seen["execution_authorized"] is False
        assert seen["state"] == "discovered"
        assert right.status()["presence_grants_execution"] is False
    finally:
        if left is not None:
            left.close()
        if right is not None:
            right.close()
        app.shutdown()
