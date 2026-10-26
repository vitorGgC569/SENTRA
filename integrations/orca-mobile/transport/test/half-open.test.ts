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

test('a half-open transport disconnects without replaying uncertain effects',{timeout:5000},async t=>{
 const p=primitives(n=>new Uint8Array(randomBytes(n))),host=nacl.box.keyPair(),keys=p.generateKeyPair();
 const http=createServer(),wss=new WebSocketServer({server:http});let received=0,effects=0;
 wss.on('connection',ws=>{let session:ServerSession|null=null;
  ws.on('message',data=>{
   if(!session){session=new ServerSession(JSON.parse(String(data)),host.secretKey,host.publicKey,p);ws.send(JSON.stringify(session.ready));return;}
   const request=JSON.parse(session.open(String(data))!);received++;
   if(received===1)ws.send(session.seal(JSON.stringify({id:request.id,ok:true,value:{ready:true}})));
   else if(request.request?.action==='message_send')effects++;
  });
 });
 http.listen(0,'127.0.0.1');await once(http,'listening');
 const device:Device={device_id:'test-phone',credential:'credential',public_key:p.encodeBase64(host.publicKey),
  endpoint:`ws://127.0.0.1:${(http.address() as any).port}/sentra/mobile/v1`,
  keys:{publicKey:p.encodeBase64(keys.publicKey),secretKey:p.encodeBase64(keys.secretKey)},
  scope:{project_id:'p',space_id:'s',dot_id:'d',actions:['workspace_inventory','message_send']}};
 const states:string[]=[],client=new MobileClient(p,url=>new WebSocket(url) as any,state=>states.push(state));
 t.after(()=>{client.disconnect();for(const ws of wss.clients)ws.terminate();wss.close();http.close();});
 await client.resume(device);assert.equal(client.isPairedTo(device),true);
 const original=globalThis.setTimeout;
 globalThis.setTimeout=((fn:any,ms?:number,...args:any[])=>original(fn,ms===15000?250:ms,...args)) as typeof setTimeout;
 try{
  const replies=await Promise.allSettled([
   client.request({action:'message_send',request_key:'single-effect'}),
   client.request({action:'workspace_inventory'}),
  ]);
  assert.ok(replies.every(result=>result.status==='rejected'&&/não confirmado/.test(result.reason.message)));
  assert.equal(received,3);assert.equal(effects,1);
  assert.equal(client.isPairedTo(device),false);assert.equal(states.at(-1),'disconnected');
 }finally{globalThis.setTimeout=original;}
});
