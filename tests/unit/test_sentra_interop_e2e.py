"""Real local ACP v1 stdio protocol tests. No external agents or daemons.

The Python agent is written into pytest's temporary directory and launched
through ACPStdioTransport, not called in process or mocked.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop import ACPProtocolError, ACPSessionAdapter, ACPStdioTransport, InteropGate


# A scripted ACP peer, deliberately unrelated to any external CLI installation.
# Writes only JSON-RPC frames on stdout. Its independent trace file proves
# whether its client requests were rejected, without creating privileged effects.
AGENT_SOURCE = r"""
import json
import sys

mode, trace_path, forbidden_path = sys.argv[1:]
session = "fixture-session"
prompt_id = None
pending_denials = set()
denied = []


def emit(data):
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":")), flush=True)


def trace(data):
    with open(trace_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(data) + "\n")


def reply(msg_id, value):
    emit({"jsonrpc": "2.0", "id": msg_id, "result": value})


def update(variant, **fields):
    emit({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": session, "update": {"sessionUpdate": variant, **fields}}})


for raw in sys.stdin:
    msg = json.loads(raw)
    method = msg.get("method")
    if method == "initialize":
        trace({"method": "initialize", "version": msg["params"].get("protocolVersion")})
        reply(msg["id"], {"protocolVersion": 1, "agentCapabilities": {"loadSession": False}})
    elif method == "session/new":
        trace({"method": "session/new",
               "mcpServers": msg["params"].get("mcpServers"),
               "clientCapabilities": "no-privileged-mcp"})
        reply(msg["id"], {"sessionId": session})
    elif method == "session/prompt":
        prompt_id = msg["id"]
        trace({"method": "session/prompt"})
        update("agent_message_chunk", messageId="msg-1",
               content={"type": "text", "text": "hello over stdio"})
        update("tool_call", toolCallId="tool-observation", title="No authority",
               kind="execute", status="pending", name="write_file",
               rawInput={"path": forbidden_path, "content": "MUST_NOT_CREATE"})
        if mode == "roundtrip":
            # All three request classes MUST be rejected by the client.
            for idx, name, params in (
                (900, "session/request_permission",
                 {"sessionId": session, "toolCall": {"toolCallId": "danger"}, "options": []}),
                (901, "terminal/create", {"command": "SHOULD_NEVER_RUN"}),
                (902, "fs/write_text_file",
                 {"path": forbidden_path, "content": "MUST_NOT_CREATE"}),
                (903, "tools/call",
                 {"name": "write_file", "arguments": {
                     "path": forbidden_path, "content": "MUST_NOT_CREATE"}}),
            ):
                pending_denials.add(idx)
                emit({"jsonrpc": "2.0", "id": idx, "method": name, "params": params})
        # Other modes wait for cancellation or for client-side timeout.
    elif method == "session/cancel":
        trace({"method": "session/cancel", "sessionId": msg["params"].get("sessionId")})
        if mode == "cancel" and prompt_id is not None:
            reply(prompt_id, {"stopReason": "cancelled"})
            prompt_id = None
    elif "id" in msg and method is None:
        err = msg.get("error", {})
        trace({"request_id": msg["id"], "error_code": err.get("code")})
        denied.append((msg["id"], err.get("code")))
        pending_denials.discard(msg["id"])
        if mode == "roundtrip" and not pending_denials and prompt_id is not None:
            trace({"denials": denied})
            reply(prompt_id, {"stopReason": "end_turn"})
            prompt_id = None
    else:
        trace({"unexpected": str(method)})
"""


def gate(policy=None):
    machine = Machine(
        "fixture", "agent", "tester",
        tuple(Capability(item, item) for item in (
            "acp:launch", "acp:session", "acp:prompt", "acp:cancel"
        )),
    )
    return InteropGate(machine, policy)


def permit(request: OperationRequest) -> PolicyDecision:
    # This test uses path pins; no generic blanket spawn grant.
    if request.capability_id == "acp:launch":
        return PolicyDecision(True, "pinned local fixture", {
            "executable_paths": [sys.executable],
            "cwd_roots": [request.arguments["cwd"]],
            "argv_sha256": hashlib.sha256(json.dumps(request.arguments["args"],
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        })
    return PolicyDecision(True, "test-only grant")


def op(idx, capability, arguments=None):
    return OperationRequest(
        f"fixture-{idx}", "tester", "fixture", capability,
        "test-work", f"fixture-key-{idx}", arguments or {},
    )


@pytest.fixture
def agent_fixture(tmp_path):
    script = tmp_path / "local_acp_agent.py"
    script.write_text(AGENT_SOURCE, encoding="utf-8")
    return script


async def launch(script: Path, mode: str, authority: InteropGate):
    trace = script.parent / (mode + "-trace.jsonl")
    forbidden = script.parent / (mode + "-forbidden.txt")
    args = ("-u", str(script), mode, str(trace), str(forbidden))
    request = op("launch-" + mode, "acp:launch", {
        "executable": sys.executable,
        "args": list(args),
        "cwd": str(script.parent),
    })
    transport = await ACPStdioTransport.launch(
        sys.executable, args, cwd=str(script.parent),
        gate=authority, request=request,
    )
    return transport, trace, forbidden


def parse_trace(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("mode", ["roundtrip", "cancel", "timeout"])
def test_real_acp_stdio_lifecycle_and_cleanup(agent_fixture, mode):
    async def scenario():
        authority = gate(permit)
        transport, trace, forbidden = await launch(agent_fixture, mode, authority)
        process = transport.process
        try:
            adapter = ACPSessionAdapter(authority, transport, workspace=str(agent_fixture.parent))
            created = await adapter.open(op("new-" + mode, "acp:session", {"cwd": str(agent_fixture.parent)}),
                                         cwd=str(agent_fixture.parent), timeout=3)
            assert created.operation.state == "SUCCEEDED"
            assert adapter.session_id == "fixture-session"
            assert created.payload == "fixture-session"

            prompt_request = op("prompt-" + mode, "acp:prompt", {"session_id": "fixture-session", "text": "check stdio"})
            turn = asyncio.create_task(adapter.prompt(prompt_request, "check stdio", timeout=0.15 if mode == "timeout" else 3))
            updates = adapter.updates(timeout=2)
            chunk = await anext(updates)
            try:
                tool_observation = await anext(updates)
            except asyncio.TimeoutError as exc:
                raise AssertionError(
                    f"ACP reader stalled; dead={transport._dead!r}, returncode={process.returncode}, "
                    f"trace={parse_trace(trace) if trace.exists() else []}"
                ) from exc
            assert chunk["sessionUpdate"] == "agent_message_chunk"
            assert chunk["content"]["text"] == "hello over stdio"
            assert tool_observation["sessionUpdate"] == "tool_call"
            assert tool_observation["rawInput"]["path"] == str(forbidden)
            # Even a malicious tool_call update is only telemetry, not a grant.
            assert not forbidden.exists()

            if mode == "roundtrip":
                answer = await asyncio.wait_for(turn, timeout=3)
                assert answer.operation.state == "SUCCEEDED"
                assert answer.payload == {"stopReason": "end_turn"}
                entries = parse_trace(trace)
                refusals = [row for row in entries if "error_code" in row]
                assert {row["request_id"] for row in refusals} == {900, 901, 902, 903}
                assert all(row["error_code"] == -32601 for row in refusals)
                assert not forbidden.exists()
                again = await adapter.prompt(prompt_request, "check stdio", timeout=3)
                assert again.duplicate
                assert sum(row.get("method") == "session/prompt" for row in parse_trace(trace)) == 1
            elif mode == "cancel":
                cancel_request = op("cancel", "acp:cancel", {"session_id": "fixture-session"})
                sent = await adapter.cancel(cancel_request)
                assert sent.state == "UNCERTAIN"
                assert (await adapter.cancel(cancel_request)).state == "UNCERTAIN"
                answer = await asyncio.wait_for(turn, timeout=3)
                assert answer.operation.state == "CANCELLED"
                assert sum(row.get("method") == "session/cancel" for row in parse_trace(trace)) == 1
            else:
                answer = await asyncio.wait_for(turn, timeout=3)
                assert answer.operation.state == "UNCERTAIN"
                assert "timeout" in answer.operation.error
                duplicate = await adapter.prompt(prompt_request, "check stdio", timeout=0.1)
                assert duplicate.duplicate and duplicate.operation.state == "UNCERTAIN"
                assert sum(row.get("method") == "session/prompt" for row in parse_trace(trace)) == 1
            assert not forbidden.exists()
        finally:
            await transport.close()
            await transport.close()
        assert process.returncode is not None
        assert process.stdin is not None and process.stdin.is_closing()
        assert transport._read_task.done()
    asyncio.run(scenario())


def test_real_stdio_spawn_denied_before_process_creation(agent_fixture):
    async def scenario():
        authority = gate(None)
        trace = agent_fixture.parent / "roundtrip-trace.jsonl"
        with pytest.raises(ACPProtocolError):
            await launch(agent_fixture, "roundtrip", authority)
        assert not trace.exists()
    asyncio.run(scenario())



def test_real_stdio_rejects_unapproved_environment(agent_fixture):
    async def scenario():
        args = (
            "-u", str(agent_fixture), "roundtrip",
            str(agent_fixture.parent / "unapproved-env-trace.jsonl"),
            str(agent_fixture.parent / "forbidden.txt"),
        )
        request = op("env-check", "acp:launch", {
            "executable": sys.executable, "args": list(args), "cwd": str(agent_fixture.parent),
        })
        with pytest.raises(ACPProtocolError, match="ENV_DENIED"):
            await ACPStdioTransport.launch(
                sys.executable, args, cwd=str(agent_fixture.parent),
                gate=gate(permit), request=request, env={"PYTHONPATH": str(agent_fixture.parent)},
            )
        assert not (agent_fixture.parent / "unapproved-env-trace.jsonl").exists()
    asyncio.run(scenario())
