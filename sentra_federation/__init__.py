"""SENTRA Peer Gateway.

The gateway carries pairing, messages, canvas projections and delegation
receipts between two installations. Each installation's Control Plane is the
only authority. Importing this package does not listen, and nothing here
serves SQLite or treats a VPN address as a grant.
"""
from __future__ import annotations

from .bind import BindRefused, assert_private_bind
from .errors import FederationDenied, FederationUncertain
from .gateway import PeerGateway
from .identity import InstallationIdentity

__all__ = [
    "BindRefused",
    "FederationDenied",
    "FederationUncertain",
    "InstallationIdentity",
    "PeerGateway",
    "assert_private_bind",
]
