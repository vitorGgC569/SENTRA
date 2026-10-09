"""A2A and ToolHive/MCP untrusted payload, grant, replay, revocation tests."""
from __future__ import annotations

import asyncio

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop import (
    A2AEnvelope, A2ATaskBoundary, A2AValidationError, AgentIdentity,
    InteropGate, MCPToolGrant, ToolHiveMCPBoundary,
)


def make_request(number, cap, args=None, key=None):
    return OperationRequest(
        f"boundary-{number}", "local-user", "agent-machine", cap, "task-work",
        key or f"boundary-key-{number}", args or {},
    )


def make_gate(policy):
    machine = Machine(
        "agent-machine", "agent", "local-user",
        (Capability("a2a:ingest", "ingest"), Capability("a2a:cancel", "cancel"),
         Capability("mcp:read", "read")),
    )
    return InteropGate(machine, policy)


def accepted(_):
    return PolicyDecision(True, "approved")


IDENTITY = AgentIdentity("local-user", "trusted-agent", "domain-pinned")


@pytest.mark.parametrize("bad", [
    {"task": {"id": "task", "contextId": "task-work", "status": {"state": "working"}},
     "statusUpdate": {"taskId": "task", "contextId": "task-work", "status": {"state": "failed"}}},
    {"artifactUpdate": {"taskId": "task", "contextId": "task-work",
                        "artifact": {"artifactId": "x", "parts": [{"file": {"uri": "file:///secret"}}]}}},
    {"message": {"role": "agent", "parts": [{"text": "unsupported state"}]}},
    {"statusUpdate": {"taskId": "task", "contextId": "task-work", "status": {"state": "unknown"}}},
    {"task": {"id": "task", "taskId": "other", "contextId": "task-work", "status": {"state": "working"}}},
    {"task": {"id": "task", "contextId": "task-work", "status": {
        "state": "working", "message": {"parts": [{"text": "ok", "file": {"uri": "bad"}}]}}}},
])
def test_a2a_rejects_ambiguous_or_unexpected_payloads(bad):
    with pytest.raises(A2AValidationError):
        A2AEnvelope.from_stream_response(
            bad, identity=IDENTITY, authenticated_principal_id="local-user",
            event_id="e-1", sequence=0, current_state="working",
        )


def test_a2a_trusted_agent_and_concurrent_replay_are_fail_closed():
    async def scenario():
        event = A2AEnvelope(IDENTITY, "task-concurrent", "task-work", "evt0", 0, "submitted")
        untrusted = A2ATaskBoundary(make_gate(accepted))
        result = await untrusted.accept(make_request(1, "a2a:ingest"), event)
        assert result.operation.state == "FAILED"
        assert await untrusted.state(event.task_id) is None

        trusted = A2ATaskBoundary(make_gate(accepted), trusted_agents=frozenset({IDENTITY}))
        result_a, result_b = await asyncio.gather(
            trusted.accept(make_request(2, "a2a:ingest"), event),
            trusted.accept(make_request(3, "a2a:ingest"), event),
        )
        assert sorted([result_a.operation.state, result_b.operation.state]) == ["FAILED", "SUCCEEDED"]
        assert await trusted.state(event.task_id) == "submitted"
        stale = await trusted.accept(
            make_request(4, "a2a:ingest"),
            A2AEnvelope(IDENTITY, event.task_id, event.context_id, "evt-new", 0, "working"))
        assert stale.operation.state == "FAILED"
        assert await trusted.state(event.task_id) == "submitted"
    asyncio.run(scenario())


def test_a2a_policy_error_and_revocation_reject_before_ingest():
    async def scenario():
        enabled = True
        def policy(_):
            if not enabled:
                return PolicyDecision(False, "revoked")
            return PolicyDecision(True, "approved")
        gateway = A2ATaskBoundary(make_gate(policy), trusted_agents=frozenset({IDENTITY}))
        first = A2AEnvelope(IDENTITY, "task-rev", "task-work", "e0", 0, "submitted")
        assert (await gateway.accept(make_request(10, "a2a:ingest"), first)).operation.state == "SUCCEEDED"
        enabled = False
        second = A2AEnvelope(IDENTITY, "task-rev", "task-work", "e1", 1, "working")
        assert (await gateway.accept(make_request(11, "a2a:ingest"), second)).operation.state == "FAILED"
        assert await gateway.state("task-rev") == "submitted"
    asyncio.run(scenario())


class FakeMCPClient:
    def __init__(self, response):
        self.calls = 0
        self.response = response

    async def call_tool(self, name, arguments):
        self.calls += 1
        return self.response


def boundary(client, policy=accepted):
    return ToolHiveMCPBoundary(
        make_gate(policy), {"trusted": client}, (MCPToolGrant("trusted", "read", "mcp:read"),),
    )


def invocation(number, args=None, key=None):
    arguments = args if args is not None else {"text": "safe"}
    return (
        make_request(number, "mcp:read", {
            "server_id": "trusted", "tool_name": "read", "arguments": arguments,
        }, key=key),
        arguments,
    )


@pytest.mark.parametrize("bad_reply", [
    {"content": [{"type": "execute", "command": "whoami"}]},
    {"content": [{"type": "text", "text": "safe", "authority": "grant-all"}]},
    {"content": [{"type": "image", "data": "abc", "mimeType": "image/png"}]},
    {"content": "not-a-list"},
    {"content": [], "isError": "false"},
    {"content": [], "privileged_action": "execute"},
    {"content": [], "structuredContent": ["invalid-list"]},
    {"isError": False},
])
def test_toolhive_mcp_rejects_unexpected_results_and_dedupes(bad_reply):
    async def scenario():
        client = FakeMCPClient(bad_reply)
        bridge = boundary(client)
        request, args = invocation(20)
        first = await bridge.call(request, server_id="trusted", tool_name="read", arguments=args)
        assert first.operation.state == "UNCERTAIN"
        assert client.calls == 1
        second = await bridge.call(request, server_id="trusted", tool_name="read", arguments=args)
        assert second.duplicate and second.operation.state == "UNCERTAIN"
        assert client.calls == 1
    asyncio.run(scenario())


def test_toolhive_mcp_rejects_unauthorized_calls_before_io_and_replay_key():
    async def scenario():
        client = FakeMCPClient({"content": [{"type": "text", "text": "ok"}]})
        revoked = False
        def policy(_):
            return PolicyDecision(not revoked, "revoked" if revoked else "granted")
        bridge = boundary(client, policy)
        request, args = invocation(30)
        assert (await bridge.call(request, server_id="trusted", tool_name="read",
                                  arguments=args)).operation.state == "SUCCEEDED"
        assert client.calls == 1
        conflict, args2 = invocation(31, key=request.idempotency_key)
        assert (await bridge.call(conflict, server_id="trusted", tool_name="read",
                                  arguments=args2)).operation.state == "FAILED"
        assert client.calls == 1
        revoked = True
        fresh, fresh_args = invocation(32)
        assert (await bridge.call(fresh, server_id="trusted", tool_name="read",
                                  arguments=fresh_args)).operation.state == "FAILED"
        invalid = await bridge.call(make_request(33, "mcp:read"), server_id="trusted",
                                    tool_name="read", arguments={})
        assert invalid.operation.state == "FAILED"
        assert client.calls == 1
    asyncio.run(scenario())
