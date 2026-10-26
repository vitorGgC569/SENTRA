import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {randomBytes} from 'node:crypto';
import WebSocket,{WebSocketServer} from 'ws';
import nacl from 'tweetnacl';
import {ServerSession} from '../src/server-session';
import {MobileClient,type Device} from '../src/client';
import {primitives} from '../src/primitives';

test('rotation fences new calls and late old failures without hiding later revocation',{timeout:8000},async t=>{
 const p=primitives(n=>new Uint8Array(randomBytes(n))),host=nacl.box.keyPair(),keys=p.generateKeyPair();
 const http=createServer(),wss=new WebSocketServer({server:http});let token='old',revoked=false,effects=0,reads=0,rotations=0;
 let releaseOld!:()=>void,seenOld!:()=>void;
 const oldSeen=new Promise<void>(resolve=>seenOld=resolve);
 wss.on('connection',ws=>{let session:ServerSession|null=null;
  ws.on('message',data=>{
   if(!session){session=new ServerSession(JSON.parse(String(data)),host.secretKey,host.publicKey,p);ws.send(JSON.stringify(session.ready));return;}
   const msg=JSON.parse(session.open(String(data))!);
   const reply=(response:object)=>ws.send(session!.seal(JSON.stringify({id:msg.id,...response})));
   if(msg.method==='rotate'){rotations++;token='new';reply({ok:true,value:{credential:token}});return;}
   if(msg.request?.action==='message_send'){
    effects++;releaseOld=()=>reply({ok:false,status:403,code:'MOBILE_DEVICE_AUTH_INVALID',error:'stale credential'});seenOld();return;
   }
   reads++;
   if(revoked||msg.credential!==token)reply({ok:false,status:403,code:'MOBILE_DEVICE_AUTH_INVALID',error:'invalid credential'});
   else reply({ok:true,value:{ok:true}});
  });
 });
 http.listen(0,'127.0.0.1');await once(http,'listening');
 const states:string[]=[],client=new MobileClient(p,url=>new WebSocket(url) as any,state=>states.push(state));
 t.after(()=>{client.disconnect();for(const ws of wss.clients)ws.terminate();wss.close();http.close();});
 const device:Device={device_id:'phone',credential:'old',public_key:p.encodeBase64(host.publicKey),
  endpoint:`ws://127.0.0.1:${(http.address() as any).port}/sentra/mobile/v1`,
  keys:{publicKey:p.encodeBase64(keys.publicKey),secretKey:p.encodeBase64(keys.secretKey)},
  scope:{project_id:'p',space_id:'s',dot_id:'d',actions:['workspace_inventory','message_send']}};
 await client.resume(device);
 const oldOutcome=client.request({action:'message_send',request_key:'one-effect'}).then(()=>null,error=>error);await oldSeen;
 let writing!:()=>void,releaseWrite!:()=>void,writes=0,saved:Device|undefined;
 const writeStarted=new Promise<void>(resolve=>writing=resolve),writeGate=new Promise<void>(resolve=>releaseWrite=resolve);
 const rotation=client.rotateCredential(async next=>{saved=next;if(++writes===2){writing();await writeGate;}});
 await writeStarted;assert.equal(saved?.credential,'new');
 await assert.rejects(client.request({action:'workspace_inventory'}),/Rotação de credencial/);
 await assert.rejects(client.request({action:'message_send',request_key:'no-second-effect'}),/Rotação de credencial/);
 assert.equal(reads,1);assert.equal(effects,1);assert.equal(rotations,1);
 releaseOld();assert.equal((await oldOutcome).status,403);
 assert.notEqual(states.at(-1),'reauth_required');
 releaseWrite();const updated=await rotation;assert.equal(client.isPairedTo(updated),true);
 assert.deepEqual(await client.request({action:'workspace_inventory'}),{ok:true});
 revoked=true;
 await assert.rejects(client.request({action:'workspace_inventory'}),(error:any)=>error.code==='MOBILE_DEVICE_AUTH_INVALID');
 assert.equal(client.isPairedTo(updated),false);assert.equal(states.at(-1),'reauth_required');assert.equal(effects,1);
});
