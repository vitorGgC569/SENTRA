"""Independent Python MCP server over real JSON-RPC stdio; not actual ToolHive."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys

from sentra_runtime.contracts import Machine, Capability, OperationRequest, PolicyDecision
from sentra_interop import InteropGate, ToolHiveMCPBoundary, MCPToolGrant
from sentra_interop.mcp_stdio import MCPStdioClient, MCPStdioError

SERVER = r"""
import json,sys,time
trace_path=sys.argv[1]
def emit(msg): print(json.dumps(msg, separators=(',',':')),flush=True)
def trace(row):
 with open(trace_path,'a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
for raw in sys.stdin:
 msg=json.loads(raw)
 meth=msg.get('method')
 if meth=='initialize':
  emit({'jsonrpc':'2.0','id':msg['id'],'result':{'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1.0'}}})
  emit({'jsonrpc':'2.0','id':900,'method':'roots/list','params':{}})
 elif meth=='notifications/initialized': trace({'method':meth})
 elif meth=='tools/list':
  trace({'method':meth})
  emit({'jsonrpc':'2.0','id':msg['id'],'result':{'tools':[{'name':x} for x in ['echo','fail','slow']]}})
 elif meth=='tools/call':
  name=msg['params']['name']
  trace({'method':meth,'name':name})
  if name=='slow':time.sleep(.3)
  result=({'content':[{'type':'text','text':'backend error'}],'isError':True}
          if name=='fail' else {'content':[{'type':'text','text':msg['params']['arguments'].get('value','ok')}]})
  emit({'jsonrpc':'2.0','id':msg['id'],'result':result})
 elif meth=='notifications/cancelled':trace({'method':meth})
 elif 'id' in msg and 'error' in msg:
  trace({'denied_server_request':msg['id'],'code':msg['error'].get('code')})
"""


def test_mcp_local_stdio_real_list_call_policy_timeout_cleanup(tmp_path):
    async def case():
        script=tmp_path / "fixture_mcp_stdio.py"
        script.write_text(SERVER,encoding="utf-8")
        trace=tmp_path / "fixture_mcp_trace.jsonl"
        argv=("-u",str(script),str(trace))
        active=True
        machine=Machine("mcp-machine","agent","tester",tuple(
            Capability(name,name) for name in (
                "mcp:launch","mcp:list","mcp:echo","mcp:fail","mcp:slow")))
        def policy(req):
            if req.capability_id=="mcp:launch":
                return PolicyDecision(True,"pinned",{
                    "executable_paths":[sys.executable],
                    "cwd_roots":[str(tmp_path)],
                    "argv_sha256":hashlib.sha256(json.dumps(list(argv),
                        separators=(",",":"),ensure_ascii=False).encode()).hexdigest()})
            return PolicyDecision(active and req.work_item_id=="work-A","scope",
                                  {"work_item_ids":["work-A"],"principal_ids":["tester"]})
        gate=InteropGate(machine,policy)
        def req(n,cap,args,work="work-A"):
            return OperationRequest("mcp-s3-"+n,"tester","mcp-machine",cap,work,
                                    "mcp-k-"+n,args)
        launch=req("launch","mcp:launch",{"executable":sys.executable,
                    "args":list(argv),"cwd":str(tmp_path),"server_id":"fixture"})
        client=await MCPStdioClient.launch(
            executable=sys.executable,argv=argv,cwd=str(tmp_path),
            server_id="fixture",request=launch,gate=gate)
        try:
            await client.initialize()
            try:
                await client.call_tool("echo", {"value":"unauthorized-direct"})
            except MCPStdioError:
                pass
            else:
                raise AssertionError("raw MCP client bypassed SENTRA grant")
            listed=await client.list_tools(req("list","mcp:list",{"server_id":"fixture"}))
            assert listed==("echo","fail","slow")
            grants=tuple(MCPToolGrant("fixture",t,"mcp:"+t) for t in listed)
            boundary=ToolHiveMCPBoundary(gate,{"fixture":client},grants)
            def job(n,name,value,work="work-A"):
                args={"value":value}
                return req(n,"mcp:"+name,{"server_id":"fixture",
                           "tool_name":name,"arguments":args},work),args
            item,args=job("one","echo","hello-over-stdio")
            good=await boundary.call(item,server_id="fixture",tool_name="echo",arguments=args)
            assert good.operation.state=="SUCCEEDED"
            assert good.payload["content"][0]["text"]=="hello-over-stdio"
            repeated=await boundary.call(item,server_id="fixture",tool_name="echo",arguments=args)
            assert repeated.duplicate and repeated.operation.state=="SUCCEEDED"
            denied_req,bad_args=job("outscope","echo","no",work="work-B")
            assert (await boundary.call(denied_req,server_id="fixture",
                    tool_name="echo",arguments=bad_args)).operation.state=="FAILED"
            bad_req,bad_args=job("notlisted","nonexistent","no")
            assert (await boundary.call(bad_req,server_id="fixture",
                    tool_name="nonexistent",arguments=bad_args)).operation.state=="FAILED"
            err,args=job("error","fail","fail")
            failed=await boundary.call(err,server_id="fixture",tool_name="fail",arguments=args)
            assert failed.operation.state=="FAILED"
            slow,args=job("slow","slow","later")
            uncertain=await boundary.call(slow,server_id="fixture",tool_name="slow",
                                          arguments=args,timeout=0.04)
            assert uncertain.operation.state=="UNCERTAIN"
            assert (await boundary.call(slow,server_id="fixture",
                    tool_name="slow",arguments=args)).duplicate
            # Stdio server may finish after client timeout, but no late
            # response can be confused with a newer tools/call ID.
            await asyncio.sleep(.4)
            nextop,args=job("aftertimeout","echo","survivor")
            assert (await boundary.call(nextop,server_id="fixture",
                    tool_name="echo",arguments=args)).operation.state=="SUCCEEDED"
            active=False
            revoked,args=job("revoked","echo","blocked")
            assert (await boundary.call(revoked,server_id="fixture",
                    tool_name="echo",arguments=args)).operation.state=="FAILED"
        finally:
            process=client.process
            await client.close()
            await client.close()
            assert process.returncode is not None and client._reader.done()
        logs=[json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines()]
        assert any(x.get("denied_server_request")==900 and x.get("code")==-32601 for x in logs)
        actual=[x["name"] for x in logs if x.get("method")=="tools/call"]
        assert actual.count("echo")==2 and actual.count("fail")==1 and actual.count("slow")==1
        assert "nonexistent" not in actual
        assert any(x.get("method")=="notifications/cancelled" for x in logs)
    asyncio.run(case())
