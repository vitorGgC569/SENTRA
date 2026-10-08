"""Memory is accessible across local MCP conversations, subject to workspace grants."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import Client

from sentra_core.conversations import ConversationStore
from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.conversation_memory import ConversationMemoryService
from sentra_mcp.services.filesystem import FilesystemService


@pytest.fixture(autouse=True)
def isolated_keyring(monkeypatch):
    if os.name != "nt":
        values = {}
        monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(
            set_password=lambda service,key,value: values.__setitem__((service,key),value),
            get_password=lambda service,key: values.get((service,key))))


def configured(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    state = tmp_path / "state"
    config = MCPConfig(allowed_roots=(root,), state_root=state,
                       audit_log=state / "audit.jsonl", remote_store_path=state / "remote.sqlite3")
    store = ConversationStore(state)
    sid = store.open(root)
    store.append(sid, "assistant", "original_memory_fact_317")
    return root, config, store, sid


def test_memory_rejects_oauth_and_other_workspace(tmp_path):
    root, config, store, sid = configured(tmp_path)
    service = ConversationMemoryService(FilesystemService(config, AuditLogger(config.audit_log)))
    with pytest.raises(PermissionError):
        service.read("conversation_get", principal="oauth-subject", owner="owner", path=str(root), session_id=sid)
    with pytest.raises(PermissionError):
        service.read("conversation_get", principal="local-operator", owner="owner", path=str(root), session_id=sid,
                     local_operator=False)
    other = tmp_path / "outside"
    other.mkdir()
    outside = store.open(other)
    with pytest.raises(PermissionError):
        service.read("conversation_get", principal="local-operator", owner="owner", path=str(root), session_id=outside,
                     local_operator=True)
    data = service.read("conversation_search", principal="local-operator", owner="owner", path=str(root), query="original_memory_fact",
                        local_operator=True)
    assert data["matches"][0]["session_id"] == sid
    assert "original_memory_fact_317" not in config.audit_log.read_text()


def test_actual_mcp_new_conversation_can_read_saved_cli_context(tmp_path):
    root, config, store, sid = configured(tmp_path)
    async def probe():
        runtime = SentraMCPServer(config)
        try:
            async with Client(runtime.mcp) as client:
                session = await client.call_tool("sentra_session_open", {})
                token = session.structured_content["data"]["session_token"]
                listed = await client.call_tool("sentra_coordination", {
                    "action": "conversation_list", "session_token": token,
                    "physical_ref": str(root), "limit": 10,
                })
                assert listed.structured_content["ok"], listed.structured_content
                assert listed.structured_content["data"]["conversations"][0]["id"] == sid
                result = await client.call_tool("sentra_coordination", {
                    "action": "conversation_get", "session_token": token,
                    "physical_ref": str(root), "conversation_id": sid,
                })
                assert result.structured_content["ok"], result.structured_content
                assert result.structured_content["data"]["messages"][0]["content"] == "original_memory_fact_317"
                # A new signed MCP conversation has the same local operator and
                # workspace grant; it can retrieve the previously saved context.
                fresh = await client.call_tool("sentra_session_open", {})
                query = await client.call_tool("sentra_coordination", {
                    "action": "conversation_search",
                    "session_token": fresh.structured_content["data"]["session_token"],
                    "physical_ref": str(root), "query": "original_memory_fact",
                })
                assert query.structured_content["ok"], query.structured_content
                assert query.structured_content["data"]["matches"][0]["session_id"] == sid
        finally:
            runtime.search.close()
            runtime.processes.shutdown()
            runtime.remote_store.close()
            runtime.durable.close()
            runtime.context.close()
    asyncio.run(probe())


def test_paginated_search_can_find_older_context_without_unbounded_scan(tmp_path):
    root, _, store, sid = configured(tmp_path)
    for _ in range(5):
        store.append(sid, "user", "unrelated newest message")
    cursor = None
    matches = []
    pages = 0
    while True:
        page = store.search_page(root, "original_memory_fact", max_scan=1, after=cursor)
        pages += 1
        assert page["scanned"] <= 1
        matches.extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
        assert pages < 10
    assert pages == 6
    assert len(matches) == 1 and matches[0]["session_id"] == sid
