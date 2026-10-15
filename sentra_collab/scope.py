"""Scope labels for project, space, or document sharing.

A scope names what a team membership covers. It does not grant anything.
Authorization stays on the installation Control Plane.
"""
from __future__ import annotations

import re

ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
RESERVED = {"__proto__", "constructor", "prototype"}
KINDS = {"project", "space", "document"}


class ScopeDenied(PermissionError):
    pass


def _ident(value, label):
    if not isinstance(value, str) or not ID.fullmatch(value) or value in RESERVED:
        raise ScopeDenied("invalid " + label)
    return value


def parse_scope(value):
    """Return a normalized scope. Extra fields and widened kinds are refused."""
    if not isinstance(value, dict):
        raise ScopeDenied("scope required")
    if set(value) - {"kind", "project_id", "space_id", "document_id"}:
        raise ScopeDenied("invalid scope")
    if "kind" not in value or "project_id" not in value:
        raise ScopeDenied("scope requires kind and project")
    kind = value["kind"]
    if kind not in KINDS:
        raise ScopeDenied("invalid scope kind")
    project_id = _ident(value["project_id"], "project id")
    space_id = value.get("space_id")
    document_id = value.get("document_id")
    if kind == "project":
        if space_id is not None or document_id is not None:
            raise ScopeDenied("project scope has no space or document")
        return {"kind": "project", "project_id": project_id, "space_id": None, "document_id": None}
    space_id = _ident(space_id, "space id")
    if kind == "space":
        if document_id is not None:
            raise ScopeDenied("space scope has no document")
        return {"kind": "space", "project_id": project_id, "space_id": space_id, "document_id": None}
    document_id = _ident(document_id, "document id")
    return {
        "kind": "document",
        "project_id": project_id,
        "space_id": space_id,
        "document_id": document_id,
    }


def same_scope(left, right):
    return parse_scope(left) == parse_scope(right)
