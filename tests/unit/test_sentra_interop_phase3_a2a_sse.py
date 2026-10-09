"""Authenticated SSE real TCP fixture, SQLite replay, Last-Event-ID and revocation."""
import asyncio
import secrets

import pytest
from sentra_runtime.contracts import Capability,Machine,OperationRequest,PolicyDecision
from sentra_interop.gate import InteropGate
from sentra_interop.a2a_sse import (
    A2ASSELedger,A2ASSEServer,A2ASSEClient,A2ASSEDenied,MAX_REPLAY,
)


def fixture(tmp_path):
    rights={"active":True}
    machine=Machine("sse-fixture","agent","alice",(
        Capability("a2a:sse_read","read"),Capability("a2a:sse_publish","publish")))
    def policy(req):
        return PolicyDecision(rights["active"] and req.principal_id=="alice"
                              and req.work_item_id=="work-one",
                              "live",{"principal_ids":["alice"],"work_item_ids":["work-one"]})
    gate=InteropGate(machine,policy)
    database=str(tmp_path/"stream.sqlite")
    def ledger():
        return A2ASSELedger(gate,workspace_root=str(tmp_path),database=database,
                            task_id="task-1",work_item_id="work-one",principal_id="alice")
    def op(i,state,text,*,work="work-one"):
        return OperationRequest(f"sse-op-{i}","alice","sse-fixture",
                                "a2a:sse_publish",work,f"sse-key-{i}",
                                {"task_id":"task-1","state":state,"text":text})
    return rights,ledger,op


def test_a2a_http_sse_real_stream_resume_terminal_and_no_leak(tmp_path):
    async def scenario():
        rights, ledger_fn, op=fixture(tmp_path)
        ledger=ledger_fn()
        token=secrets.token_urlsafe(32)
        server=await A2ASSEServer(ledger,token=token).start()
        client=A2ASSEClient(port=server.port,token=token,principal_id="alice",
                            work_item_id="work-one",task_id="task-1")
        try:
            assert server._server.sockets[0].getsockname()[0]=="127.0.0.1"
            wrong=A2ASSEClient(port=server.port,token="incorrect"*5,
                                principal_id="alice",work_item_id="work-one",task_id="task-1")
            code,_,writer=await wrong.connect()
            assert code==401
            writer.close();await writer.wait_closed()
            outsider=A2ASSEClient(port=server.port,token=token,principal_id="alice",
                                   work_item_id="other-work",task_id="task-1")
            code,_,writer=await outsider.connect()
            assert code==403
            writer.close();await writer.wait_closed()

            first=op("1","submitted","started")
            outcome=await ledger.append(first,state="submitted",text="started")
            assert outcome.operation.state=="SUCCEEDED" and outcome.payload["sequence"]==1
            assert (await ledger.append(first,state="submitted",text="started")).duplicate
            code,reader,writer=await client.connect(last_event_id=0)
            assert code==200
            received=await client.next_event(reader)
            assert received=={"id":1,"state":"submitted","text":"started"}
            idle=await client.next_event(reader)
            assert idle=={"heartbeat":True}
            second=await ledger.append(op("2","working","progress"),
                                       state="working",text="progress")
            assert second.operation.state=="SUCCEEDED"
            update=await client.next_event(reader)
            assert update=={"id":2,"state":"working","text":"progress"}
            writer.close();await writer.wait_closed()
            # Independent SQLite connection and new HTTP client reproduce
            # Last-Event-ID replay without duplicating task effects.
            reloaded=ledger_fn()
            assert reloaded.latest()==2 and reloaded.state()=="working"
            code,reader,writer=await client.connect(last_event_id=1)
            assert code==200
            assert (await client.next_event(reader))["id"]==2
            writer.close();await writer.wait_closed()

            # Cancel is a persisted terminal task-status EVENT; HTTP SSE has no
            # command/cancel endpoint and cannot execute a tool.
            assert (await reloaded.append(op("3","canceled","cancel confirmed"),
                                          state="canceled",text="cancel confirmed")
                    ).operation.state=="SUCCEEDED"
            code,reader,writer=await client.connect(last_event_id=2)
            assert code==200
            done=await client.next_event(reader)
            assert done["id"]==3 and done["state"]=="canceled"
            assert await client.next_event(reader) is None
            writer.close();await writer.wait_closed()
            blocked=await reloaded.append(op("4","working","unauthorized"),
                                          state="working",text="unauthorized")
            assert blocked.operation.state=="UNCERTAIN"
            assert reloaded.latest()==3
        finally:
            await server.close()
        with pytest.raises((OSError,ConnectionError)):
            await client.connect()
    asyncio.run(scenario())


def test_a2a_sse_replay_window_revocation_and_backpressure(tmp_path):
    async def scenario():
        rights, ledger_fn, op=fixture(tmp_path)
        ledger=ledger_fn()
        for i in range(MAX_REPLAY+1):
            state="submitted" if i==0 else "working"
            result=await ledger.append(op(str(i),state,f"safe-{i}"),
                                       state=state,text=f"safe-{i}")
            assert result.operation.state=="SUCCEEDED"
        with pytest.raises(A2ASSEDenied,match="replay window"):
            ledger.since(0)
        token=secrets.token_urlsafe(32)
        server=await A2ASSEServer(ledger,token=token).start()
        client=A2ASSEClient(port=server.port,token=token,principal_id="alice",
                            work_item_id="work-one",task_id="task-1")
        try:
            code,_,w=await client.connect(last_event_id=0)
            assert code==409
            w.close();await w.wait_closed()
            code,r,w=await client.connect(last_event_id=ledger.latest()-1)
            assert code==200
            assert (await client.next_event(r))["id"]==ledger.latest()
            rights["active"]=False
            assert await client.next_event(r) is None
            w.close();await w.wait_closed()
            code,_,w=await client.connect(last_event_id=ledger.latest())
            assert code==403
            w.close();await w.wait_closed()
            forbidden=await ledger.append(op("unauth","working","blocked"),
                                          state="working",text="blocked")
            assert forbidden.operation.state=="FAILED"
            assert ledger.latest()==MAX_REPLAY+1
        finally:
            await server.close()
    asyncio.run(scenario())


def test_a2a_sse_slow_consumer_write_buffer_is_bounded(tmp_path):
    rights, ledger_fn, _=fixture(tmp_path)
    ledger=ledger_fn()
    server=A2ASSEServer(ledger,token=secrets.token_urlsafe(32))
    class FakeTransport:
        def get_write_buffer_size(self):
            return 100000000
    class FakeWriter:
        transport=FakeTransport()
        def write(self,_):
            raise AssertionError("oversized buffer unexpectedly written")
        async def drain(self):
            raise AssertionError("backpressure bypass")
    with pytest.raises(A2ASSEDenied,match="slow consumer"):
        asyncio.run(server._drain(FakeWriter(),b"secret"))
