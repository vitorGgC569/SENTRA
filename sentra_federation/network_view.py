"""Presentation model for the Dot network, invite, conversation and Canvas.

Lumen renders this document in the desktop shell. The model does not listen,
does not authorize, and does not carry a database.
"""
from __future__ import annotations

import json


def network_surface(gateway, scope=None):
    status = gateway.status()
    dots = []
    for peer in status["peers"]:
        node_id = peer.get("node_id")
        dots.append({
            "node_id": node_id,
            "state": peer.get("state"),
            "paired": peer.get("paired") is True,
            "invite": peer.get("pair_state"),
            "execution_authorized": False,
            "conversation": gateway.history(node_id) if node_id else [],
        })
    return {
        "schema": 1,
        "renderer": "lumen",
        "physical_proof": False,
        "vpn_is_authorization": False,
        "public_bind": False,
        "database_exposed": False,
        "image_installer": False,
        "bind": {"host_class": status.get("host_class"), "port": status.get("port")},
        "dots": dots,
        "canvas": gateway.canvas_view(scope) if scope else None,
    }


def surface_json(gateway, scope=None):
    return json.dumps(network_surface(gateway, scope), sort_keys=True, ensure_ascii=False)
