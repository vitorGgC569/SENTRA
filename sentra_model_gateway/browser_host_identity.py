"""Read-only identity observations from the existing authenticated Browser Host.

A transport-authenticated snapshot is not a calibrated account attestation.
This client never reads session/cookie APIs or promotes an unverified schema.
"""
from __future__ import annotations

import http.client
import hashlib
import json
from urllib.parse import urlsplit


def _host_post(descriptor: dict, path: str, payload: dict) -> dict:
    control = descriptor.get("control") or {}
    endpoint = urlsplit(str(control.get("endpoint") or ""))
    token = control.get("token")
    if (endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}
            or not endpoint.port or endpoint.path not in {"", "/"} or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment):
        raise PermissionError("Browser Host identity endpoint is not authenticated loopback")
    if not isinstance(token, str) or len(token) < 40 or any(not (c.isalnum() or c in "_-") for c in token):
        raise PermissionError("Browser Host control authentication is unavailable")
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=5)
    try:
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is not None:
            context.checkpoint()
        connection.request("POST", path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read(128_001)
        if response.status != 200 or len(body) > 128_000:
            raise PermissionError("Browser Host identity snapshot unavailable")
        snapshot = json.loads(body)
    finally:
        connection.close()
    if not isinstance(snapshot, dict) or snapshot.get("ok") is not True:
        raise PermissionError("Browser Host identity snapshot is invalid")
    return snapshot


def _binding(tab: dict, trace_id: str) -> dict:
    binding = {"traceId": trace_id, "surface_id": tab.get("surfaceId"),
               "document_id": tab.get("documentId"), "identity_epoch": tab.get("identityEpoch")}
    if any(not isinstance(value, str) or not value for value in binding.values()):
        raise PermissionError("Browser Host has no current document identity snapshot")
    return binding


def read_host_identity(descriptor: dict, tab: dict, *, trace_id: str) -> dict:
    binding = _binding(tab, trace_id)
    snapshot = _host_post(descriptor, "/v1/sentra/identity-snapshot", binding)
    for field in ("surface_id", "document_id", "identity_epoch"):
        if snapshot.get(field) != binding[field]:
            raise PermissionError("Browser Host document identity changed")
    collector = descriptor.get("sentraIdentityCollector") or {}
    if (not collector.get("sha256") or snapshot.get("collector_id") != collector.get("id")
            or snapshot.get("collector_sha256") != collector["sha256"]):
        raise PermissionError("Browser Host collector source identity changed")
    # No raw account identifiers escape into audit/errors. This observation
    # remains host-only and cannot authorize a send by itself.
    return snapshot


def read_host_message(descriptor: dict, tab: dict, *, trace_id: str, expected: dict) -> dict:
    """Consume a Host-issued challenge, independently observing the exact message.

    Expectations are selectors, never proof. Raw bodies/account IDs do not travel.
    Host and central frame revisions are distinct clocks. Persistence checks
    monotonicity of the Host observation independently of the central frame.
    """
    challenge = {**_binding(tab, trace_id), "conversation_id": expected["conversation_id"],
                 "message_id": expected["message_id"], "expected_role": expected["role"],
                 "observed_request_id": expected["request_id"]}
    if expected["role"] == "assistant":
        challenge["parent_user_message_id"] = expected["parent_user_message_id"]
    elif expected["role"] != "user":
        raise PermissionError("Browser Host message role is unknown")
    challenge["body_sha256"] = expected["body_sha256"]
    if "complete" in expected:
        challenge["complete"] = expected["complete"]
    digest = hashlib.sha256(json.dumps(challenge, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    issued = _host_post(descriptor, "/v1/sentra/message-challenge", challenge)
    nonce = issued.get("challenge_id")
    if (issued.get("state") != "CHALLENGED" or issued.get("challenge_sha256") != digest
            or not isinstance(nonce, str) or len(nonce) != 32
            or any(character not in "0123456789abcdef" for character in nonce)):
        raise PermissionError("Browser Host message challenge differs from original intent")
    observed = _host_post(descriptor, "/v1/sentra/message-snapshot", {"challenge_id": nonce})
    if (observed.get("matched") is not True or observed.get("state") != "OBSERVED"
            or observed.get("challenge_id") != nonce or observed.get("challenge_sha256") != digest):
        raise PermissionError("Browser Host message observation remains unknown")
    for field, wanted in {"surface_id": challenge["surface_id"], "document_id": challenge["document_id"],
            "identity_epoch": challenge["identity_epoch"], "conversation_id": expected["conversation_id"],
            "message_id": expected["message_id"], "role": expected["role"], "observed_request_id": expected["request_id"],
            "body_sha256": expected["body_sha256"]}.items():
        if observed.get(field) != wanted:
            raise PermissionError("Browser Host message binding changed")
    if expected["role"] == "assistant" and observed.get("parent_user_message_id") != expected["parent_user_message_id"]:
        raise PermissionError("Browser Host assistant parent changed")
    if "complete" in expected and observed.get("complete") is not expected["complete"]:
        raise PermissionError("Browser Host completion is not observed")
    if (type(observed.get("host_revision")) is not int or observed["host_revision"] < 1
            or observed.get("revision_source") != "host-observation"):
        raise PermissionError("Browser Host revision is not independently observed")
    collector = descriptor.get("sentraMessageCollector") or {}
    if (not collector.get("sha256") or observed.get("collector_id") != collector.get("id")
            or observed.get("collector_sha256") != collector["sha256"]):
        raise PermissionError("Browser Host message collector source changed")
    return observed


def read_host_approval(descriptor: dict, tab: dict, *, trace_id: str) -> dict:
    """Read-only observed approval state from the authenticated Browser Host.

    Returns {"state": "pending|idle|unknown", "tool_name": ...} as *data*.
    This client never clicks, accepts or dismisses approval UI; the operator
    and the durable consent gate remain the only approval authority.
    """
    binding = _binding(tab, trace_id)
    snapshot = _host_post(descriptor, "/v1/sentra/approval-snapshot", binding)
    for field in ("surface_id", "document_id", "identity_epoch"):
        if snapshot.get(field) != binding[field]:
            raise PermissionError("Browser Host document identity changed")
    state = snapshot.get("approval_state")
    if state not in {"pending", "idle", "unknown"}:
        raise PermissionError("Browser Host approval state is not observed")
    tool = snapshot.get("tool_name")
    if tool is not None and (not isinstance(tool, str) or not 1 <= len(tool) <= 200):
        raise PermissionError("Browser Host approval tool name is invalid")
    return {"state": state, "tool_name": tool,
            "document_id": binding["document_id"],
            "identity_epoch": binding["identity_epoch"],
            "effect_performed": False}


def read_host_account_catalog(descriptor: dict, tab: dict, *, trace_id: str,
                              provider: str, account_verifier=None) -> dict:
    """Read-only authenticated account model/effort catalog snapshot.

    The Host binds the catalog to the current document/identity epoch and its
    own authentication revision. Callers must treat a missing attestor or an
    unverified account as fail-closed: no catalog, no model assumption.
    Raw account identifiers never escape into audit/errors.
    """
    if provider not in {"chatgpt", "gemini"}:
        raise ValueError("catalog provider must be chatgpt or gemini")
    binding = _binding(tab, trace_id)
    snapshot = _host_post(descriptor, "/v1/sentra/account-catalog",
                          {**binding, "provider": provider})
    for field in ("surface_id", "document_id", "identity_epoch"):
        if snapshot.get(field) != binding[field]:
            raise PermissionError("Browser Host document identity changed")
    if not callable(account_verifier) or account_verifier(snapshot) is not True:
        raise PermissionError("current browser account/profile identity is unverified by host")
    models = snapshot.get("models")
    efforts = snapshot.get("efforts")
    if (not isinstance(models, list) or not models or len(models) > 64
            or not isinstance(efforts, list) or len(efforts) > 64
            or any(not isinstance(e, str) or not 1 <= len(e) <= 120 for e in [*models, *efforts])):
        raise PermissionError("Browser Host account catalog is invalid")
    revision = snapshot.get("authentication_revision")
    if type(revision) is not int or revision < 0:
        raise PermissionError("current browser account authentication revision is unverified")
    return {"provider": provider, "models": list(models), "efforts": list(efforts),
            "authentication_revision": revision,
            "document_id": binding["document_id"],
            "identity_epoch": binding["identity_epoch"],
            "account_verified": True, "catalog_complete": snapshot.get("catalog_complete") is True,
            "selection_verified": snapshot.get("selection_verified") is True,
            "model": snapshot.get("model"), "effort": snapshot.get("effort")}
