/** Driven by the Python acceptance fixture; never uses installed account state. */
import {createInterface} from 'node:readline';
import {randomBytes} from 'node:crypto';
import WebSocket from 'ws';
import {MobileClient} from '../src/client';
import {primitives} from '../src/primitives';
const lines=createInterface({input:process.stdin})[Symbol.asyncIterator]();
const config=JSON.parse((await lines.next()).value!);
const client=new MobileClient(primitives(n=>new Uint8Array(randomBytes(n))),url=>new WebSocket(url) as any);
try{
 const pending=await client.pair(config.offer,'Acceptance phone');
 process.stdout.write(JSON.stringify({phase:'pending',device_id:pending.device_id})+'\n');
 if((await lines.next()).value!=='approved')throw Error('owner did not approve');
 const device=await client.claim(pending);if(!device)throw Error('device not approved');
 const inventory=await client.request({action:'workspace_inventory'}),conversations=await client.request({action:'conversation_list'});
 process.stdout.write(JSON.stringify({phase:'scoped',protocol:inventory.value.protocol_version,conversations:conversations.value.items.map((c:any)=>c.conversation_id)})+'\n');
 if(config.rotate){
  let saved=device,writes=0,lost=false;
  try{await client.rotateCredential(async next=>{if(++writes===2)throw Error('simulated protected-store interruption');saved=next})}catch{lost=true}
  if(!saved.rotation_key||!lost)throw Error('rotation recovery was not exercised');
  client.disconnect();const recovered=await client.resume(saved,async next=>{saved=next});
  let oldRefused=false;try{await client.rpc({method:'request',device_id:device.device_id,credential:device.credential,request:{action:'workspace_inventory',...device.scope}})}catch{oldRefused=true}
  if(!oldRefused||saved.rotation_key||recovered.public_key!==device.public_key)throw Error('rotation identity/revocation contract failed');
  process.stdout.write(JSON.stringify({phase:'rotated',recovered:true,old_refused:oldRefused})+'\n');
 }
 if(config.restart){
  if((await lines.next()).value!=='restart')throw Error('broker restart gate missing');
  const recovered=await client.request({action:'workspace_inventory'});
  const continued=await client.request({action:'conversation_list'});
  process.stdout.write(JSON.stringify({phase:'restarted',protocol:recovered.value.protocol_version,
   conversations:continued.value.items.map((c:any)=>c.conversation_id)})+'\n');
 }
 if((await lines.next()).value!=='revoked')throw Error('owner did not revoke');
 let refused=false;try{await client.request({action:'workspace_inventory'})}catch{refused=true}
 process.stdout.write(JSON.stringify({phase:'revoked',refused})+'\n');
 if(!refused)process.exitCode=1;
}finally{client.disconnect();process.stdin.destroy()}
