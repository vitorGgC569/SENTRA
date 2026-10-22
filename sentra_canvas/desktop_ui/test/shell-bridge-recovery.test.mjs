import {test} from 'node:test';
import assert from 'node:assert/strict';

const values=new Map([['sentra_native_token','local-test-bearer']]);
globalThis.location={hash:''};
globalThis.sessionStorage={getItem:key=>values.get(key) || null,setItem:(key,value)=>values.set(key,value)};
globalThis.window={dispatchEvent:()=>{}};
globalThis.CustomEvent=class {constructor(type){this.type=type;}};
const {shellBridge,pendingShellMutations}=await import('../src/shell-bridge.js');

test('a confirmation timeout preserves the exact creation key for inspection',async()=>{
  const previous=globalThis.fetch;
  globalThis.fetch=async()=>{throw new DOMException('timeout','AbortError');};
  const request={action:'conversation_create',project_id:'project',space_id:'space',dot_id:'dot',request_key:'timeout-key'};
  try{
    await assert.rejects(shellBridge(request),error=>error.uncertain===true && error.requestKey==='timeout-key');
    assert.deepEqual(pendingShellMutations('project').find(row=>row.request_key==='timeout-key'),request);
  }finally{globalThis.fetch=previous;}
});

test('a success envelope without the intended conversation remains recoverable',async()=>{
  const previous=globalThis.fetch;
  globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({ok:true,value:{status:'uncertain',operation_id:'operation'}})});
  const request={action:'conversation_create',project_id:'project',space_id:'space',dot_id:'dot',request_key:'incomplete-key'};
  try{
    await assert.rejects(shellBridge(request),error=>error.uncertain===true);
    assert.deepEqual(pendingShellMutations('project').find(row=>row.request_key==='incomplete-key'),request);
  }finally{globalThis.fetch=previous;}
});

test('workspace inventory is a scoped read and never enters pending effects',async()=>{
 const previous=globalThis.fetch;let sent;
 globalThis.fetch=async(path,options)=>{sent={path,body:JSON.parse(options.body)};return {ok:true,status:200,json:async()=>({ok:true,value:{protocol_version:1,layout_scope:'owner-dot'}})}};
 try{
  const before=pendingShellMutations('project').length;
  const value=await shellBridge({action:'workspace_inventory',project_id:'project',space_id:'space',dot_id:'dot'});
  assert.equal(value.protocol_version,1);assert.equal(sent.path,'/api/shell/bridge');
  assert.equal(sent.body.request_key,undefined);assert.equal(pendingShellMutations('project').length,before);
 }finally{globalThis.fetch=previous;}
});
