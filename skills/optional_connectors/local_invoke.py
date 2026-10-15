"""Optional connector entry. This file does not open a socket.

Without a host credential and without a permitted network, ``run`` fails.
It does not answer in place of GitHub, Drive, OneDrive, Microsoft 365, or Slack.
A test may inject ``transport``; GitHub then performs one delimited repository
read and returns that transport's payload. The payload is not a live account.
"""
from __future__ import annotations

import json
import re

CALLS = 0

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_MAX_BYTES = 65536
_READ_KEYS = frozenset({"owner", "repo"})


class ConnectorRefused(RuntimeError):
    """The account was not contacted, or the read was not a delimited GitHub GET."""


def run(context):
    """Fail closed unless a test transport performs one GitHub repository read."""
    global CALLS
    if not isinstance(context, dict):
        raise ConnectorRefused("CONNECTOR_CONTEXT_REQUIRED")
    CALLS += 1
    transport = context.get("transport")
    if context.get("network") is not False and transport is None:
        raise ConnectorRefused("CONNECTOR_NETWORK_REFUSED")
    if transport is None and not _has_credential(context) and context.get("network_allowed") is not True:
        raise ConnectorRefused("CONNECTOR_CREDENTIAL_AND_NETWORK_ABSENT")
    if transport is None:
        raise ConnectorRefused("CONNECTOR_ACCOUNT_NOT_CONTACTED")
    if not callable(transport):
        raise ConnectorRefused("CONNECTOR_TRANSPORT_INVALID")
    if context.get("subject_id") != "github":
        raise ConnectorRefused("CONNECTOR_ACCOUNT_REQUIRED")
    return _read_repository(context, transport)


def _has_credential(context) -> bool:
    credential = context.get("credential")
    return isinstance(credential, str) and bool(credential.strip())


def _read_repository(context, transport):
    read = context.get("read")
    if not isinstance(read, dict) or set(read) != _READ_KEYS:
        raise ConnectorRefused("CONNECTOR_READ_UNBOUNDED")
    owner, repo = read["owner"], read["repo"]
    if (not isinstance(owner, str) or not isinstance(repo, str)
            or not _ID.fullmatch(owner) or not _ID.fullmatch(repo)
            or ".." in owner or ".." in repo):
        raise ConnectorRefused("CONNECTOR_READ_UNBOUNDED")
    request = {
        "connector": "github",
        "operation": "read_repository",
        "method": "GET",
        "path": "/repos/" + owner + "/" + repo,
        "query": None,
        "body": None,
        "max_bytes": _MAX_BYTES,
    }
    payload = transport(dict(request))
    if not isinstance(payload, dict):
        raise ConnectorRefused("CONNECTOR_PAYLOAD_INVALID")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > _MAX_BYTES:
        raise ConnectorRefused("CONNECTOR_READ_UNBOUNDED")
    return dict(payload)
