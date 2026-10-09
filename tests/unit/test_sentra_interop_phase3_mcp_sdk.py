"""Real Node.js MCP 2025-06-18 JSON-RPC stdio fixture; NOT npm SDK."""
import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop.gate import InteropGate
from sentra_interop.mcp_sdk_compat import MCPTypescriptCompatClient
from sentra_interop.mcp_stdio import MCPStdioError, _minimal_windows_runtime_env
from sentra_interop.mcp import ToolHiveMCPBoundary,MCPToolGrant

NODE_SOURCE=r"""
const fs=require('fs'), readline=require('readline');
const trace=process.argv[2];
function send(x){process.stdout.write(JSON.stringify({jsonrpc:'2.0',...x})+'\n')}
function log(x){fs.appendFileSync(trace,JSON.stringify(x)+'\n')}
readline.createInterface({input:process.stdin,crlfDelay:Infinity}).on('line',(raw)=>{
  let o;
  try {o=JSON.parse(raw)} catch {return}
  if(o.error && o.id===900){log({deny:o.error.code});return}
  if(!o.method)return;
  if(o.method==='initialize'){
    send({id:o.id,result:{protocolVersion:'2025-06-18',capabilities:{tools:{},resources:{},prompts:{}},serverInfo:{name:'local-node-fixture',version:'1'}}});
    send({id:900,method:'roots/list',params:{}})
    return;
  }
  if(o.method==='notifications/initialized')return;
  if(o.method==='notifications/cancelled'){log({cancel:true});return}
  log({method:o.method,name:o.params?.name,uri:o.params?.uri});
  if(o.method==='tools/list'){send({id:o.id,result:{tools:[{name:'echo'},{name:'bad'},{name:'rpc-error'}]}});return}
  if(o.method==='tools/call'){
    if(o.params.name==='rpc-error'){send({id:o.id,error:{code:-32001,message:'fixture failure'}});return}
    const error=o.params.name==='bad';
    send({id:o.id,result:error?{isError:true,content:[{type:'text',text:'denied'}]}:{content:[{type:'text',text:o.params.arguments.value}]}});
    return;
  }
  if(o.method==='resources/list'){send({id:o.id,result:{resources:[{uri:'sentra://fixture/help',name:'Help'}]}});return}
  if(o.method==='resources/read'){send({id:o.id,result:{contents:[{uri:o.params.uri,mimeType:'text/plain',text:'resource-safe'}]}});return}
  if(o.method==='prompts/list'){send({id:o.id,result:{prompts:[{name:'summarize'}]}});return}
  if(o.method==='prompts/get'){send({id:o.id,result:{messages:[{role:'user',content:{type:'text',text:'Summarize safely'}}]}});return}
  send({id:o.id,error:{code:-32601,message:'Method not found'}})
});
"""


def test_mcp_node_typescript_shape_stdio_readonly_e2e(tmp_path):
    node=shutil.which("node")
    if not node or not Path(node).is_file():
        pytest.skip("Node executable is not installed; do not install npm packages")
    async def scenario():
        script=tmp_path/"mcp_fixture_node.cjs"
        script.write_text(NODE_SOURCE,encoding="utf-8")
        checked=subprocess.run([node,"--check",str(script)],capture_output=True,text=True,env=_minimal_windows_runtime_env(),timeout=5)
        assert checked.returncode==0, checked.stderr
        trace=tmp_path/"mcp_node_trace.jsonl"
        argv=(str(script),str(trace))
        allowed=True
        caps=("mcp:launch","mcp:list","mcp:echo","mcp:bad","mcp:rpc-error",
              "mcp:resources_list","mcp:resource_read",
              "mcp:prompts_list","mcp:prompt_read")
        machine=Machine("mcp-node","agent","local-owner",tuple(Capability(x,x) for x in caps))
        digest=hashlib.sha256(json.dumps(list(argv),separators=(",",":")).encode()).hexdigest()
        def authorize(req):
            if req.capability_id=="mcp:launch":
                return PolicyDecision(allowed,"pinned",{
                    "executable_paths":[node],"cwd_roots":[str(tmp_path)],
                    "argv_sha256":digest,"principal_ids":["local-owner"],
                    "work_item_ids":["node-work"]})
            return PolicyDecision(allowed and req.principal_id=="local-owner"
                                  and req.work_item_id=="node-work","scope",{
                    "principal_ids":["local-owner"],"work_item_ids":["node-work"]})
        gate=InteropGate(machine,authorize)
        def op(label,cap,args,*,work="node-work"):
            return OperationRequest("node-"+label,"local-owner","mcp-node",cap,work,
                                    "node-key-"+label,args)
        launch=op("launch","mcp:launch",{"executable":node,"args":list(argv),
              "cwd":str(tmp_path),"server_id":"node"})
        transport=await MCPTypescriptCompatClient.launch(
            executable=node,argv=argv,cwd=str(tmp_path),
            server_id="node",request=launch,gate=gate)
        process=transport.process
        try:
            transport.configure_readonly(resources=frozenset({"sentra://fixture/help"}),
                                         prompts=frozenset({"summarize"}))
            await transport.initialize()
            assert await transport.list_tools(op("list","mcp:list",{"server_id":"node"}))==("echo","bad","rpc-error")
            bridge=ToolHiveMCPBoundary(gate,{"node":transport},tuple(
                MCPToolGrant("node",n,"mcp:"+n) for n in ("echo","bad","rpc-error")))
            args={"value":"typescript-shape"}
            call=op("call","mcp:echo",{"server_id":"node","tool_name":"echo","arguments":args})
            ok=await bridge.call(call,server_id="node",tool_name="echo",arguments=args)
            assert ok.operation.state=="SUCCEEDED"
            assert ok.payload["content"][0]["text"]=="typescript-shape"
            assert (await bridge.call(call,server_id="node",tool_name="echo",
                                      arguments=args)).duplicate
            bad=op("bad","mcp:bad",{"server_id":"node","tool_name":"bad","arguments":args})
            assert (await bridge.call(bad,server_id="node",tool_name="bad",
                                      arguments=args)).operation.state=="FAILED"
            rpc=op("rpc","mcp:rpc-error",{"server_id":"node",
                                         "tool_name":"rpc-error","arguments":args})
            uncertain=await bridge.call(rpc,server_id="node",tool_name="rpc-error",
                                        arguments=args)
            assert uncertain.operation.state=="UNCERTAIN"
            assert (await bridge.call(rpc,server_id="node",tool_name="rpc-error",
                                      arguments=args)).duplicate
            assert await transport.list_resources(op("lr","mcp:resources_list",
                                                       {"server_id":"node"}))==("sentra://fixture/help",)
            item=op("rr","mcp:resource_read",{"server_id":"node","uri":"sentra://fixture/help"})
            assert (await transport.read_resource(item,uri="sentra://fixture/help"))["text"]=="resource-safe"
            assert await transport.list_prompts(op("lp","mcp:prompts_list",
                                                     {"server_id":"node"}))==("summarize",)
            prompt=op("pr","mcp:prompt_read",{"server_id":"node","name":"summarize"})
            assert (await transport.get_prompt(prompt,name="summarize"))["text"]=="Summarize safely"
            with pytest.raises(MCPStdioError):
                await transport.read_resource(item,uri="file:///C:/sensitive")
            with pytest.raises(MCPStdioError):
                await transport.get_prompt(prompt,name="admin")
            with pytest.raises(MCPStdioError):
                await transport.read_resource(op("foreign","mcp:resource_read",
                     {"server_id":"node","uri":"sentra://fixture/help"},work="other"),
                     uri="sentra://fixture/help")
            with pytest.raises(MCPStdioError):
                await transport.call_tool("echo",args)
            allowed=False
            with pytest.raises(MCPStdioError):
                await transport.get_prompt(prompt,name="summarize")
        finally:
            await transport.close()
        assert process.returncode is not None
        logs=[json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines()]
        assert any(x.get("deny")==-32601 for x in logs)
        assert sum(x.get("method")=="tools/call" for x in logs)==3
        assert sum(x.get("method")=="resources/read" for x in logs)==1
        assert sum(x.get("method")=="prompts/get" for x in logs)==1
    asyncio.run(scenario())
