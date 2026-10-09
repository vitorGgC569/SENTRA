"""Acceptance of real local JSON-RPC pipes; fixture is not an external agent.

ProtocolDouble cases isolate capability, malformed-response and policy failures.
No test here asserts that Codex/Antigravity or another provider is installed.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from sentra_interop.acp import ACPSessionAdapter, ACPStdioTransport, ACPProtocolError, ACPLaunchError
from sentra_interop.acp_local import ACPLocalLifecycle
from sentra_interop.acp_session import ACPSessionState, ACPSessionStore
from sentra_interop.gate import InteropGate, EffectRejected
from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision

CAPS = ("launch", "session", "prompt", "cancel", "resume", "load", "list", "close", "delete", "config", "mode")


def request(name, capability, arguments, *, principal="tester"):
    return OperationRequest("acp-wave-" + name, principal, "machine", "acp:" + capability,
                            "work", "key-" + name, arguments)


def gate(*, allow=True):
    def policy(req):
        if req.capability_id == "acp:launch":
            return PolicyDecision(allow, "pinned fixture", {
                "executable_paths": [sys.executable], "cwd_roots": [req.arguments["cwd"]],
                "argv_sha256": hashlib.sha256(json.dumps(req.arguments["args"],
                     ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()})
        return PolicyDecision(allow, "fixture scope", {"principal_ids": ["tester"], "work_item_ids": ["work"]})
    return InteropGate(Machine("machine", "agent", "tester", tuple(
        Capability("acp:" + c, c) for c in CAPS)), policy)


AGENT = r'''
import json,sys
from pathlib import Path
revision=int(sys.argv[1]); trace=Path(sys.argv[2]); db=Path(sys.argv[3])
model={"id":"model","name":"Model","category":"model","type":"select","currentValue":"small",
       "options":[{"group":"g","name":"Models","options":[{"value":"small","name":"Small"},{"value":"large","name":"Large"}]}]}
toggle={"id":"toggle","name":"Toggle","type":"boolean","currentValue":False}
options=[model,toggle]
def send(m): print(json.dumps(m),flush=True)
def update(u): send({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"persisted","update":u}})
for line in sys.stdin:
 m=json.loads(line); method=m["method"]; p=m.get("params",{})
 with trace.open("a",encoding="utf8") as f: f.write(json.dumps({"method":method,"params":p})+"\n")
 if method=="initialize":
  out=({"protocolVersion":1,"agentCapabilities":{"loadSession":True,"sessionCapabilities":{k:{} for k in ("resume","list","close","delete")}}}
       if revision==1 else {"protocolVersion":2,"info":{"name":"local-fixture","version":"1.0.0"},"capabilities":{"session":{"delete":{}}}})
 elif method=="session/new":
  db.write_text("persisted",encoding="utf8"); out={"sessionId":"persisted","configOptions":options}
  if revision==1: out["modes"]={"currentModeId":"safe","availableModes":[{"id":"safe","name":"Safe"},{"id":"review","name":"Review"}]}
 elif method in ("session/resume","session/load"):
  if not db.exists():
   send({"jsonrpc":"2.0","id":m["id"],"error":{"code":-32000,"message":"missing"}}); continue
  out={"configOptions":options}
 elif method=="session/list": out={"sessions":[{"sessionId":"persisted","cwd":str(db.parent)}],"nextCursor":"page2"}
 elif method=="session/set_config_option":
  for o in options:
   if o["id"]==p["configId"]: o["currentValue"]=p["value"]
  out={"configOptions":options}
 elif method=="session/set_mode": out={}
 elif method=="session/prompt":
  update({"sessionUpdate":"tool_call" if revision==1 else "tool_call_update","toolCallId":"t","title":"Read","rawInput":{"path":"a"},"content":[]})
  update({"sessionUpdate":"tool_call_update","toolCallId":"t","status":"completed","rawInput":None})
  update({"sessionUpdate":"usage_update","used":12,"size":100,"cost":{"amount":0.02,"currency":"USD"},"_meta":{"provider":"fixture"}})
  out={"stopReason":"end_turn","_meta":{"accounting":"fixture"}} if revision==1 else {"messageId":"message-1"}
 elif method=="session/close": out={}
 elif method=="session/delete":
  db.unlink(missing_ok=True); out={}
 elif method=="session/cancel": continue
 else:
  send({"jsonrpc":"2.0","id":m["id"],"error":{"code":-32601,"message":"unsupported"}}); continue
 send({"jsonrpc":"2.0","id":m["id"],"result":out})
 if method=="session/prompt" and revision==2:
  update({"sessionUpdate":"state_update","state":"idle","stopReason":"end_turn"})
'''


@pytest.mark.parametrize("revision", [1, 2])
def test_real_stdio_full_lifecycle_reopen_mapping_without_new_replay(tmp_path, revision):
    async def case():
        script = tmp_path / "fixture.py"
        script.write_text(AGENT, encoding="utf8")
        trace, remote = tmp_path / "trace.jsonl", tmp_path / "remote-session.txt"
        argv = ("-u", str(script), str(revision), str(trace), str(remote))
        ledger = str(tmp_path / "sessions.sqlite")
        versions = (1,) if revision == 1 else (1, 2)
        launch_args = {"executable": sys.executable, "args": list(argv), "cwd": str(tmp_path)}
        first = ACPLocalLifecycle(gate(), workspace=str(tmp_path), ledger_path=ledger,
                                 local_session_id="local", provider="fixture", supported_versions=versions)
        try:
            opened = await first.start(executable=sys.executable, argv=argv, cwd=str(tmp_path),
                launch_request=request("launch1", "launch", launch_args),
                session_request=request("open", "session", {"cwd": str(tmp_path)}))
            assert opened.operation.state == "SUCCEEDED"
            adapter = first.adapter
            assert adapter.protocol_version == revision
            model_req = request("model", "config", {"session_id":"persisted", "config_id":"model", "value":"large"})
            assert (await first.set_model(model_req, model_id="large")).operation.state == "SUCCEEDED"
            toggle_req = request("toggle", "config", {"session_id":"persisted", "config_id":"toggle", "value":True})
            assert (await first.set_config_option(toggle_req, config_id="toggle", value=True)).operation.state == "SUCCEEDED"
            if revision == 1:
                mode_req = request("mode", "mode", {"session_id":"persisted", "mode_id":"review"})
                assert (await first.set_mode(mode_req, mode_id="review")).operation.state == "SUCCEEDED"
            work = request("prompt", "prompt", {"session_id":"persisted", "text":"private prompt"})
            result = await first.prompt(work, "private prompt", timeout=3)
            assert result.operation.state == "SUCCEEDED"
            if revision == 2:
                assert result.payload == {"messageId":"message-1", "completionConfirmed":False}
                assert adapter.state.foreground is None
            else:
                assert result.payload["_meta"] == {"accounting":"fixture"}
            updates = adapter.updates(timeout=3)
            for _ in range(4 if revision == 2 else 3):
                await anext(updates)
            assert adapter.state.usage["cost"]["amount"] == .02
            assert adapter.state.tool_calls["t"]["status"] == "completed"
            if revision == 2:
                assert adapter.state.tool_calls["t"]["rawInput"] is None
                assert adapter.state.foreground["state"] == "idle"
            else:
                assert adapter.state.tool_calls["t"]["rawInput"] == {"path":"a"}
            listed = await first.list_sessions(request("list", "list", {"cwd":str(tmp_path),"cursor":None}), cwd=str(tmp_path))
            assert listed.payload["nextCursor"] == "page2"
            assert (await first.close_session(request("close", "close", {"session_id":"persisted"}))).operation.state == "SUCCEEDED"
        finally:
            await first.close()
        reopened = ACPLocalLifecycle(gate(), workspace=str(tmp_path), ledger_path=ledger,
                                     local_session_id="local", provider="fixture", supported_versions=versions)
        try:
            resumed = await reopened.start(executable=sys.executable, argv=argv, cwd=str(tmp_path), reattach=True,
                launch_request=request("launch2", "launch", launch_args),
                session_request=request("resume", "resume", {"session_id":"persisted", "cwd":str(tmp_path)}))
            assert resumed.operation.state == "SUCCEEDED"
            # Fresh in-process journal still cannot resend a persisted prompt.
            duplicate = await reopened.adapter.prompt(work, "private prompt")
            assert duplicate.operation.state == "FAILED"
            deleted = await reopened.delete_session(request("delete", "delete", {"session_id":"persisted"}), session_id="persisted")
            assert deleted.operation.state == "SUCCEEDED"
            assert not remote.exists()
            binding = reopened.session_store.get("local", provider="fixture", request=work)
            assert binding.state == "DELETED"
            assert (await reopened.adapter.reattach(request("again", "resume", {"session_id":"persisted", "cwd":str(tmp_path)}))).operation.state == "FAILED"
        finally:
            await reopened.close()
        methods = [json.loads(line)["method"] for line in trace.read_text().splitlines()]
        assert methods.count("session/new") == 1
        assert methods.count("session/prompt") == 1
        assert methods.count("session/resume") == 1
        assert b"private prompt" not in Path(ledger).read_bytes()
    asyncio.run(case())


class ProtocolDouble:
    """Explicit unit-only protocol double; no provider runtime claim."""
    def __init__(self, initialization=None, response=None):
        self.initialization = initialization or {"protocolVersion":1}
        self.response = response or {"sessionId":"s"}
        self.calls = []
        self.closed = False

    async def request(self, method, params, timeout):
        self.calls.append((method, params))
        return self.initialization if method == "initialize" else self.response

    async def notify(self, method, params):
        self.calls.append((method, params))

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("caps", [{}, {"resume":None}, {"resume":False}, {"resume":True}])
def test_v1_optional_capability_absent_null_boolean_denies_before_method(tmp_path, caps):
    async def case():
        transport = ProtocolDouble({"protocolVersion":1,"agentCapabilities":{"sessionCapabilities":caps}})
        adapter = ACPSessionAdapter(gate(), transport, workspace=str(tmp_path))
        outcome = await adapter.resume(request("resume", "resume", {"session_id":"s","cwd":str(tmp_path)}), session_id="s", cwd=str(tmp_path))
        assert outcome.operation.state == "FAILED"
        assert [m for m, _ in transport.calls] == ["initialize"]
    asyncio.run(case())


def test_policy_denial_wrong_scope_and_unsupported_revision_never_create(tmp_path):
    async def case():
        transport = ProtocolDouble()
        adapter = ACPSessionAdapter(gate(allow=False), transport, workspace=str(tmp_path))
        assert (await adapter.open(request("open", "session", {"cwd":str(tmp_path)}), cwd=str(tmp_path))).operation.state == "FAILED"
        assert not transport.calls
        transport = ProtocolDouble({"protocolVersion":2})
        adapter = ACPSessionAdapter(gate(), transport, workspace=str(tmp_path))
        assert (await adapter.open(request("wrong-version", "session", {"cwd":str(tmp_path)}), cwd=str(tmp_path))).operation.state == "UNCERTAIN"
        assert transport.closed
        assert [m for m, _ in transport.calls] == ["initialize"]
        adapter = ACPSessionAdapter(gate(), ProtocolDouble(), workspace=str(tmp_path))
        assert (await adapter.open(request("open-good", "session", {"cwd":str(tmp_path)}), cwd=str(tmp_path))).operation.state == "SUCCEEDED"
        bad = await adapter.prompt(request("cross-scope", "prompt", {"session_id":"s","text":"hi"}, principal="other"), "hi")
        assert bad.operation.state == "FAILED"
        assert len(adapter.transport.calls) == 2
    asyncio.run(case())


def test_v2_absent_session_surface_no_new_method(tmp_path):
    async def case():
        transport = ProtocolDouble({"protocolVersion":2,"info":{"name":"double","version":"1.0.0"},"capabilities":{}})
        adapter = ACPSessionAdapter(gate(), transport, workspace=str(tmp_path), supported_versions=(1,2))
        result = await adapter.open(request("open", "session", {"cwd":str(tmp_path)}), cwd=str(tmp_path))
        assert result.operation.state == "UNCERTAIN"
        assert [m for m, _ in transport.calls] == ["initialize"]
    asyncio.run(case())


def test_v2_load_not_enabled_by_unknown_capability_field(tmp_path):
    async def case():
        transport = ProtocolDouble({"protocolVersion":2,"info":{"name":"double","version":"1.0.0"},
                                    "capabilities":{"session":{"load":{},"set_model":{}}}})
        adapter = ACPSessionAdapter(gate(), transport, workspace=str(tmp_path), supported_versions=(2,))
        req = request("load", "load", {"session_id":"s", "cwd":str(tmp_path)})
        outcome = await adapter.resume(req, session_id="s", cwd=str(tmp_path), load_history=True)
        assert outcome.operation.state == "FAILED"
        assert not adapter.supports("session/load") and not adapter.supports("session/set_model")
        assert [m for m, _ in transport.calls] == ["initialize"]
    asyncio.run(case())


def test_v2_tool_partial_null_replace_chunks_and_v1_null_compatibility():
    state = ACPSessionState(2)
    state.apply({"sessionUpdate":"tool_call_update","toolCallId":"t","title":"A","name":"read",
                 "rawInput":{"a":1},"content":[{"type":"content","content":{"type":"text","text":"a"}}]})
    state.apply({"sessionUpdate":"tool_call_update","toolCallId":"t","status":"completed"})
    assert state.tool_calls["t"]["title"] == "A"
    state.apply({"sessionUpdate":"tool_call_update","toolCallId":"t","rawInput":None,"name":None})
    assert state.tool_calls["t"]["rawInput"] is None and state.tool_calls["t"]["name"] is None
    state.apply({"sessionUpdate":"tool_call_content_chunk","toolCallId":"t","content":{"type":"content","content":{"type":"text","text":"b"}}})
    assert len(state.tool_calls["t"]["content"]) == 2
    state.apply({"sessionUpdate":"tool_call_update","toolCallId":"t","content":[]})
    assert state.tool_calls["t"]["content"] == []
    state.apply({"sessionUpdate":"tool_call_update","toolCallId":"t","content":None})
    assert state.tool_calls["t"]["content"] is None
    state.apply({"sessionUpdate":"tool_call_content_chunk","toolCallId":"t","content":{"type":"content","content":{"type":"text","text":"c"}}})
    assert len(state.tool_calls["t"]["content"]) == 1
    older = ACPSessionState(1)
    older.apply({"sessionUpdate":"tool_call","toolCallId":"t","title":"A","rawInput":{"a":1}})
    older.apply({"sessionUpdate":"tool_call_update","toolCallId":"t","title":None,"rawInput":None})
    assert older.tool_calls["t"]["title"] == "A" and older.tool_calls["t"]["rawInput"] == {"a":1}
    with pytest.raises(ValueError, match="revision"):
        older.apply({"sessionUpdate":"state_update","state":"idle"})


def test_durable_inflight_new_receipt_blocks_replacement_and_scope_change(tmp_path):
    store = ACPSessionStore(str(tmp_path/"db.sqlite"), workspace=str(tmp_path))
    opening = request("new", "session", {"cwd":str(tmp_path)})
    store.reserve("local", "session/new", opening)
    recovered = ACPSessionStore(str(store.path), workspace=str(tmp_path))
    assert recovered.receipt(opening.operation_id) == "UNCERTAIN"
    with pytest.raises(EffectRejected):
        recovered.reserve("local", "session/new", request("replacement", "session", {"cwd":str(tmp_path)}))
    recovered.bind("bound", "fixture", "s", str(tmp_path), 1, opening)
    with pytest.raises(EffectRejected, match="scope"):
        recovered.get("bound", provider="fixture", request=request("other", "resume", {}, principal="other"))


def test_real_launch_trusted_hook_and_owned_process_cleanup(tmp_path):
    async def case():
        script = tmp_path / "wait.py"
        script.write_text("import time\ntime.sleep(60)\n", encoding="utf8")
        argv = ("-u", str(script))
        req = request("hook", "launch", {"executable":sys.executable,"args":list(argv),"cwd":str(tmp_path)})
        calls = []
        async def hook(effect):
            calls.append("physical")
            return await effect()
        transport = await ACPStdioTransport.launch(sys.executable, argv, cwd=str(tmp_path), gate=gate(), request=req, launch_hook=hook)
        assert calls == ["physical"]
        await transport.close()
        await transport.close()
        assert transport.process.returncode is not None
    asyncio.run(case())


def test_context_checkpoint_denies_spawn_and_records_uncertainty(tmp_path):
    from sentra_runtime.effect_boundary import current_effect_context
    class BoundaryDouble:
        def checkpoint(self):
            raise PermissionError("revoked fixture context")
        async def run_async(self, effect):
            return await effect()
    async def case():
        marker = tmp_path / "must-not-exist"
        args = ("-c", "from pathlib import Path; Path(r'" + str(marker) + "').touch()")
        token = current_effect_context.set(BoundaryDouble())
        try:
            with pytest.raises(ACPLaunchError):
                await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path), gate=gate(),
                    request=request("checkpoint", "launch", {"executable":sys.executable,"args":list(args),"cwd":str(tmp_path)}))
        finally:
            current_effect_context.reset(token)
        assert not marker.exists()
    asyncio.run(case())


def test_physical_context_after_reserve_wraps_actual_spawn_without_contextvar(tmp_path):
    async def case():
        events = []
        class BoundaryDouble:
            def checkpoint(self):
                events.append("checkpoint")
            async def run_async(self, effect):
                events.append("physical")
                return await effect()
        base_gate = gate()
        def physical_context(req):
            assert req.operation_id in base_gate.journal._by_operation
            events.append("reserved-context")
            return BoundaryDouble()
        base_gate.physical_context = physical_context
        args = ("-c", "import time; time.sleep(60)")
        req = request("durable-hook", "launch", {"executable":sys.executable,"args":list(args),"cwd":str(tmp_path)})
        transport = await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path), gate=base_gate, request=req)
        try:
            assert events[:3] == ["reserved-context", "physical", "checkpoint"]
            assert events.count("checkpoint") >= 2
        finally:
            await transport.close()
        assert (await base_gate.journal.get(req.operation_id)).state == "SUCCEEDED"
    asyncio.run(case())


def test_owned_agent_descendants_terminated_after_leader_exit(tmp_path):
    async def case():
        from sentra_interop.acp_process import spawn_owned
        marker = tmp_path / "descendant.pid"
        code = "import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); Path(sys.argv[1]).write_text(str(p.pid))"
        process, owner = await spawn_owned(sys.executable, ("-c", code, str(marker)),
                                           stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(process.wait(), 5)
            child_pid = int(marker.read_text())
        finally:
            await owner.close()
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, child_pid)
            if handle:
                try:
                    code = wintypes.DWORD()
                    assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                    assert code.value != 259
                finally:
                    kernel.CloseHandle(handle)
        else:
            proc = Path(f"/proc/{child_pid}/stat")
            if proc.exists():
                assert proc.read_text().split()[2] == "Z"
            else:
                with pytest.raises(ProcessLookupError):
                    os.kill(child_pid, 0)
    asyncio.run(case())


def test_real_central_authority_launch_session_and_prompt_use_existing_journal(tmp_path):
    """Real central admission + Python stdio fixture; no external AI provider."""
    from sentra_mcp.services.context import ContextBusService
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_mcp.services.durable import DurableRunService
    from sentra_interop.central import CentralInteropAdapter
    from sentra_runtime.effect_boundary import current_effect_context
    import sqlite3

    durable = DurableRunService(tmp_path / "central")
    control = ControlPlaneService(durable, ContextBusService(tmp_path / "central"))
    owner = "owner"
    caps = ("acp:launch", "acp:session", "acp:prompt", "acp:cancel")
    durable.create_run(owner, run_id="run", workspace=str(tmp_path))
    control.ensure_agent("run", owner, agent_id="tester", role="worker")
    control.create_work_item("run", owner, work_item_id="work", objective="ACP local acceptance",
                             assignee_agent_id="tester", required_capabilities=list(caps))
    control.transition_work_item("work", owner, "RUNNING")
    for cap in caps:
        control.authorization_grant(owner, principal_type="agent", principal_id="tester",
                                    capability=cap, scope_type="work_item", scope_id="work")
    center = CentralInteropAdapter(control=control, run_id="run", owner=owner,
        machine=Machine("machine", "agent", owner, tuple(Capability(c, c) for c in caps)))
    script = tmp_path / "fixture-central.py"
    script.write_text(AGENT, encoding="utf8")
    argv = ("-u", str(script), "1", str(tmp_path / "trace.jsonl"), str(tmp_path / "remote.txt"))
    constraints = {"acp:launch": {"executable_paths":[sys.executable], "cwd_roots":[str(tmp_path)],
        "argv_sha256":hashlib.sha256(json.dumps(list(argv), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}}
    async def case():
        central_gate = center.protocol_gate(constraints=constraints)
        assert current_effect_context.get() is None
        launch = request("real-central-launch", "launch", {"executable":sys.executable,"args":list(argv),"cwd":str(tmp_path)})
        transport = await ACPStdioTransport.launch(sys.executable, argv, cwd=str(tmp_path), gate=central_gate, request=launch)
        session_store = ACPSessionStore(str(tmp_path / "associations.sqlite"), workspace=str(tmp_path))
        adapter = ACPSessionAdapter(central_gate, transport, workspace=str(tmp_path),
                                   store=session_store, provider="fixture", local_session_id="bound")
        try:
            opened = await adapter.open(request("real-central-open", "session", {"cwd":str(tmp_path)}), cwd=str(tmp_path))
            assert opened.operation.state == "SUCCEEDED"
            prompted = await adapter.prompt(request("real-central-prompt", "prompt", {"session_id":"persisted","text":"hello"}), "hello")
            assert prompted.operation.state == "SUCCEEDED"
            cancelled = await adapter.cancel(request("real-central-cancel", "cancel", {"session_id":"persisted"}))
            assert cancelled.state == "UNCERTAIN"
            assert durable.operation_status(launch.operation_id, owner)["state"] == "SUCCEEDED"
            recovered = await central_gate.journal.get(prompted.operation.operation_id)
            assert recovered.state == "SUCCEEDED"
            assert recovered.evidence["payload"]["stopReason"] == "end_turn"
            with sqlite3.connect(str(session_store.path)) as db:
                assert db.execute("SELECT COUNT(*) FROM acp_session_bindings").fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM acp_session_effects").fetchone()[0] == 0
            # A fresh central gate recovers the launch, without creating a child.
            fresh = center.protocol_gate(constraints=constraints)
            with pytest.raises(ACPLaunchError, match="DUPLICATE"):
                await ACPStdioTransport.launch(sys.executable, argv, cwd=str(tmp_path), gate=fresh, request=launch)
        finally:
            await transport.close()
    try:
        asyncio.run(case())
    finally:
        durable.close()
