"""GATE-5 offline ACP registry, OpenHands, A2A and ToolHive boundary tests.

Every test is local. Third-party manifests are metadata references, not execution.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop import (
    ACPRegistryEntry, ACPVersionedCatalog, InteropRequestMapper, InteropMappingDenied,
    OpenHandsEvent, OpenHandsEventBridge, AgentIdentity, A2AEnvelope,
    A2ATaskBoundary, InteropGate, MCPToolGrant, ToolHiveMCPBoundary,
)
from sentra_interop.a2a import operation_arguments

BASE = Path(__file__).resolve().parents[2]
REGISTRY = BASE / "third_party" / "acp-registry"


def run(coro):
    return asyncio.run(coro)


def make_gate(policy=None):
    machine = Machine("machine-g5", "agent", "user-g5",
                      tuple(Capability(s, s) for s in (
                          "acp:session", "acp:prompt", "a2a:ingest",
                          "mcp:read", "openhands:event",
                      )))
    return InteropGate(machine, policy)


def mapper(root):
    return InteropRequestMapper(
        "machine-g5", "user-g5", "work-g5", str(root),
        frozenset({"acp:session", "acp:prompt", "a2a:ingest",
                   "mcp:read", "openhands:event"}),
    )


def allow(_):
    return PolicyDecision(True, "granted", {"work_item_ids": ["work-g5"]})


def test_catalog_version_pins_from_cloned_manifests():
    if not REGISTRY.is_dir():
        pytest.skip("third_party ACP registry checkout unavailable")
    codex = json.loads((REGISTRY / "codex-acp" / "agent.json").read_text(encoding="utf-8"))
    anti = json.loads((REGISTRY / "antigravity-acp" / "agent.json").read_text(encoding="utf-8"))
    index = {"version": "1.0.0", "agents": [anti, codex]}
    catalog = ACPVersionedCatalog.from_index(
        index, schema_version="1.0.0",
        pinned_versions={"codex-acp": "2.1.1", "antigravity-acp": "1.3.0"},
    )
    assert catalog.select("codex-acp", version="2.1.1").distribution_kind == "npx"
    assert catalog.select("antigravity-acp", version="1.3.0").distribution_kind == "binary"
    assert catalog.select("antigravity-acp", version="1.3.0").distribution_name == "binary:manual-approval-required"
    assert len(catalog.snapshot_sha256) == 64
    assert catalog.snapshot_sha256 == ACPVersionedCatalog.from_index(
        index, schema_version="1.0.0",
        pinned_versions={"codex-acp": "2.1.1", "antigravity-acp": "1.3.0"},
    ).snapshot_sha256
    with pytest.raises(ValueError):
        catalog.select("codex-acp", version="2.1.2")
    with pytest.raises(ValueError):
        ACPVersionedCatalog.from_index(
            {"version":"1.0.0", "agents":[anti, codex, codex]},
            schema_version="1.0.0", pinned_versions={"codex-acp":"2.1.1"})
    with pytest.raises(ValueError):
        ACPVersionedCatalog.from_index(
            index, schema_version="9.0.0", pinned_versions={"codex-acp":"2.1.1"})


def test_registry_preview_explicit_version_selection():
    row = {
        "id":"local-acp", "name":"Local Test", "version":"1.2.3",
        "distribution":{"npx":{"package":"local-acp@1.2.3"}},
        "preview":{"version":"1.2.4-preview.2",
                   "distribution":{"npx":{"package":"local-acp@1.2.4-preview.2"}}},
    }
    assert ACPRegistryEntry.from_mapping(row, pinned_version="1.2.3").version == "1.2.3"
    with pytest.raises(ValueError):
        ACPRegistryEntry.from_mapping(row, pinned_version="1.2.4-preview.2")
    preview = ACPRegistryEntry.from_mapping(
        row, pinned_version="1.2.4-preview.2", channel="preview")
    assert preview.version == "1.2.4-preview.2"
    catalog = ACPVersionedCatalog.from_index(
        {"version":"1.0.0","agents":[row]}, schema_version="1.0.0",
        pinned_versions={"local-acp":"1.2.4-preview.2"},
        channels={"local-acp":"preview"})
    assert catalog.select("local-acp", version=preview.version) == preview
    with pytest.raises(ValueError):
        ACPVersionedCatalog.from_index(
            {"version":"1.0.0","agents":[row]}, schema_version="1.0.0",
            pinned_versions={"unknown":"1.2.3"})


@pytest.mark.parametrize("payload", [
    {"text":"hello","api_key":"NEVER_TRANSFER"},
    {"config":{"authorization":"Bearer secret"}},
    {"nested":[{"secret":"private"}]},
    {"custom":object()},
    {"long":"a"*70000},
])
def test_scope_mapper_rejects_secret_keys_and_invalid_payloads(tmp_path, payload):
    with pytest.raises(InteropMappingDenied):
        mapper(tmp_path).make(
            operation_id="op", idempotency_key="idem", capability_id="mcp:read",
            arguments=payload,
        )


def test_scope_mapper_roundtrip_binding_and_immutable_copy(tmp_path):
    origin = {"x": ["a", "b"]}
    m = mapper(tmp_path)
    request = m.mcp_call(operation_id="op", idempotency_key="idem", capability_id="mcp:read",
                         server_id="local", tool_name="read", arguments=origin)
    origin["x"].append("mutated")
    assert request.arguments["arguments"]["x"] == ["a", "b"]
    assert (request.principal_id, request.work_item_id, request.machine_id) == (
        "user-g5", "work-g5", "machine-g5")
    with pytest.raises(InteropMappingDenied):
        m.make(operation_id="bad", idempotency_key="idem2",
               capability_id="root:access", arguments={})
    with pytest.raises(InteropMappingDenied):
        m.acp_session(operation_id="bad", idempotency_key="idem3", cwd=str(tmp_path.parent))
    bound = m.acp_session(operation_id="session", idempotency_key="idem4", cwd=str(tmp_path))
    assert bound.arguments == {"cwd":str(tmp_path.resolve())}


def test_request_mapper_authorize_policy_denial_and_scope(tmp_path):
    async def case():
        m = mapper(tmp_path)
        req = m.acp_prompt(operation_id="prompt1", idempotency_key="k1",
                           session_id="s1", text="safe")
        assert await m.authorize(req, make_gate(allow)) is req
        with pytest.raises(InteropMappingDenied):
            await m.authorize(req, make_gate(None))
        impostor = OperationRequest(req.operation_id, "other-user", req.machine_id,
                                   req.capability_id, req.work_item_id,
                                   req.idempotency_key, req.arguments)
        with pytest.raises(InteropMappingDenied):
            await m.authorize(impostor, make_gate(allow))
    run(case())


def test_a2a_mapped_scope_roundtrip_replay_and_cancel(tmp_path):
    async def case():
        m = mapper(tmp_path)
        who = AgentIdentity("user-g5", "remote", "trusted")
        event = A2AEnvelope(who, "task", "work-g5", "evt-0", 0, "submitted")
        command = m.a2a_event(operation_id="ingest1", idempotency_key="idem1", event=event)
        assert command.arguments == operation_arguments(event)
        bridge = A2ATaskBoundary(make_gate(allow), trusted_agents=frozenset({who}),
                                 require_mapped_arguments=True)
        assert (await bridge.accept(command, event)).operation.state == "SUCCEEDED"
        assert (await bridge.accept(command, event)).duplicate
        next_event = A2AEnvelope(who, "task", "work-g5", "evt-1", 1, "working")
        # Cannot reuse old operation identity for a different event.
        assert (await bridge.accept(command, next_event)).operation.state == "FAILED"
        assert (await bridge.accept(m.a2a_event(
            operation_id="ingest2", idempotency_key="idem2",
            event=next_event), next_event)).operation.state == "SUCCEEDED"
        assert await bridge.state("task") == "working"
        with pytest.raises(InteropMappingDenied):
            m.a2a_event(operation_id="wrong", idempotency_key="k", event=A2AEnvelope(
                who, "other", "different-work", "e0", 0, "submitted"))
    run(case())


def test_openhands_typed_event_bridge_no_secret_leak_and_dedupe(tmp_path):
    async def case():
        m = mapper(tmp_path)
        bridge = OpenHandsEventBridge(
            make_gate(allow), conversation_id="work-g5",
            principal_id="user-g5", work_item_id="work-g5")
        raw = {"id":"evt0", "kind":"message", "source":"agent",
               "parent_id":"__root__", "content":"discard this internal text"}
        event = OpenHandsEvent.from_mapping(raw, conversation_id="work-g5", sequence=0)
        request = m.openhands_event(operation_id="open0", idempotency_key="open-k0", event=event)
        result = await bridge.accept(request, raw,
                                     authenticated_conversation_id="work-g5", sequence=0)
        assert result.operation.state == "SUCCEEDED"
        assert "discard this internal text" not in str(result.payload)
        assert await bridge.observe("evt0") == event
        assert (await bridge.accept(request, raw,
                                    authenticated_conversation_id="work-g5", sequence=0)).duplicate
        assert (await bridge.accept(
            m.openhands_event(operation_id="open1", idempotency_key="open-k1", event=event),
            raw, authenticated_conversation_id="work-g5", sequence=0)).operation.state == "FAILED"
        assert (await bridge.accept(request, raw, authenticated_conversation_id="forged",
                                    sequence=0)).operation.state == "FAILED"
        secret_raw = {"id":"evt1","kind":"message","source":"agent",
                      "llm_message":{"api_key":"DO_NOT_LEAK"}}
        secret_event = OpenHandsEvent.from_mapping(secret_raw, conversation_id="work-g5", sequence=1)
        secret_request = m.openhands_event(operation_id="open2",
                                           idempotency_key="open-k2", event=secret_event)
        rejected = await bridge.accept(secret_request, secret_raw,
                                       authenticated_conversation_id="work-g5", sequence=1)
        assert rejected.operation.state == "FAILED"
        assert await bridge.observe("evt1") is None
    run(case())


def test_openhands_revocation_and_hook_compatibility(tmp_path):
    async def case():
        current = True
        def policy(_):
            return PolicyDecision(current, "allowed" if current else "revoked")
        m = mapper(tmp_path)
        bridge = OpenHandsEventBridge(
            make_gate(policy), conversation_id="work-g5",
            principal_id="user-g5", work_item_id="work-g5")
        raw = {"id":"hook-1","kind":"observation","source":"hook"}
        event = OpenHandsEvent.from_mapping(raw, conversation_id="work-g5", sequence=0)
        current = False
        outcome = await bridge.accept(m.openhands_event(
            operation_id="hook-op", idempotency_key="hook-idem", event=event),
            raw, authenticated_conversation_id="work-g5", sequence=0)
        assert outcome.operation.state == "FAILED"
        assert await bridge.observe("hook-1") is None
    run(case())


@pytest.mark.parametrize("secret_reply", [
    {"content":[{"type":"text","text":"Authorization: Bearer supersecret"}]},
    {"content":[{"type":"text","text":"sk-proj-supersecret"}]},
    {"content":[{"type":"text","text":"ordinary"}], "structuredContent":{"access_token":"secret"}},
    {"content":[{"type":"text","text":"ordinary"}], "_meta":{"private_key":"secret"}},
])
def test_mcp_toolhive_credential_like_output_uncertain_never_replayed(tmp_path, secret_reply):
    class Client:
        calls = 0
        async def call_tool(self, name, args):
            self.calls += 1
            return secret_reply
    async def case():
        m = mapper(tmp_path)
        client = Client()
        bridge = ToolHiveMCPBoundary(make_gate(allow), {"server":client},
                                     (MCPToolGrant("server","read","mcp:read"),))
        req = m.mcp_call(operation_id="mcp-o", idempotency_key="mcp-k",
                         capability_id="mcp:read", server_id="server",
                         tool_name="read", arguments={"query":"x"})
        out = await bridge.call(req, server_id="server", tool_name="read",
                                arguments={"query":"x"})
        assert out.operation.state == "UNCERTAIN"
        assert out.payload is None
        assert (await bridge.call(req, server_id="server", tool_name="read",
                                  arguments={"query":"x"})).duplicate
        assert client.calls == 1
    run(case())


def test_mcp_toolhive_sensitive_arguments_never_reach_client(tmp_path):
    class Client:
        calls = 0
        async def call_tool(self, name, args):
            self.calls += 1
            return {"content":[{"type":"text","text":"ok"}]}
    async def case():
        client = Client()
        bridge = ToolHiveMCPBoundary(make_gate(allow), {"server":client},
                                     (MCPToolGrant("server","read","mcp:read"),))
        evil = {"api_key":"secret"}
        req = OperationRequest("op-1","user-g5","machine-g5","mcp:read",
                               "work-g5","idem-1",{"server_id":"server",
                               "tool_name":"read","arguments":evil})
        result = await bridge.call(req, server_id="server", tool_name="read",
                                   arguments=evil)
        assert result.operation.state == "FAILED"
        assert client.calls == 0
    run(case())



def test_mcp_workspace_path_pin_and_camelcase_secret_guard(tmp_path):
    m = mapper(tmp_path)
    for bad in (
        {"path": str(tmp_path.parent / "outside.txt")},
        {"nested": {"filePath": str(tmp_path.parent / "outside.txt")}},
        {"clientSecret": "secret"},
        {"apiKey": "secret"},
    ):
        with pytest.raises(InteropMappingDenied):
            m.mcp_call(operation_id="op", idempotency_key="key",
                       capability_id="mcp:read", server_id="local",
                       tool_name="read", arguments=bad)
    safe = tmp_path / "nested"
    safe.mkdir()
    req = m.mcp_call(operation_id="good", idempotency_key="good",
                     capability_id="mcp:read", server_id="local",
                     tool_name="read", arguments={"path": str(safe / "allowed.txt")})
    assert req.arguments["arguments"]["path"] == str(safe / "allowed.txt")


def test_openhands_rejects_malformed_typed_source_and_parent():
    for event in (
        {"id": "one", "kind": [], "source": "agent"},
        {"id": "one", "kind": "message", "source": {"forged": True}},
        {"id": "__root__", "kind": "message", "source": "agent"},
        {"id": "one", "kind": "message", "source": "agent", "parent_id": "one"},
    ):
        with pytest.raises(ValueError):
            OpenHandsEvent.from_mapping(event, conversation_id="work-g5", sequence=0)
