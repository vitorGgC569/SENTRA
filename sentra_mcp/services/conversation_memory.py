"""Workspace-authorized access to local protected conversation context."""
from __future__ import annotations

import json

from sentra_core.conversations import ConversationStore


class ConversationMemoryService:
    def __init__(self, filesystem):
        self.filesystem = filesystem

    def read(self, action, *, principal, owner, workspace=None, path=".",
             session_id=None, query=None, limit=20, cursor=None, local_operator=False):
        # OS protected local history belongs to the desktop operator. OAuth
        # subjects do not inherit access just because the server can decrypt it.
        if local_operator is not True or principal != "local-operator":
            raise PermissionError("local conversation memory is available only to the desktop operator")
        _, target, _, grant = self.filesystem._resolve_access(
            path, workspace=workspace, owner=owner, permission="read")
        if not target.is_dir():
            raise ValueError("conversation workspace must be an existing directory")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("conversation result limit must be 1-100")
        root = self.filesystem.config.resolved_state_root
        store = ConversationStore(root)
        if action == "conversation_list":
            result = {"workspace": str(target), "conversations": store.list(target, limit=limit)}
        elif action == "conversation_get":
            status = store.status(session_id)
            if status["workspace"] != str(target):
                raise PermissionError("conversation belongs to another workspace")
            window = store.history_window(session_id, max_messages=limit,
                                          max_chars=min(320000, max(1000, self.filesystem.max_read_bytes // 8)))
            result = {"conversation": status, **window}
        elif action == "conversation_search":
            page = store.search_page(target, query, limit=limit, after=(cursor or {}).get("after"))
            result = {"workspace": str(target), "matches": page.pop("items"), **page}
        else:
            raise ValueError("unsupported conversation memory action")
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > self.filesystem.max_read_bytes:
            raise ValueError("memory response exceeds configured read limit; request fewer results")
        self.filesystem.audit.emit("conversation.memory.read", "ok", {
            "operation": action, "workspace_id": grant["workspace_id"],
            "conversation_id": session_id, "limit": limit,
        })
        return result
