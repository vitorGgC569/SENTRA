"""Local surface for the SENTRA Peer Gateway.

The surface binds the gateway on loopback or a documented private network.
It does not open a public port and its diagnostics do not carry SQLite,
private keys, or filesystem paths.
"""
from __future__ import annotations

import json

from sentra_federation.bind import assert_private_bind
from sentra_federation.gateway import PeerGateway
from sentra_federation.network_view import network_surface


class PeerGatewaySurface:
    DATABASE_EXPOSED = False
    PUBLIC_BIND = False

    def __init__(self, gateway, host="127.0.0.1", port=0, documented_networks=()):
        if not isinstance(gateway, PeerGateway):
            raise TypeError("peer surface requires the installation peer gateway")
        self.host = assert_private_bind(host, documented_networks)
        self.port = port
        self.gateway = gateway

    def start(self):
        bound = self.gateway.listen(self.host, self.port)
        if bound["host_class"] not in {"loopback", "private", "documented-private"}:
            raise RuntimeError("peer surface refused the bind")
        return bound

    def network(self, scope=None):
        """Call site for the Lumen shell. Returns the network document, not a window."""
        document = network_surface(self.gateway, scope)
        if document.get("renderer") != "lumen":
            raise RuntimeError("network document is not addressed to Lumen")
        return document

    def diagnostics(self):
        status = self.gateway.status()
        encoded = json.dumps(status, sort_keys=True)
        lowered = encoded.lower()
        if "sqlite" in lowered or "private_key" in lowered or "begin private" in lowered:
            raise RuntimeError("peer surface leaked local state")
        if ":\\" in encoded or "journal.json" in lowered:
            raise RuntimeError("peer surface leaked a local path")
        return {
            "bind_host": self.host,
            "bind_port": status["port"],
            "host_class": status["host_class"],
            "database_exposed": False,
            "public_bind": False,
            "vpn_is_authorization": False,
            "execution_authorized": False,
            "automatic_resend": False,
            "physical_proof": False,
            "image_installer": False,
            "peers": status["peers"],
        }
