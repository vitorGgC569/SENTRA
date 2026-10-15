import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {inspectMessageRequest,confirmedMessageRequest} from '../src/shell-message-request-status.js';
const scope={project_id:'project',space_id:'space',conversation_id:'conversation'};
const original={action:'message_send',...scope,request_key:'original-request',content:'never resend',attachments:['private-ref']};
function confirmed(){return {status:'confirmed',confirmed:true,automatic_retry:false,request_key:original.request_key,
  message:{...scope,request_key:original.request_key,message_id:'canonical-message',role:'user',status:'queued'}};}

test('unknown delivery inspection sends only an exact read selector and never the original prompt',async()=>{
  const calls=[];
  const result=await inspectMessageRequest(async body=>{calls.push(body);return {status:'unverified',confirmed:false,automatic_retry:false};},
    original,{...scope,action:'message_send',content:'malicious extra'});
  assert.equal(result.confirmed,false);
  assert.deepEqual(calls,[{action:'message_request_status',...scope,request_key:original.request_key}]);
  assert.ok(!('content' in calls[0])&&!('attachments' in calls[0]));
});

test('only matching canonical scope key role and known message status can clear an uncertain draft',async()=>{
  const value=confirmed();
  assert.equal(confirmedMessageRequest(value,original,scope),true);
  assert.equal(await inspectMessageRequest(async()=>value,original,scope),value);
  for(const changed of [
    {...value,request_key:'other'},
    {...value,automatic_retry:true},
    {...value,message:{...value.message,conversation_id:'other'}},
    {...value,message:{...value.message,status:'uncertain'}},
    {...value,message:{...value.message,role:'assistant'}},
    {...value,message:{...value.message,request_key:'other'}},
  ]){
    assert.equal(confirmedMessageRequest(changed,original,scope),false);
    await assert.rejects(()=>inspectMessageRequest(async()=>changed,original,scope),/original/);
  }
});

test('mismatching local scope does not issue any transport call',async()=>{
  let calls=0;
  await assert.rejects(()=>inspectMessageRequest(async()=>{calls++;},original,{...scope,conversation_id:'other'}),/Escopo/);
  assert.equal(calls,0);
});

test('an uncertain stored message remains pending and cannot be confused with a confirmed result',async()=>{
  const value={...confirmed(),status:'uncertain',confirmed:false};
  assert.equal(confirmedMessageRequest(value,original,scope),false);
  assert.equal(await inspectMessageRequest(async()=>value,original,scope),value);
});

test('the production bridge classifies status inspection as read-only even though its transport is POST',async()=>{
  const calls=[],writes=[];
  const source=fs.readFileSync(new URL('../src/shell-bridge.js',import.meta.url),'utf8')
    .replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
  class ApiError extends Error{}
  const sandbox={ApiError,canvasMaintenanceActive:()=>false,confirmedConversation:()=>true,
    api:async(path,body,options)=>{calls.push({path,body,options});return {ok:true,value:{status:'unverified',confirmed:false,automatic_retry:false}};},
    sessionStorage:{getItem:()=>null,setItem:(...args)=>writes.push(args)},
    window:{dispatchEvent:()=>{}},CustomEvent:class{},crypto:{randomUUID:()=>assert.fail('A read must not create an idempotency key')},
  };
  vm.createContext(sandbox);vm.runInContext(source+'\nglobalThis.testBridge=shellBridge;',sandbox);
  await inspectMessageRequest(sandbox.testBridge,original,scope);
  assert.equal(calls.length,1);
  assert.equal(calls[0].body.action,'message_request_status');
  assert.equal(calls[0].options.readOnly,true);
  assert.deepEqual(writes,[]);
});
