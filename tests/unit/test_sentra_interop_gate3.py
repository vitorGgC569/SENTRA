"""GATE-3: real ACP stdio races, forged requests, late results and ExecutorRegistry.

The only spawned program is a test-owned Python script under tmp_path; no
third-party daemons, agents, services, or elevated commands are executed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, OperationResult, PolicyDecision
from sentra_runtime.executor import AuthorizationRequired, ExecutorRegistry, InvalidOperation
from sentra_interop import (
    ACPProtocolError, ACPStdioTransport, ACPSessionAdapter,
    AgentIdentity, A2AEnvelope, A2ATaskBoundary, InteropGate, MCPToolGrant,
    ToolHiveMCPBoundary,
)

PEER = r"""
import json
import sys

mode = sys.argv[1]
pending = []
for line in sys.stdin:
    frame = json.loads(line)
    method = frame.get("method")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": frame["id"], "result": {"protocolVersion": 1}}), flush=True)
    elif method == "session/new":
        print(json.dumps({"jsonrpc": "2.0", "id": frame["id"], "result": {"sessionId": "gate3"}}), flush=True)
    elif method == "session/prompt":
        # Agent-initiated tools/terminal/filesystem can collide with a live
        # client request ID; a denial is never a successful tool execution.
        if mode == "collision":
            print(json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": frame["id"],
                              "params": {"name": "danger", "arguments": {}}}), flush=True)
            pending.append(frame)
        elif mode == "malformed":
            sys.stdout.write('{"jsonrpc":"2.0","id":1,"id":1,"result":{}}\n')
            sys.stdout.flush()
        elif mode == "mixed":
            print(json.dumps({"jsonrpc":"2.0","id":frame["id"],
                              "result":{},"error":{"code":-32600,"message":"bad"}}), flush=True)
        elif mode == "nonfinite":
            sys.stdout.write('{"jsonrpc":"2.0","id":'+str(frame["id"])+',"result":{"value":NaN}}\n')
            sys.stdout.flush()
        elif mode == "unexpected_id":
            print(json.dumps({"jsonrpc":"2.0","id":88888,"result":{}}), flush=True)
        elif mode == "disconnect":
            sys.exit(0)
        elif mode == "slow":
            pending.append(frame)
        elif mode == "late":
            pending.append(frame)
            if len(pending) == 2:
                for prev in pending:
                    print(json.dumps({"jsonrpc":"2.0","id":prev["id"],
                                      "result":{"stopReason":"end_turn","echo":prev["params"]["prompt"][0]["text"]}}),
                          flush=True)
                pending.clear()
        else:
            pending.append(frame)
            if len(pending) == 16:
                for prev in reversed(pending):
                    print(json.dumps({"jsonrpc":"2.0","id":prev["id"],
                                      "result":{"stopReason":"end_turn","echo":prev["params"]["prompt"][0]["text"]}}),
                          flush=True)
                pending.clear()
    elif method in ("session/cancel", "$/cancel_request"):
        # No ack means canceled remote work is not proven.
        pass
    elif mode == "collision" and "id" in frame:
        if frame.get("error", {}).get("code") == -32601:
            prev = pending.pop(0)
            print(json.dumps({"jsonrpc":"2.0","id":prev["id"],
                              "result":{"stopReason":"end_turn","echo":"denied"}}), flush=True)
"""


def req(index, cap="acp:prompt", args=None, work="workspace-one", principal="alice"):
    return OperationRequest(
        f"op-g3-{index}", principal, "machine-interoperability",
        cap, work, f"key-g3-{index}", args or {},
    )


def machine():
    return Machine(
        "machine-interoperability", "agent", "alice",
        tuple(Capability(c, c) for c in (
            "acp:launch", "acp:session", "acp:prompt", "acp:cancel",
            "a2a:ingest", "a2a:cancel", "mcp:read",
        )),
    )


def authorize(request):
    if request.capability_id == "acp:launch":
        return PolicyDecision(True, "pinned", {
            "executable_paths": [sys.executable],
            "cwd_roots": [request.arguments["cwd"]],
            "argv_sha256": hashlib.sha256(json.dumps(request.arguments["args"],
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        })
    return PolicyDecision(True, "authorized", {"work_item_ids": ["workspace-one"]})


async def spawn(tmp_path, mode, gate):
    source = tmp_path / "gate3_peer.py"
    source.write_text(PEER, encoding="utf-8")
    args = ("-u", str(source), mode)
    return await ACPStdioTransport.launch(
        sys.executable, args, cwd=str(tmp_path), gate=gate,
        request=req(f"spawn-{mode}", "acp:launch", {
            "executable": sys.executable, "args": list(args), "cwd": str(tmp_path),
        }),
    )


@pytest.mark.parametrize("mode", [
    "collision", "malformed", "mixed", "nonfinite", "unexpected_id", "disconnect",
])
def test_acp_peer_adversarial_envelopes_and_cleanup(tmp_path, mode):
    async def case():
        control = InteropGate(machine(), authorize)
        transport = await spawn(tmp_path, mode, control)
        child = transport.process
        try:
            if mode == "collision":
                # The agent uses the *same* id as the inflight client request.
                response = await transport.request(
                    "session/prompt", {"prompt": [{"type":"text","text":"hi"}]}, 2)
                assert response["echo"] == "denied"
            else:
                with pytest.raises(ACPProtocolError):
                    await transport.request(
                        "session/prompt", {"prompt": [{"type":"text","text":"hi"}]}, 2)
                assert transport._dead is not None
                # A compromised peer is terminated by the read loop itself,
                # before any caller invokes cleanup.
                await asyncio.wait_for(child.wait(), 2)
                assert child.returncode is not None
                with pytest.raises(ACPProtocolError):
                    await transport.next_update(timeout=0.5)
        finally:
            await transport.close()
        assert child.returncode is not None
        assert transport._read_task.done()
        assert not transport._pending
    asyncio.run(case())


def test_acp_concurrent_reversed_responses_unique_ids(tmp_path):
    async def case():
        transport = await spawn(tmp_path, "concurrent", InteropGate(machine(), authorize))
        try:
            values = await asyncio.gather(*(
                transport.request("session/prompt", {
                    "prompt": [{"type": "text", "text": f"parallel-{n}"}],
                }, 3) for n in range(16)
            ))
            assert [v["echo"] for v in values] == [f"parallel-{n}" for n in range(16)]
            assert transport._sequence == 16
            assert not transport._pending
        finally:
            await transport.close()
        assert transport.process.returncode is not None
    asyncio.run(case())


def test_acp_timeout_late_response_does_not_break_new_request(tmp_path):
    async def case():
        transport = await spawn(tmp_path, "late", InteropGate(machine(), authorize))
        try:
            with pytest.raises(asyncio.TimeoutError):
                await transport.request("session/prompt", {
                    "prompt":[{"type":"text","text":"old-uncertain"}]}, 0.05)
            new = await transport.request("session/prompt", {
                "prompt":[{"type":"text","text":"new"}]}, 2)
            assert new["echo"] == "new"
            assert not transport._pending
            assert not transport._expired_ids
            assert transport._dead is None
        finally:
            await transport.close()
    asyncio.run(case())


def test_acp_caller_cancel_does_not_reuse_remote_id(tmp_path):
    async def case():
        transport = await spawn(tmp_path, "late", InteropGate(machine(), authorize))
        try:
            old = asyncio.create_task(transport.request("session/prompt", {
                "prompt":[{"type":"text","text":"cancelled"}]}, 3))
            await asyncio.sleep(0.04)
            old.cancel()
            with pytest.raises(asyncio.CancelledError):
                await old
            new = await transport.request("session/prompt", {
                "prompt":[{"type":"text","text":"survivor"}]}, 3)
            assert new["echo"] == "survivor"
            assert transport._dead is None
        finally:
            await transport.close()
    asyncio.run(case())


def test_acp_close_with_pending_request_no_orphan(tmp_path):
    async def case():
        transport = await spawn(tmp_path, "slow", InteropGate(machine(), authorize))
        child = transport.process
        waiting = asyncio.create_task(transport.request("session/prompt", {
            "prompt":[{"type":"text","text":"unfinished"}]}, 20))
        try:
            await asyncio.sleep(0.05)
            await asyncio.wait_for(transport.close(), 4)
            with pytest.raises(ACPProtocolError):
                await asyncio.wait_for(waiting, 1)
        finally:
            await transport.close()
        assert child.returncode is not None
        assert transport._read_task.done()
        assert child.stdin is not None and child.stdin.is_closing()
    asyncio.run(case())


def test_acp_reattach_cannot_promote_agent_initiated_commands(tmp_path):
    async def case():
        gate = InteropGate(machine(), authorize)
        transport = await spawn(tmp_path, "collision", gate)
        try:
            first = ACPSessionAdapter(gate, transport, workspace=str(tmp_path))
            assert (await first.open(req("session-first", "acp:session", {"cwd": str(tmp_path)}), cwd=str(tmp_path))).operation.state == "SUCCEEDED"
            assert (await first.prompt(req("prompt-first", args={"session_id":"gate3","text":"one"}), "one", timeout=2)).operation.state == "SUCCEEDED"
            # Simulate an adapter rebind on the same trusted stdio connection.
            rebound = ACPSessionAdapter(gate, transport, workspace=str(tmp_path))
            assert (await rebound.open(req("session-rebound", "acp:session", {"cwd": str(tmp_path)}), cwd=str(tmp_path))).operation.state == "SUCCEEDED"
            assert (await rebound.prompt(req("prompt-rebound", args={"session_id":"gate3","text":"two"}), "two", timeout=2)).operation.state == "SUCCEEDED"
        finally:
            await transport.close()
        assert transport.process.returncode is not None
    asyncio.run(case())


def test_revocation_during_mcp_call_and_workspace_scope():
    class Client:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def call_tool(self, name, arguments):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return {"content": [{"type":"text","text":"remote may have executed"}]}

    async def case():
        grants = True
        def policy(request):
            if not grants:
                return PolicyDecision(False, "revoked")
            return PolicyDecision(True, "workspace policy", {
                "work_item_ids": ["workspace-one"],
                "principal_ids": ["alice"],
            })
        control = InteropGate(machine(), policy)
        client = Client()
        boundary = ToolHiveMCPBoundary(control, {"local":client}, (
            MCPToolGrant("local", "read", "mcp:read"),))
        args = {"query":"work"}
        def inv(index, work="workspace-one"):
            return req(index, "mcp:read", {
                "server_id":"local", "tool_name":"read", "arguments":args}, work=work)
        out_of_scope = await boundary.call(inv("scope", work="workspace-other"),
                                           server_id="local", tool_name="read", arguments=args)
        assert out_of_scope.operation.state == "FAILED"
        assert client.calls == 0
        in_flight = asyncio.create_task(boundary.call(
            inv("active"), server_id="local", tool_name="read", arguments=args))
        await asyncio.wait_for(client.started.wait(), 2)
        grants = False
        client.release.set()
        revoked = await asyncio.wait_for(in_flight, 2)
        assert revoked.operation.state == "UNCERTAIN"
        assert revoked.payload is None
        assert client.calls == 1
        again = await boundary.call(inv("fresh"), server_id="local", tool_name="read", arguments=args)
        assert again.operation.state == "FAILED"
        assert client.calls == 1
    asyncio.run(case())


def test_a2a_workspace_scope_and_policy_revocation():
    async def case():
        grants = True
        def policy(request):
            return PolicyDecision(grants, "current", {"work_item_ids":["workspace-one"]})
        identity = AgentIdentity("alice", "remote", "trusted-domain")
        gateway = A2ATaskBoundary(
            InteropGate(machine(), policy), trusted_agents=frozenset({identity}))
        bad = A2AEnvelope(identity, "task", "workspace-other", "event0", 0, "submitted")
        assert (await gateway.accept(req("bad-scope", "a2a:ingest"),
                                     bad)).operation.state == "FAILED"
        assert await gateway.state("task") is None
        start = A2AEnvelope(identity, "task", "workspace-one", "event0", 0, "submitted")
        assert (await gateway.accept(req("start", "a2a:ingest"),
                                     start)).operation.state == "SUCCEEDED"
        grants = False
        update = A2AEnvelope(identity, "task", "workspace-one", "event1", 1, "working")
        assert (await gateway.accept(req("revoked", "a2a:ingest"),
                                     update)).operation.state == "FAILED"
        assert await gateway.state("task") == "submitted"
    asyncio.run(case())


def test_executor_registry_to_mcp_boundary_policy_e2e():
    class AgentExecutor:
        def __init__(self, bridge):
            self.bridge = bridge
            self.results = {}
            self.calls = 0

        async def discover(self, host):
            return host.capabilities

        async def start(self, request):
            self.calls += 1
            result = await self.bridge.call(
                request, server_id="local", tool_name="read",
                arguments=request.arguments["arguments"])
            self.results[request.operation_id] = result.operation
            return result.operation

        async def observe(self, operation_id):
            return self.results[operation_id]

        async def reconcile(self, operation_id):
            return self.results[operation_id]

        async def cancel(self, operation_id):
            return OperationResult(operation_id, "UNCERTAIN", error="remote cancel unconfirmed")

        async def cleanup(self, operation_id):
            return None

    class Client:
        calls = 0
        async def call_tool(self, name, arguments):
            self.calls += 1
            return {"content":[{"type":"text","text":"approved"}]}

    async def case():
        client = Client()
        host = machine()
        bridge = ToolHiveMCPBoundary(InteropGate(host, lambda _: PolicyDecision(True,"admitted")),
                                     {"local":client}, (MCPToolGrant("local","read","mcp:read"),))
        exec_adapter = AgentExecutor(bridge)
        no_policy = ExecutorRegistry()
        no_policy.register(host, exec_adapter)
        cmd = req("reg", "mcp:read", {"server_id":"local","tool_name":"read","arguments":{}})
        with pytest.raises(AuthorizationRequired):
            await no_policy.submit(cmd)
        assert client.calls == 0
        denied = ExecutorRegistry(lambda _: PolicyDecision(False, "not allowed"))
        denied.register(host, exec_adapter)
        with pytest.raises(AuthorizationRequired):
            await denied.submit(cmd)
        assert client.calls == 0
        registry = ExecutorRegistry(lambda _: PolicyDecision(True, "grant"))
        registry.register(host, exec_adapter)
        result = await registry.submit(cmd)
        assert result.state == "SUCCEEDED"
        duplicate = await registry.submit(cmd)
        assert duplicate.state == "SUCCEEDED"
        assert await registry.reconcile(cmd.operation_id) == result
        assert client.calls == exec_adapter.calls == 1
        with pytest.raises(InvalidOperation):
            await registry.submit(req("nonexistent", "not-advertised"))
    asyncio.run(case())



def test_a2a_same_operation_id_cannot_claim_another_event():
    async def case():
        identity = AgentIdentity("alice", "remote", "trusted-domain")
        gateway = A2ATaskBoundary(
            InteropGate(machine(), authorize), trusted_agents=frozenset({identity}))
        request = req("a2a-collision", "a2a:ingest")
        event1 = A2AEnvelope(identity, "task-collision", "workspace-one",
                             "event-0", 0, "submitted")
        assert (await gateway.accept(request, event1)).operation.state == "SUCCEEDED"
        forged = A2AEnvelope(identity, "task-collision", "workspace-one",
                             "event-1", 1, "completed")
        result = await gateway.accept(request, forged)
        assert result.operation.state == "FAILED"
        assert await gateway.state("task-collision") == "submitted"
    asyncio.run(case())


def test_a2a_cancel_rejects_foreign_task_ack():
    class Forged:
        async def cancel_task(self, task_id):
            return {"id":"foreign-task", "contextId":"workspace-one",
                    "status":{"state":"TASK_STATE_CANCELED"}}

    async def case():
        identity = AgentIdentity("alice", "remote", "trusted-domain")
        gateway = A2ATaskBoundary(
            InteropGate(machine(), authorize), trusted_agents=frozenset({identity}))
        event = A2AEnvelope(identity, "task-cancel-foreign", "workspace-one",
                            "event-0", 0, "submitted")
        assert (await gateway.accept(req("a2a-start", "a2a:ingest"),
                                     event)).operation.state == "SUCCEEDED"
        result = await gateway.cancel(req("a2a-cancel", "a2a:cancel"),
                                      task_id="task-cancel-foreign", transport=Forged())
        # The fake peer acknowledged a different task, so cancellation of the
        # submitted task remains uncertain and its local state is unchanged.
        assert result.operation.state == "UNCERTAIN"
        assert await gateway.state("task-cancel-foreign") == "submitted"
        retry = await gateway.cancel(req("a2a-cancel", "a2a:cancel"),
                                     task_id="task-cancel-foreign", transport=Forged())
        assert retry.operation.state == "UNCERTAIN"
    asyncio.run(case())


def test_acp_concurrent_session_open_yields_only_one_remote_session(tmp_path):
    async def case():
        control = InteropGate(machine(), authorize)
        transport = await spawn(tmp_path, "slow", control)
        try:
            adapter = ACPSessionAdapter(control, transport, workspace=str(tmp_path))
            first, second = await asyncio.gather(
                adapter.open(req("open-a", "acp:session", {"cwd": str(tmp_path)}), cwd=str(tmp_path), timeout=2),
                adapter.open(req("open-b", "acp:session", {"cwd": str(tmp_path)}), cwd=str(tmp_path), timeout=2),
            )
            assert sorted([first.operation.state, second.operation.state]) == ["FAILED", "SUCCEEDED"]
            assert adapter.session_id == "gate3"
        finally:
            await transport.close()
    asyncio.run(case())



def test_acp_launch_argv_pin_deny_before_spawn(tmp_path):
    async def case():
        program = tmp_path / "pin_peer.py"
        program.write_text(PEER, encoding="utf-8")
        forbidden = tmp_path / "executed.txt"
        args = ("-u", str(program), "slow")
        request = req("pin-reject", "acp:launch", {
            "executable": sys.executable, "args": list(args), "cwd": str(tmp_path),
        })
        def malicious_grant(_):
            # Allow executable and directory, but pin a different argv.
            return PolicyDecision(True, "wrong argv", {
                "executable_paths": [sys.executable],
                "cwd_roots": [str(tmp_path)],
                "argv_sha256": "0" * 64,
            })
        with pytest.raises(ACPProtocolError):
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=InteropGate(machine(), malicious_grant),
                                           request=request)
        assert not forbidden.exists()
    asyncio.run(case())


def test_acp_outbound_privileged_methods_rejected_even_after_launch(tmp_path):
    async def case():
        transport = await spawn(tmp_path, "slow", InteropGate(machine(), authorize))
        try:
            with pytest.raises(ACPProtocolError):
                await transport.request("terminal/create", {"command": "forbidden"}, 2)
            with pytest.raises(ACPProtocolError):
                await transport.request("tools/call", {"name": "danger"}, 2)
            with pytest.raises(ACPProtocolError):
                await transport.notify("fs/write_text_file", {"path": "forbidden"})
            assert transport._sequence == 0
        finally:
            await transport.close()
    asyncio.run(case())


def test_acp_request_args_bind_session_prompt_and_cancel(tmp_path):
    async def case():
        control = InteropGate(machine(), authorize)
        transport = await spawn(tmp_path, "collision", control)
        try:
            client = ACPSessionAdapter(control, transport, workspace=str(tmp_path))
            bad_open = await client.open(req("scope-unbound", "acp:session"), cwd=str(tmp_path))
            assert bad_open.operation.state == "FAILED"
            assert transport._sequence == 0
            good_open = await client.open(req("scope-bound", "acp:session", {"cwd":str(tmp_path)}),
                                          cwd=str(tmp_path))
            assert good_open.operation.state == "SUCCEEDED"
            bad_prompt = await client.prompt(req("payload-unbound"), "secret", timeout=2)
            assert bad_prompt.operation.state == "FAILED"
            bad_cancel = await client.cancel(req("cancel-unbound", "acp:cancel"))
            assert bad_cancel.state == "FAILED"
            assert transport._sequence == 2  # initialize and session/new only
            okay = await client.prompt(req("payload-good", args={"session_id":"gate3",
                                                                  "text":"secret"}), "secret", timeout=2)
            assert okay.operation.state == "SUCCEEDED"
            # Changing prompt text while replaying operation_id cannot assert
            # success from the original request.
            replay = await client.prompt(req("payload-good", args={"session_id":"gate3",
                                                                   "text":"different"}), "different", timeout=2)
            assert replay.operation.state == "FAILED"
        finally:
            await transport.close()
    asyncio.run(case())


def test_a2a_revocation_between_admission_and_state_mutation():
    async def case():
        evaluations = 0
        def check(_):
            nonlocal evaluations
            evaluations += 1
            # The admission grant is revoked before the event commit.
            return PolicyDecision(evaluations == 1,
                                  "initial grant" if evaluations == 1 else "revoked")
        control = InteropGate(machine(), check)
        identity = AgentIdentity("alice", "remote", "trusted-domain")
        bridge = A2ATaskBoundary(control, trusted_agents=frozenset({identity}))
        incoming = A2AEnvelope(identity, "race", "workspace-one", "event0", 0, "submitted")
        outcome = await bridge.accept(req("race", "a2a:ingest"), incoming)
        assert evaluations == 2
        assert outcome.operation.state == "FAILED"
        assert await bridge.state("race") is None
    asyncio.run(case())
