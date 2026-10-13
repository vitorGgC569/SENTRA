"""Durable Web message identity under a virtualized DOM (Rastro).

The page virtualizes/reorders/reloads messages, so a positional index from
`edge_extension/content-script.js` (Brisa) is NEVER a message identity. The
durable identity is the central `browser_request_messages` correlation
(principal, request_id) -> message_id, joined with the enrolled collector
document/epoch binding. Anything that cannot resolve through this table
fails closed instead of guessing from DOM order.

Consumers: `stream_ingest` (assistant frames), `web_send.answer` paths and
Compact & Resume receipt checks. No grants, sends or authority here.
"""
from __future__ import annotations

import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_PRINCIPAL = re.compile(r"^[^\x00-\x1f]{1,128}$")


def _check(label: str, value: str, pattern) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} requires a stable bounded identifier")
    return value


def resolve_by_request(control: Any, *, browser_principal: str,
                        request_id: str) -> dict[str, Any]:
    """Resolve the durable (message_id, document, epoch) for a proven request."""
    _check("browser principal", browser_principal, _PRINCIPAL)
    _check("request", request_id, _ID)
    with control.session_checkpoints.store.connect("chat_access") as db:
        row = db.execute(
            "SELECT m.message_id,m.extension_id,m.worker,m.document_id,"
            "m.collector_revision,ep.identity_epoch FROM browser_request_messages m "
            "LEFT JOIN browser_document_epochs ep ON ep.extension_id=m.extension_id "
            "AND ep.worker=m.worker AND ep.document_id=m.document_id "
            "WHERE m.principal=? AND m.request_id=?",
            (browser_principal, request_id)).fetchone()
    if row is None:
        raise PermissionError("Web request has no durable message identity")
    return {"message_id": row["message_id"], "extension_id": row["extension_id"],
            "worker": row["worker"], "document_id": row["document_id"],
            "collector_revision": row["collector_revision"],
            "identity_epoch": row["identity_epoch"]}


def resolve_by_message(control: Any, *, browser_principal: str,
                        message_id: str) -> dict[str, Any]:
    """Resolve the durable request/document binding for a known message_id."""
    _check("browser principal", browser_principal, _PRINCIPAL)
    _check("message", message_id, _ID)
    with control.session_checkpoints.store.connect("chat_access") as db:
        row = db.execute(
            "SELECT m.request_id,m.extension_id,m.worker,m.document_id,"
            "m.collector_revision,ep.identity_epoch FROM browser_request_messages m "
            "LEFT JOIN browser_document_epochs ep ON ep.extension_id=m.extension_id "
            "AND ep.worker=m.worker AND ep.document_id=m.document_id "
            "WHERE m.principal=? AND m.message_id=?",
            (browser_principal, message_id)).fetchone()
    if row is None:
        raise PermissionError("Web message has no durable request binding")
    return {"request_id": row["request_id"], "extension_id": row["extension_id"],
            "worker": row["worker"], "document_id": row["document_id"],
            "collector_revision": row["collector_revision"],
            "identity_epoch": row["identity_epoch"]}


def require_index_resolution(control: Any, *, browser_principal: str,
                              conversation_id: str, observed_index: int,
                              request_id: str) -> dict[str, Any]:
    """Bind a positional snapshot index to the durable message_id.

    The index is descriptive metadata only. Resolution succeeds only when
    the same (principal, request_id) already owns a durable message_id in
    the same conversation; otherwise it fails closed and the frame must be
    dropped, never stored under a fabricated identity.
    """
    _check("browser principal", browser_principal, _PRINCIPAL)
    _check("conversation", conversation_id, _ID)
    _check("request", request_id, _ID)
    if type(observed_index) is not int or not 0 <= observed_index <= 1_000_000:
        raise ValueError("bounded observed message index required")
    proven = control.chat_access.require_exact_message(
        browser_principal, request_id,
        resolve_by_request(control, browser_principal=browser_principal,
                           request_id=request_id)["message_id"])
    if proven.get("source") != "proven" or proven.get("conversation_id") != conversation_id:
        raise PermissionError("index observation is not tied to target conversation")
    binding = resolve_by_request(control, browser_principal=browser_principal,
                                 request_id=request_id)
    return {**binding, "conversation_id": conversation_id,
            "observed_index": observed_index, "grants_created": False}
