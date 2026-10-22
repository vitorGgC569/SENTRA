import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import WebSocket from 'ws';
import {MobileClient,type Device} from '../src/client';
import {primitives} from '../src/primitives';
import {deviceAtAddress} from '../src/pairing-state';

test('same mobile login survives broker and LAN endpoint changes without replay', {timeout:25000},async t=>{
 const seen:{host:number;action:string}[]=[];
 const brokers=[0,1].map(host=>createServer(async(req,res)=>{
  assert.equal(req.headers.authorization,'Bearer host-'+host);
  let raw='';for await(const chunk of req)raw+=chunk;
  const body=JSON.parse(raw);seen.push({host,action:body.request.action});
  if(body.request.action==='message_send'){res.destroy();return;}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({ok:true,value:{host,accepted:true}}));
 }));
 for(const server of brokers){server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(()=>{server.closeAllConnections();server.close()});}
 const target=(host:number)=>({broker:'http://127.0.0.1:'+(brokers[host].address() as any).port,bearer:'host-'+host,runtime_id:'runtime-'+host});
 const secret=randomBytes(32).toString('base64');
 async function gateway(key=secret){
  const reserve=createServer();reserve.listen(0,'127.0.0.1');await once(reserve,'listening');
  const port=(reserve.address() as any).port;await new Promise<void>(resolve=>reserve.close(()=>resolve()));
  const child=spawn(process.execPath,[fileURLToPath(new URL('../node_modules/tsx/dist/cli.mjs',import.meta.url)),
   fileURLToPath(new URL('../src/gateway.ts',import.meta.url))],{stdio:['pipe','pipe','pipe'],windowsHide:true});
  t.after(()=>child.kill());
  const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
  child.stdin.write(JSON.stringify({bind:'127.0.0.1',port,...target(0),secret_key:key})+'\n');
  const ready=JSON.parse((await lines.next()).value!);assert.equal(ready.ready,true);
  return {child,lines,ready};
 }
 const first=await gateway(),p=primitives(n=>new Uint8Array(randomBytes(n))),keys=p.generateKeyPair();
 const device:Device={device_id:'original-phone',credential:'original-scoped-credential',public_key:first.ready.public_key,
  endpoint:first.ready.endpoint,keys:{publicKey:p.encodeBase64(keys.publicKey),secretKey:p.encodeBase64(keys.secretKey)},
  scope:{project_id:'p',space_id:'s',dot_id:'d',actions:['workspace_inventory','message_send']}};
 const sockets:WebSocket[]=[];
 const client=new MobileClient(p,url=>{const socket=new WebSocket(url);sockets.push(socket);return socket as any});t.after(()=>client.disconnect());
 await client.resume(device);
 const retired={message:sockets[0].onmessage,error:sockets[0].onerror,close:sockets[0].onclose};
 await assert.rejects(client.request({action:'message_send',request_key:'only-intent'}),/não confirmado/);
 first.child.stdin.write(JSON.stringify({type:'broker_update',available:false})+'\n');
 assert.equal(JSON.parse((await first.lines.next()).value!).broker_updated,true);
 await assert.rejects(client.request({action:'workspace_inventory'}),/não confirmado/);
 first.child.stdin.write(JSON.stringify({type:'broker_update',available:true,...target(1)})+'\n');
 assert.equal(JSON.parse((await first.lines.next()).value!).runtime_id,'runtime-1');
 assert.equal((await client.request({action:'workspace_inventory'})).host,1);
 assert.equal(seen.filter(v=>v.action==='message_send').length,1);
 client.disconnect();first.child.kill();await once(first.child,'exit');
 const second=await gateway();assert.equal(second.ready.public_key,device.public_key);
 await client.resume(deviceAtAddress(device,second.ready.endpoint));
 retired.message?.call(sockets[0],{data:'invalid stale frame'} as any);
 retired.error?.call(sockets[0],{} as any);retired.close?.call(sockets[0],{} as any);
 assert.equal((await client.request({action:'workspace_inventory'})).accepted,true);
 assert.equal(seen.filter(v=>v.action==='message_send').length,1);
 const stranger=await gateway(randomBytes(32).toString('base64'));
 const count=seen.length;
 await assert.rejects(client.resume(deviceAtAddress(device,stranger.ready.endpoint)),/Identidade/);
 assert.equal(seen.length,count);
 await assert.rejects(client.request({action:'workspace_inventory'}),/não pareado/);
});
