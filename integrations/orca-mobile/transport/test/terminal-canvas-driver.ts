/** Isolated encrypted acceptance client. An ACK is deliberately dropped once. */
import {createInterface} from 'node:readline';
import {randomBytes,createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import WebSocket from 'ws';
import {MobileClient,EffectJournal,canonicalIntent,journalIntent} from '../src/client';
import {primitives} from '../src/primitives';
const lines=createInterface({input:process.stdin})[Symbol.asyncIterator]();
const config=JSON.parse((await lines.next()).value!);let drop=false;
const p=primitives(n=>new Uint8Array(randomBytes(n)));
function socket(url:string){
 const wire=new WebSocket(url);
 const proxy:any={send:(value:string)=>wire.send(value),close:()=>wire.close(),onopen:null,onmessage:null,onclose:null,onerror:null};
 wire.on('open',()=>proxy.onopen?.({}));wire.on('close',()=>proxy.onclose?.({}));wire.on('error',()=>proxy.onerror?.({}));
 wire.on('message',data=>{if(drop){drop=false;wire.close();return}proxy.onmessage?.({data:String(data)})});return proxy;
}
let client=new MobileClient(p,socket),stored:string|null=null;
const journal=new EffectJournal({read:async()=>stored,write:async value=>{stored=value}});
const unwrap=(v:any)=>v?.ok===true?v.value:v;
const emit=(v:any)=>process.stdout.write(JSON.stringify(v)+'\n');
try{
 const pending=await client.pair(config.offer,'Terminal acceptance phone');assert.equal(client.hasPairedSession,false);
 emit({phase:'pending',device_id:pending.device_id});assert.equal((await lines.next()).value,'approved');
 const device=await client.claim(pending);assert.ok(device);assert.equal(client.hasPairedSession,true);
 const inventory=unwrap(await client.request({action:'dot_computer_get',conversation_id:config.conversation_id}));
 assert.equal(inventory.terminal_observation.protocol_version,1);
 assert.ok(inventory.terminals.some((t:any)=>t.id===config.terminal_id&&t.work_item_id===config.work_item_id));
 const request={action:'dot_computer_action',conversation_id:config.conversation_id,request_key:config.key,
  request:{action:'machine_execute',machine_id:config.machine_id,work_item_id:config.work_item_id,
   capability_id:'terminal:write',arguments:{terminal_id:config.terminal_id,data:config.command+'\r'}}};
 const fingerprint=createHash('sha256').update(canonicalIntent(journalIntent({...request,...device!.scope}))).digest('hex');
 await journal.begin({key:config.key,slot:'terminal:'+config.terminal_id,device_id:device!.device_id,action:request.action,
  conversation_id:config.conversation_id,fingerprint,created_at:Date.now()});
 drop=true;let uncertain=false;try{await client.request(request)}catch{uncertain=true}
 assert.equal(uncertain,true);assert.equal((await journal.list()).length,1);client.disconnect();
 emit({phase:'uncertain'});
 client=new MobileClient(p,socket);await client.resume(device!);
 const receipt=unwrap(await client.request({action:'workspace_request_status',selector:{action:request.action,
  request_key:config.key,fingerprint,conversation_id:config.conversation_id}}));
 assert.equal(receipt.resolved,true);assert.equal(receipt.receipt.source_state,'SUCCEEDED');await journal.finish(config.key);
 const read={action:'dot_computer_read',conversation_id:config.conversation_id,request:{action:'terminal_output',
  machine_id:config.machine_id,work_item_id:config.work_item_id,capability_id:'terminal:read',terminal_id:config.terminal_id,cursor:0}};
 const frame=unwrap(await client.request(read));assert.equal(frame.protocol_version,1);assert.equal(frame.terminal_id,config.terminal_id);
 const checkpoint=unwrap(await client.request({...read,request:{...read.request,action:'terminal_checkpoint',cursor:undefined}}));
 assert.equal(checkpoint.available,true);assert.equal(checkpoint.checkpoint.version,1);
 emit({phase:'recovered',resolved:true,pending:(await journal.list()).length,writes:1,checkpoint:true});
 assert.equal((await lines.next()).value,'revoked');let refused=false;try{await client.request(read)}catch{refused=true}
 assert.equal(refused,true);emit({phase:'revoked',refused});
}finally{client.disconnect();process.stdin.destroy()}
