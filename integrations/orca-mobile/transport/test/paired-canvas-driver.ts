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
 if(config.disconnect_before_claim)client.disconnect();
 if((await lines.next()).value!=='approved')throw Error('owner did not approve');
 let acknowledgedCredential:string|undefined;
 if(config.lose_claim_response){
  const rpc=client.rpc.bind(client);let dropped=false;
  client.rpc=async body=>{const result=await rpc(body);if(body.method==='claim'&&!dropped){dropped=true;acknowledgedCredential=result.credential;throw Error('simulated lost claim response')}return result};
  let uncertain=false;try{await client.claim(pending)}catch{uncertain=true}
  if(!uncertain||!acknowledgedCredential)throw Error('lost claim receipt was not exercised');
  client.disconnect(); // The next claim is an explicit owner retry, never automatic replay.
 }
 const device=await client.claim(pending);if(!device)throw Error('device not approved');let currentDevice=device;
 if(config.lose_claim_response&&device.credential!==acknowledgedCredential)throw Error('claim recovery changed the credential');
 const inventory=await client.request({action:'workspace_inventory'}),conversations=await client.request({action:'conversation_list'});
 process.stdout.write(JSON.stringify({phase:'scoped',protocol:inventory.value.protocol_version,conversations:conversations.value.items.map((c:any)=>c.conversation_id)})+'\n');
 if(config.rotate){
  let saved=device,writes=0,lost=false;
  try{await client.rotateCredential(async next=>{if(++writes===2)throw Error('simulated protected-store interruption');saved=next})}catch{lost=true}
  if(!saved.rotation_key||!lost)throw Error('rotation recovery was not exercised');
  client.disconnect();const recovered=await client.resume(saved,async next=>{saved=next});
  let oldRefused=false;try{await client.rpc({method:'request',device_id:device.device_id,credential:device.credential,request:{action:'workspace_inventory',...device.scope}})}catch{oldRefused=true}
  if(!oldRefused||saved.rotation_key||recovered.public_key!==device.public_key||!client.isPairedTo(recovered))throw Error('rotation identity/revocation contract failed');
  currentDevice=recovered;
  process.stdout.write(JSON.stringify({phase:'rotated',recovered:true,old_refused:oldRefused})+'\n');
 }
 if(config.restart){
  if((await lines.next()).value!=='restart')throw Error('broker restart gate missing');
  const recovered=await client.request({action:'workspace_inventory'});
  const continued=await client.request({action:'conversation_list'});
  process.stdout.write(JSON.stringify({phase:'restarted',protocol:recovered.value.protocol_version,
   conversations:continued.value.items.map((c:any)=>c.conversation_id)})+'\n');
 }
 let scopeError:any;try{await client.request({action:'document_list'})}catch(e){scopeError=e}
 if(scopeError?.status!==403||scopeError?.code||!client.isPairedTo(currentDevice))throw Error('scope denial must not invalidate the paired session');
 process.stdout.write(JSON.stringify({phase:'scope_denied',still_paired:true})+'\n');
 if((await lines.next()).value!=='revoked')throw Error('owner did not revoke');
 let authError:any;try{await client.request({action:'workspace_inventory'})}catch(e){authError=e}
 const refused=authError?.status===403&&authError?.code==='MOBILE_DEVICE_AUTH_INVALID'&&!client.isPairedTo(currentDevice);
 process.stdout.write(JSON.stringify({phase:'revoked',refused})+'\n');
 if(!refused)process.exitCode=1;
}finally{client.disconnect();process.stdin.destroy()}
