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
