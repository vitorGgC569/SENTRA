"""E2E separate local stdio peer, OpenHands-shaped typed events; SDK not installed."""
import asyncio
import hashlib
import json
import sys
import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop.gate import InteropGate
from sentra_interop.openhands_local import OpenHandsLocalStream, OpenHandsLocalError

AGENT = r"""
import json,sys
session=sys.argv[1]
sentinel=sys.argv[2]
def say(x):
 print(json.dumps(dict({'version':1},**x),separators=(',',':')),flush=True)
say({'type':'hello','conversation_id':session})
for row in sys.stdin:
 req=json.loads(row)
 typ=req.get('type')
 if typ=='start':
  say({'type':'event','sequence':0,'event':{'id':'ev0','kind':'message','source':'agent','content':'hello'}})
  say({'type':'artifact','sequence':1,'artifact_id':'report','text':'safe artifact'})
  say({'type':'tool_request','id':'t1','name':'fs/write_file','path':sentinel})
 elif typ=='tool_denied':
  assert req['id']=='t1'
  say({'type':'event','sequence':2,'event':{'id':'ev1','kind':'observation','source':'environment','parent_id':'ev0'}})
 elif typ=='cancel':
  say({'type':'cancel_ack','conversation_id':session})
  say({'type':'done','conversation_id':session})
"""


def test_openhands_local_stream_launch_events_artifacts_cancel_attach_denials(tmp_path):
    async def check():
        granted=True
        script=tmp_path/"local_oh_peer.py"
        script.write_text(AGENT,encoding="utf-8")
        forbidden=tmp_path/"forbidden-created.txt"
        args=("-u",str(script),"conversation-1",str(forbidden))
        machine=Machine("oh-fixture","agent","alice",tuple(Capability(x,x) for x in
            ("openhands:launch","openhands:start","openhands:read","openhands:event",
             "openhands:artifact","openhands:cancel")))
        def auth(req):
            if req.capability_id=="openhands:launch":
                return PolicyDecision(True,"pinned",{
                    "executable_paths":[sys.executable],
                    "cwd_roots":[str(tmp_path)],
                    "argv_sha256":hashlib.sha256(json.dumps(list(args),
                        separators=(",",":"),ensure_ascii=False).encode()).hexdigest(),
                    "principal_ids":["alice"],"work_item_ids":["conversation-1"]})
            return PolicyDecision(granted and req.work_item_id=="conversation-1",
                                  "local grant",{
                                  "principal_ids":["alice"],"work_item_ids":["conversation-1"]})
        gate=InteropGate(machine,auth)
        def op(i,cap,arguments,*,work="conversation-1"):
            return OperationRequest("oh-s2-"+i,"alice","oh-fixture",cap,work,
                                    "oh-k-"+i,arguments)
        launch=op("launch","openhands:launch",{
            "executable":sys.executable,"args":list(args),"cwd":str(tmp_path),
            "conversation_id":"conversation-1"})
        session=await OpenHandsLocalStream.launch(gate=gate,request=launch,
            executable=sys.executable,argv=args,cwd=str(tmp_path),
            conversation_id="conversation-1")
        process=session.process
        try:
            start=await session.start(op("start","openhands:start",{
                "conversation_id":"conversation-1"}))
            assert start.operation.state=="SUCCEEDED"
            read=op("read","openhands:read",{"conversation_id":"conversation-1",
                                            "after_sequence":-1})
            for _ in range(70):
                events=await session.attach(read,after_sequence=-1)
                if len(events)==2:
                    break
                await asyncio.sleep(.02)
            assert [event["kind"] for event in events]==["message","observation"]
            assert all("content" not in event for event in events)
            assert [event["sequence"] for event in events]==[0,2]
            assert [event["event_id"] for event in await session.attach(
                op("reattach","openhands:read",{"conversation_id":"conversation-1",
                                               "after_sequence":0}),
                after_sequence=0)]==["ev1"]
            docs=await session.artifacts(read)
            assert docs[0]["artifact_id"]=="report" and docs[0]["text"]=="safe artifact"
            assert not forbidden.exists()
            with pytest.raises(OpenHandsLocalError):
                await session.attach(op("other","openhands:read",{
                    "conversation_id":"conversation-1","after_sequence":-1},work="foreign"),
                    after_sequence=-1)
            granted=False
            with pytest.raises(OpenHandsLocalError):
                await session.artifacts(read)
            assert (await session.cancel(op("denied","openhands:cancel",{
                "conversation_id":"conversation-1"}))).state=="FAILED"
            granted=True
            result=await session.cancel(op("cancel","openhands:cancel",{
                "conversation_id":"conversation-1"}),timeout=3)
            assert result.state=="CANCELLED"
            assert (await gate.journal.get("oh-s2-cancel")).state=="CANCELLED"
            assert not forbidden.exists()
        finally:
            await session.close()
            await session.close()
        assert process.returncode is not None and session._task.done()
    asyncio.run(check())
