"""Contract tests for isolated SENTRA Agent Runtime interoperability boundaries."""
import asyncio
import hashlib
import json
import sys

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop import (
    A2AEnvelope, A2ATaskBoundary, A2AValidationError, AgentIdentity,
    ACPSessionAdapter, ACPStdioTransport, ACPProtocolError,
    ACPRegistryEntry, InteropGate, MCPToolGrant, OperationJournal,
    ToolHiveEndpoint, ToolHiveMCPBoundary,
)


CAPS = (
    "acp:launch", "acp:session", "acp:prompt", "acp:cancel",
    "a2a:ingest", "a2a:cancel", "mcp:server:read",
)


def make_gate(policy=None):
    machine = Machine("local-agent", "agent", "alice",
                      tuple(Capability(cap, cap) for cap in CAPS))
    return InteropGate(machine, policy)


def req(n, cap, *, args=None, principal="alice", work="work", key=None):
    return OperationRequest(f"op-{n}", principal, "local-agent", cap, work,
                            key or f"key-{n}", args or {})


def allow(_):
    return PolicyDecision(True, "granted")


def run(coro):
    return asyncio.run(coro)


def test_missing_capability_machine_and_policy_fail_closed():
    async def scenario():
        called = 0
        async def effect():
            nonlocal called
            called += 1
        gate = make_gate(None)
        for operation in [
            req(1, "mcp:server:read"),
            req(2, "not-advertised"),
            OperationRequest("op-3", "alice", "foreign", "acp:session", "work", "key-3"),
        ]:
            assert (await gate.execute(operation, effect)).operation.state == "FAILED"
        assert called == 0

        async def exploding(_):
            raise RuntimeError("policy service unavailable")
        bad = make_gate(exploding)
        assert (await bad.execute(req(4, "acp:session"), effect)).operation.state == "FAILED"
        assert called == 0

        constrained = make_gate(lambda _: PolicyDecision(True, "granted", {"new_scope": "ignored"}))
        assert (await constrained.execute(req(5, "acp:session"), effect)).operation.state == "FAILED"
        assert called == 0

        narrowed = make_gate(lambda _: PolicyDecision(True, "granted", {"principal_ids": ["bob"]}))
        assert (await narrowed.execute(req(6, "acp:session"), effect)).operation.state == "FAILED"
        assert called == 0
    run(scenario())


def test_parallel_idempotency_duplicate_ids_keys_and_timeout():
    async def scenario():
        calls = 0
        gate = make_gate(allow)
        async def effect():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return {"ok": True}
        request = req(11, "acp:prompt")
        first, duplicate = await asyncio.gather(gate.execute(request, effect), gate.execute(request, effect))
        assert calls == 1
        assert {first.operation.state, duplicate.operation.state} <= {"ACCEPTED", "SUCCEEDED"}
        again = await gate.execute(request, effect)
        assert again.duplicate and calls == 1
        assert (await gate.execute(req(12, "acp:prompt", key="key-11"), effect)).operation.state == "FAILED"
        assert calls == 1
        assert (await gate.execute(req(11, "acp:session", key="changed"), effect)).operation.state == "FAILED"

        async def slow():
            await asyncio.sleep(0.1)
        timeout = req(13, "acp:prompt")
        assert (await gate.execute(timeout, slow, timeout=0.001)).operation.state == "UNCERTAIN"
        assert (await gate.execute(timeout, effect)).operation.state == "UNCERTAIN"
        assert calls == 1
    run(scenario())


def test_cancelled_effect_is_uncertain_not_success():
    async def scenario():
        gate = make_gate(allow)
        operation = req(20, "acp:prompt")
        started = asyncio.Event()
        async def effect():
            started.set()
            await asyncio.sleep(5)
        task = asyncio.create_task(gate.execute(operation, effect))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await gate.journal.get(operation.operation_id)).state == "UNCERTAIN"
    run(scenario())


class FakeACP:
    def __init__(self):
        self.calls = []
        self.sent = []
        self.incoming = asyncio.Queue()
        self.version = 1

    async def request(self, method, params, timeout):
        self.calls.append((method, dict(params)))
        if method == "initialize":
            return {"protocolVersion": self.version}
        if method == "session/new":
            return {"sessionId": "sess-one"}
        if method == "session/prompt":
            return {"stopReason": "end_turn"}
        raise AssertionError(method)

    async def notify(self, method, params):
        self.sent.append((method, dict(params)))

    async def next_update(self, timeout):
        return await asyncio.wait_for(self.incoming.get(), timeout)

    async def close(self):
        return None


def test_acp_negotiate_prompt_stream_cancel_and_deny(tmp_path):
    async def scenario():
        gate = make_gate(allow)
        fake = FakeACP()
        agent = ACPSessionAdapter(gate, fake, workspace=str(tmp_path))
        assert (await agent.open(req(30, "acp:session", args={"cwd": str(tmp_path)}), cwd=str(tmp_path))).operation.state == "SUCCEEDED"
        assert fake.calls[0][0] == "initialize"
        assert fake.calls[0][1]["clientCapabilities"]["terminal"] is False
        assert fake.calls[1][1]["mcpServers"] == []
        assert (await agent.prompt(req(31, "acp:prompt", args={"session_id": "sess-one", "text": "hello"}), "hello")).operation.state == "SUCCEEDED"
        assert (await agent.prompt(req(31, "acp:prompt", args={"session_id": "sess-one", "text": "hello"}), "hello")).duplicate
        assert len([m for m, _ in fake.calls if m == "session/prompt"]) == 1

        await fake.incoming.put({"sessionId": "sess-one",
                                  "update": {"sessionUpdate": "agent_message_chunk",
                                             "content": {"type": "text", "text": "hello"}}})
        stream = agent.updates()
        assert (await anext(stream))["sessionUpdate"] == "agent_message_chunk"
        assert (await agent.cancel(req(32, "acp:cancel", args={"session_id": "sess-one"}))).state == "UNCERTAIN"
        assert fake.sent == [("session/cancel", {"sessionId": "sess-one"})]
        assert (await agent.cancel(req(32, "acp:cancel", args={"session_id": "sess-one"}))).state == "UNCERTAIN"
        assert len(fake.sent) == 1

        no_policy = ACPSessionAdapter(make_gate(None), FakeACP(), workspace=str(tmp_path))
        outcome = await no_policy.open(req(33, "acp:session", args={"cwd": str(tmp_path)}), cwd=str(tmp_path))
        assert outcome.operation.state == "FAILED"
        assert not no_policy.transport.calls

        bad_protocol = FakeACP()
        bad_protocol.version = 2
        adapter = ACPSessionAdapter(make_gate(allow), bad_protocol, workspace=str(tmp_path))
        assert (await adapter.open(req(34, "acp:session", args={"cwd": str(tmp_path)}), cwd=str(tmp_path))).operation.state == "UNCERTAIN"
        assert adapter.session_id is None
    run(scenario())


def test_acp_stdio_real_opt_in_protocol_roundtrip(tmp_path):
    script = (
        "import sys,json\n"
        "for line in sys.stdin:\n"
        " m=json.loads(line)\n"
        " if m.get('method')=='initialize': out={'protocolVersion':1}\n"
        " elif m.get('method')=='session/new': out={'sessionId':'real-stdio'}\n"
        " elif m.get('method')=='session/prompt': out={'stopReason':'end_turn'}\n"
        " else: out={}\n"
        " if 'id' in m:\n"
        "  print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':out}),flush=True)\n"
    )
    async def scenario():
        args = ("-u", "-c", script)
        launch = req(40, "acp:launch",
                     args={"executable": sys.executable, "args": list(args), "cwd": str(tmp_path)})
        with pytest.raises(ACPProtocolError):
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=make_gate(None), request=launch)
        with pytest.raises(ACPProtocolError):
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=make_gate(allow), request=launch)
        pinned_policy = lambda _: PolicyDecision(True, "granted", {
            "executable_paths": [sys.executable], "cwd_roots": [str(tmp_path)],
            "argv_sha256": hashlib.sha256(json.dumps(list(args), ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")).hexdigest(),
        })
        gate = make_gate(pinned_policy)
        transport = await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                                   gate=gate, request=launch)
        try:
            client = ACPSessionAdapter(gate, transport, workspace=str(tmp_path))
            assert (await client.open(req(41, "acp:session", args={"cwd": str(tmp_path)}), cwd=str(tmp_path))).operation.state == "SUCCEEDED"
            assert (await client.prompt(req(42, "acp:prompt", args={"session_id": "real-stdio", "text": "works"}), "works")).operation.state == "SUCCEEDED"
        finally:
            await transport.close()
    run(scenario())


def test_a2a_identity_stream_state_and_terminal_immutability():
    async def scenario():
        principal = AgentIdentity("alice", "agent-a", "sentra")
        boundary = A2ATaskBoundary(make_gate(allow), trusted_agents=frozenset({principal}))
        def event(i, state):
            return A2AEnvelope(principal, "task1", "work", f"evt{i}", i, state)
        assert (await boundary.accept(req(50, "a2a:ingest"), event(0, "submitted"))).operation.state == "SUCCEEDED"
        assert (await boundary.accept(req(51, "a2a:ingest"), event(1, "working"))).operation.state == "SUCCEEDED"
        assert (await boundary.accept(req(52, "a2a:ingest"), event(2, "completed"))).operation.state == "SUCCEEDED"
        assert await boundary.state("task1") == "completed"
        late = await boundary.accept(req(53, "a2a:ingest"), event(3, "working"))
        assert late.operation.state == "FAILED"
        assert await boundary.state("task1") == "completed"
        intruder = await boundary.accept(req(54, "a2a:ingest", principal="bob"), event(4, "working"))
        assert intruder.operation.state == "FAILED"
        with pytest.raises(A2AValidationError):
            A2AEnvelope(principal, "task2", "work", "evt", 0, "submitted",
                        ({"type": "file", "uri": "file:///secret"},))
        wire = {"id": "t-10", "contextId": "ctx", "status": {
            "state": "TASK_STATE_WORKING", "message": {"parts": [{"text": "progress"}]}}}
        parsed_wire = dict(wire)
        parsed_wire["status"] = {**wire["status"], "state": "working"}
        parsed = A2AEnvelope.from_task_event(parsed_wire, identity=principal,
                                              authenticated_principal_id="alice",
                                              event_id="evt-remote", sequence=5)
        assert parsed.parts[0]["text"] == "progress"
        with pytest.raises(A2AValidationError):
            A2AEnvelope.from_task_event(parsed_wire, identity=principal,
                                        authenticated_principal_id="bob",
                                        event_id="evt-remote", sequence=5)
    run(scenario())


def test_a2a_cancel_requires_remote_confirmation():
    class Pending:
        async def cancel_task(self, task_id):
            return {"status": {"state": "working"}}
    async def scenario():
        p = AgentIdentity("alice", "agent-a", "sentra")
        b = A2ATaskBoundary(make_gate(allow), trusted_agents=frozenset({p}))
        await b.accept(req(60, "a2a:ingest"), A2AEnvelope(p, "task2", "work", "e0", 0, "submitted"))
        result = await b.cancel(req(61, "a2a:cancel"), task_id="task2", transport=Pending())
        assert result.operation.state == "UNCERTAIN"
        assert (await b.cancel(req(61, "a2a:cancel"), task_id="task2",
                               transport=Pending())).operation.state == "UNCERTAIN"
    run(scenario())


def test_mcp_toolhive_boundary_policy_scope_dedupe_and_error():
    class Client:
        def __init__(self):
            self.count = 0
        async def call_tool(self, name, arguments):
            self.count += 1
            if arguments.get("bad"):
                return {"isError": True, "content": []}
            return {"isError": False, "content": [{"type": "text", "text": "ok"}]}
    async def scenario():
        cli = Client()
        boundary = ToolHiveMCPBoundary(
            make_gate(allow), {"server": cli},
            (MCPToolGrant("server", "read", "mcp:server:read"),))
        args = {"path": "doc"}
        payload = {"server_id": "server", "tool_name": "read", "arguments": args}
        request = req(70, "mcp:server:read", args=payload)
        outcome = await boundary.call(request, server_id="server", tool_name="read", arguments=args)
        assert outcome.operation.state == "SUCCEEDED"
        assert outcome.payload["content"][0]["text"] == "ok"
        assert (await boundary.call(request, server_id="server", tool_name="read",
                                    arguments=args)).duplicate
        assert cli.count == 1
        assert (await boundary.call(req(71, "mcp:server:read"), server_id="server",
                                    tool_name="read", arguments=args)).operation.state == "FAILED"
        assert (await boundary.call(req(72, "mcp:server:read"), server_id="unknown",
                                    tool_name="read", arguments=args)).operation.state == "FAILED"
        bad_args = {"bad": True}
        bad = req(73, "mcp:server:read",
                  args={"server_id": "server", "tool_name": "read", "arguments": bad_args})
        assert (await boundary.call(bad, server_id="server", tool_name="read",
                                    arguments=bad_args)).operation.state == "FAILED"
        assert cli.count == 2
    run(scenario())


def test_registry_version_pin_and_endpoint_validation():
    raw = {"id": "codex-acp", "name": "Codex", "version": "2.1.1",
           "distribution": {"npx": {"package": "@agentclientprotocol/codex-acp@2.1.1"}}}
    assert ACPRegistryEntry.from_mapping(raw, pinned_version="2.1.1").agent_id == "codex-acp"
    with pytest.raises(ValueError):
        ACPRegistryEntry.from_mapping(raw, pinned_version="2.1.0")
    with pytest.raises(ValueError):
        ACPRegistryEntry.from_mapping({**raw, "distribution": {
            "npx": {"package": "codex-acp@latest"}}}, pinned_version="2.1.1")
    assert ToolHiveEndpoint("local", "http://127.0.0.1:9000/mcp")
    with pytest.raises(ValueError):
        ToolHiveEndpoint("bad", "http://public.example/mcp")


def test_a2a_stream_artifact_chunking_and_default_deny():
    async def scenario():
        p = AgentIdentity("alice", "agent-a", "sentra")
        blocked = A2ATaskBoundary(make_gate(allow))
        first = A2AEnvelope(p, "task-art", "work", "e0", 0, "submitted")
        assert (await blocked.accept(req(80, "a2a:ingest"), first)).operation.state == "FAILED"
        assert await blocked.state("task-art") is None
        b = A2ATaskBoundary(make_gate(allow), trusted_agents=frozenset({p}))
        assert (await b.accept(req(81, "a2a:ingest"), first)).operation.state == "SUCCEEDED"

        status = A2AEnvelope.from_stream_response({
            "statusUpdate": {
                "taskId": "task-art", "contextId": "work",
                "status": {"state": "TASK_STATE_WORKING"},
            }}, identity=p, authenticated_principal_id="alice",
            event_id="e1", sequence=1)
        assert status.state == "working"
        assert (await b.accept(req(82, "a2a:ingest"), status)).operation.state == "SUCCEEDED"

        chunk1 = A2AEnvelope.from_stream_response({
            "artifactUpdate": {
                "taskId": "task-art", "contextId": "work",
                "artifact": {"artifactId": "art-1", "parts": [{"text": "one"}]},
                "append": False, "lastChunk": False,
            }}, identity=p, authenticated_principal_id="alice",
            event_id="e2", sequence=2, current_state="working")
        assert chunk1.artifact_id == "art-1"
        assert not chunk1.artifact_final
        assert (await b.accept(req(83, "a2a:ingest"), chunk1)).operation.state == "SUCCEEDED"

        incomplete_terminal = A2AEnvelope(p, "task-art", "work", "e3", 3, "completed")
        assert (await b.accept(req(84, "a2a:ingest"), incomplete_terminal)).operation.state == "FAILED"
        assert await b.state("task-art") == "working"

        chunk2 = A2AEnvelope.from_stream_response({
            "artifactUpdate": {
                "taskId": "task-art", "contextId": "work",
                "artifact": {"artifactId": "art-1", "parts": [{"text": "two"}]},
                "append": True, "lastChunk": True,
            }}, identity=p, authenticated_principal_id="alice",
            event_id="e4", sequence=4, current_state="working")
        assert (await b.accept(req(85, "a2a:ingest"), chunk2)).operation.state == "SUCCEEDED"
        assert (await b.accept(req(86, "a2a:ingest"),
                               A2AEnvelope(p, "task-art", "work", "e5", 5, "completed"))).operation.state == "SUCCEEDED"

        with pytest.raises(A2AValidationError):
            A2AEnvelope.from_stream_response({
                "artifactUpdate": {"taskId": "task-art", "contextId": "work",
                                   "artifact": {"artifactId": "art-2", "parts": []}}},
                identity=p, authenticated_principal_id="alice",
                event_id="unsafe", sequence=6)
    run(scenario())


def test_a2a_cancel_terminal_ack_and_openhands_pure_event():
    from sentra_interop import OpenHandsEvent
    class Ack:
        async def cancel_task(self, task_id):
            return {"id": task_id, "contextId": "work",
                    "status": {"state": "TASK_STATE_CANCELED"}}
    async def scenario():
        p = AgentIdentity("alice", "agent-a", "sentra")
        b = A2ATaskBoundary(make_gate(allow), trusted_agents=frozenset({p}))
        await b.accept(req(90, "a2a:ingest"),
                       A2AEnvelope(p, "task-cancel", "work", "e0", 0, "submitted"))
        outcome = await b.cancel(req(91, "a2a:cancel"), task_id="task-cancel", transport=Ack())
        assert outcome.operation.state == "CANCELLED"
        assert await b.state("task-cancel") == "canceled"
    run(scenario())
    event = OpenHandsEvent.from_mapping({"id": "ev-1", "kind": "message", "source": "agent"},
                                        conversation_id="conv-1", sequence=0)
    assert event.event_id == "ev-1"
    with pytest.raises(ValueError):
        OpenHandsEvent.from_mapping({"id": "ev-2", "kind": "tool", "source": "other"},
                                    conversation_id="conv-1", sequence=1)


def test_acp_stdio_denies_agent_initiated_permission_request(tmp_path):
    script = (
        "import sys,json\n"
        "first=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc':'2.0','id':99,'method':'session/request_permission',"
        "'params':{'sessionId':'remote','options':[]}}),flush=True)\n"
        "denial=json.loads(sys.stdin.readline())\n"
        "result={'protocolVersion':1} if denial.get('error',{}).get('code')==-32601 else {'protocolVersion':2}\n"
        "print(json.dumps({'jsonrpc':'2.0','id':first['id'],'result':result}),flush=True)\n"
    )
    async def scenario():
        args = ("-u", "-c", script)
        launch = req(100, "acp:launch", args={
            "executable": sys.executable, "args": list(args), "cwd": str(tmp_path)})
        policy = lambda _: PolicyDecision(True, "pinned", {
            "executable_paths": [sys.executable], "cwd_roots": [str(tmp_path)],
            "argv_sha256": hashlib.sha256(json.dumps(list(args), ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")).hexdigest(),
        })
        transport = await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                                   gate=make_gate(policy), request=launch)
        try:
            response = await transport.request("initialize", {"protocolVersion": 1}, timeout=3)
            assert response["protocolVersion"] == 1
        finally:
            await transport.close()
    run(scenario())


def test_a2a_replay_with_new_operation_denied_without_advancing_state():
    async def scenario():
        identity = AgentIdentity("alice", "agent-a", "sentra")
        gateway = A2ATaskBoundary(make_gate(allow), trusted_agents=frozenset({identity}))
        event = A2AEnvelope(identity, "task-replay", "work", "same", 0, "submitted")
        assert (await gateway.accept(req(101, "a2a:ingest"), event)).operation.state == "SUCCEEDED"
        assert (await gateway.accept(req(102, "a2a:ingest"), event)).operation.state == "FAILED"
        assert await gateway.state("task-replay") == "submitted"
    run(scenario())
