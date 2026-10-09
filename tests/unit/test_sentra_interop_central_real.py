"""Three real SENTRA ControlPlane/SQLite integration admission tests.

They explicitly prove NO remote effects are dispatched because today's
DurableRunService lacks the full-intent/fence contract. Test-owned loopback
fixtures demonstrate network connectivity, not an authorized SENTRA run.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import sys
import shutil
from pathlib import Path

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_runtime.contracts import Capability,Machine,OperationRequest,PolicyDecision
from sentra_runtime.durable_admission import DurableAdmissionUnavailable,DurableOperationGate
from sentra_runtime.executor import AuthorizationRequired
from sentra_interop.central import CentralInteropAdapter,BLOCKED_CODE
from sentra_interop.gate import InteropGate
from sentra_interop.acp_verified import ACPVerifiedResolver,canonical
from sentra_interop.a2a_loopback import A2ALoopbackServer,A2ALoopbackClient
from sentra_interop.a2a import AgentIdentity
from sentra_interop.a2a_sse import A2ASSELedger,A2ASSEServer,A2ASSEClient
from sentra_interop.activepieces_loopback import ActivepiecesLoopbackServer,ActivepiecesActionClient
from sentra_interop.mcp_sdk_compat import MCPTypescriptCompatClient
from sentra_interop.mcp_stdio import _minimal_windows_runtime_env, MCPStdioError
from test_sentra_interop_phase3_mcp_sdk import NODE_SOURCE


@pytest.fixture
def real_center(tmp_path):
    state=tmp_path/"sentra-real-sqlite"
    durable=DurableRunService(state)
    cp=ControlPlaneService(durable,ContextBusService(state))
    owner="sentra-owner"
    durable.create_run(owner,run_id="run-central",workspace=str(tmp_path))
    caps=("acp:resolve","acp:launch","a2a:ingest","a2a:read","a2a:cancel",
          "a2a:sse_publish","a2a:sse_read","mcp:echo","mcp:list",
          "openhands:start","activepieces:echo")
    cp.ensure_agent("run-central",owner,agent_id="trusted-agent",role="worker")
    cp.create_work_item("run-central",owner,work_item_id="WI-central",
                        objective="Real SENTRA interop admission",
                        assignee_agent_id="trusted-agent",required_capabilities=list(caps))
    cp.transition_work_item("WI-central",owner,"RUNNING")
    machine=Machine("interop-center", "central-real", owner,
                    tuple(Capability(c,c) for c in caps))
    adapter=CentralInteropAdapter(control=cp,run_id="run-central",
                                  owner=owner,machine=machine)
    def request(tag,cap,arguments,*,work="WI-central",principal="trusted-agent"):
        return OperationRequest("op-"+tag,principal,"interop-center",cap,work,
                                "idem-"+tag,arguments)
    def grant(cap,principal="trusted-agent"):
        return cp.authorization_grant(
            owner,principal_type="agent",principal_id=principal,
            capability=cap,scope_type="work_item",scope_id="WI-central")
    try:
        yield cp,durable,adapter,request,grant,tmp_path
    finally:
        durable.close()


def test_central_real_acp_catalog_selection_and_durable_launch_deny(real_center):
    cp,durable,center,req,grant,root=real_center
    assert center.durable_gate is None
    with pytest.raises(DurableAdmissionUnavailable):
        DurableOperationGate(durable,center.policy,machine=center.machine)
    key=b"externally-provisioned-test-root-at-least-32-bytes"
    install=root/"approved-cli"
    install.mkdir()
    executable=install/"cli-verified.bin"
    executable.write_bytes(b"approved fixture executable metadata, never launched")
    digest=hashlib.sha256(executable.read_bytes()).hexdigest()
    manifest={"schema":1,"publisher":"trusted-fixture","sequence":1,"agents":[{
        "provider":"fixture-acp","version":"1.0.0","executable":str(executable),
        "cwd":str(install),"argv":["--stdio"],"sha256":digest}]}
    signed=hmac.new(key,canonical(manifest),hashlib.sha256).hexdigest()
    registry=ACPVerifiedResolver(install_root=str(install),
        ledger_file=str(install/"catalog.sqlite"),
        publisher_keys={"trusted-fixture":key},revoked_publishers=frozenset(),
        gate=InteropGate(center.machine,center.decision))
    metadata_req=req("resolve","acp:resolve",{
        "provider":"fixture-acp","version":"1.0.0",
        "publisher":"trusted-fixture","sequence":1,
        "manifest_sha256":hashlib.sha256(canonical(manifest)).hexdigest(),
        "executable_sha256":digest})
    async def exercise():
        assert center.decision(metadata_req).allowed is False
        grant("acp:resolve")
        entry=await registry.resolve(manifest,signed,provider="fixture-acp",
                                     version="1.0.0",request=metadata_req)
        assert entry.executable==str(executable) and entry.sha256==digest
        operation=req("launch","acp:launch",{
            "executable":entry.executable,"args":list(entry.argv),
            "cwd":entry.cwd,"provider":"fixture-acp"})
        grant("acp:launch")
        result=await center.registry().submit(operation)
        assert result.state=="FAILED" and BLOCKED_CODE in result.error
        row=durable.operation_status(operation.operation_id,center.owner)
        assert row["state"]=="FAILED" and row["run_id"]=="run-central"
        assert (row["progress"] or {})["work_item_id"]=="WI-central"
        assert row["error"]["code"]==BLOCKED_CODE
        assert not any(p.name.endswith(".log") for p in install.iterdir())
        replay=await center.start(operation)
        assert replay.state=="FAILED"
        # A freshly constructed host adapter reads the SAME central SQLite
        # receipt, rather than an interop-owned side journal or remote replay.
        restarted=CentralInteropAdapter(control=cp,run_id="run-central",
                                        owner=center.owner,machine=center.machine)
        assert (await restarted.reconcile(operation.operation_id)).state=="FAILED"
        assert center.decision(metadata_req).allowed is True
    asyncio.run(exercise())


def test_central_real_a2a_http_sse_two_clients_revoke_and_no_effect(real_center):
    cp,durable,center,req,grant,root=real_center
    async def exercise():
        # Test-owned HTTP listeners, but real SENTRA authority decides every
        # SSE read and denied ingress action (no bypass into A2A task state).
        grants=[grant("a2a:sse_read")]
        who=AgentIdentity("trusted-agent","fixture-peer","laboratory")
        a2a=A2ALoopbackServer(
            InteropGate(center.machine,center.decision),
            mapper=__import__("sentra_interop.requests",fromlist=["InteropRequestMapper"]).InteropRequestMapper(
                "interop-center","trusted-agent","WI-central",str(root),
                frozenset({"a2a:ingest","a2a:read","a2a:cancel"})),
            identity=who,token=secrets.token_urlsafe(32))
        await a2a.start()
        correct=A2ALoopbackClient(port=a2a.port,token=a2a._token)
        wrong=A2ALoopbackClient(port=a2a.port,token="incorrect"*5)
        ledger=A2ASSELedger(InteropGate(center.machine,center.decision),
                            workspace_root=str(root),database=str(root/"sse-lab.sqlite"),
                            task_id="task-local",work_item_id="WI-central",
                            principal_id="trusted-agent")
        stream=await A2ASSEServer(ledger,token=secrets.token_urlsafe(32)).start()
        sse=A2ASSEClient(port=stream.port,token=stream._token,
                         principal_id="trusted-agent",work_item_id="WI-central",
                         task_id="task-local")
        foreign=A2ASSEClient(port=stream.port,token=stream._token,
                         principal_id="other-agent",work_item_id="WI-other",
                         task_id="task-local")
        try:
            assert (await correct.request("GET","/.well-known/agent-card.json"))[0]==200
            assert (await wrong.request("GET","/.well-known/agent-card.json"))[0]==401
            assert (await foreign.connect())[0]==403
            code,reader,writer=await sse.connect()
            assert code==200
            assert (await sse.next_event(reader))=={"heartbeat":True}
            # No event can be published by this adapter; even with grant.
            grant("a2a:ingest")
            outbound=req("a2a-dispatch","a2a:ingest",
                        {"task_id":"task-local","context_id":"WI-central"})
            outcome=await center.registry().submit(outbound)
            assert outcome.state=="FAILED" and BLOCKED_CODE in outcome.error
            assert ledger.latest()==0 and ledger.state()=="new"
            assert await a2a.boundary.state("task-local") is None
            # Revocation causes current SSE to terminate at its next
            # emission/heartbeat; a new stream is denied.
            cp.authorization_revoke(grants[0]["grant_id"],center.owner)
            assert await asyncio.wait_for(sse.next_event(reader),2) is None
            writer.close();await writer.wait_closed()
            code,_,writer=await sse.connect()
            assert code==403
            writer.close();await writer.wait_closed()
            assert durable.operation_status(outbound.operation_id,center.owner)["state"]=="FAILED"
        finally:
            await a2a.close()
            await stream.close()
    asyncio.run(exercise())


def test_central_real_mcp_openhands_activepieces_registered_but_no_fence_no_io(real_center):
    cp,durable,center,req,grant,root=real_center
    async def exercise():
        hits=[]
        async def lab_action(args):
            hits.append(args)
            return {"value":"should-not-run"}
        svc=await ActivepiecesLoopbackServer(
            InteropGate(center.machine,center.decision),principal_id="trusted-agent",
            workspace_id="WI-central",token=secrets.token_urlsafe(32),
            handlers={"echo":lab_action},allowlist={"echo":frozenset({"value"})},
        ).start()
        client=None
        try:
            # A real Node process is created by the TEST ONLY. It exercises
            # read-only MCP discovery with a current SENTRA SQLite grant.
            # The guarded ExecutorRegistry must NEVER dispatch tools/call.
            node=shutil.which("node")
            if node:
                script=root/"central_node_fixture.cjs"
                trace=root/"central_node_trace.jsonl"
                script.write_text(NODE_SOURCE,encoding="utf-8")
                process=await asyncio.create_subprocess_exec(
                    node,str(script),str(trace),cwd=str(root),
                    env=_minimal_windows_runtime_env(),
                    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
                client=MCPTypescriptCompatClient(process,InteropGate(
                    center.machine,center.decision),server_id="node")
                grant("mcp:list")
                await client.initialize()
                listed=await client.list_tools(req("node-discover","mcp:list",
                                                   {"server_id":"node"}))
                assert "echo" in listed

            # Registry, capabilities and grants are all the REAL SENTRA types.
            for cap in ("mcp:echo","openhands:start","activepieces:echo"):
                grant(cap)
            registry=center.registry()
            assert {c.capability_id for c in registry.get_machine("interop-center").capabilities} >= {
                "mcp:echo","openhands:start","activepieces:echo"}
            for label,cap,args in (
                ("mcp","mcp:echo",{"server_id":"mcp-local","tool_name":"echo",
                                  "arguments":{"value":"hello"}}),
                ("oh","openhands:start",{"conversation_id":"WI-central"}),
                ("active","activepieces:echo",{"action":"echo",
                                             "arguments":{"value":"hello"}}),
            ):
                operation=req(label,cap,args)
                result=await registry.submit(operation)
                assert result.state=="FAILED" and result.error==BLOCKED_CODE
                record=durable.operation_status(operation.operation_id,center.owner)
                assert record["state"]=="FAILED" and record["error"]["code"]==BLOCKED_CODE
                assert (await registry.submit(operation)).state=="FAILED"  # in-process reconcile, no resend
            assert hits==[] and svc.counts=={}
            # Revoke a real durable grant; no new operation or HTTP action occurs.
            grants=cp.authorization.list_grants(center.owner)
            target=next(x for x in grants["items"] if x["capability"]=="activepieces:echo")
            cp.authorization_revoke(target["grant_id"],center.owner)
            with pytest.raises(AuthorizationRequired,match="revoked"):
                await registry.submit(req("active-after","activepieces:echo",
                                          {"action":"echo","arguments":{"value":"later"}}))
            assert hits==[]
            assert durable.operation_status("op-active",center.owner)["state"]=="FAILED"
            if client is not None:
                # Discovery is genuine Node stdio; no provider effect follows.
                observed=[json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
                assert any(e.get("method")=="tools/list" for e in observed)
                assert not any(e.get("method")=="tools/call" for e in observed)
                listing=next(x for x in cp.authorization.list_grants(center.owner)["items"]
                             if x["capability"]=="mcp:list")
                cp.authorization_revoke(listing["grant_id"],center.owner)
                with pytest.raises(MCPStdioError):
                    await client.list_tools(req("node-revoked","mcp:list",{"server_id":"node"}))
        finally:
            if client is not None:
                await client.close()
                assert client.process.returncode is not None
            await svc.close()
    asyncio.run(exercise())
