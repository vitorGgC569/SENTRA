import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {once} from 'node:events';
import WebSocket from 'ws';
import {MobileClient,NATIVE_MOBILE_ORIGIN,type Device} from '../src/client';
import {primitives} from '../src/primitives';

test('real LAN gateway pins crypto identity and never replays effects on reconnect', {timeout:20000}, async t=>{
 const observed:any[]=[];
 const broker=createServer(async(req,res)=>{
  assert.equal(req.headers.authorization,'Bearer test-host-only');
  let raw='';for await(const data of req)raw+=data;
  const body=JSON.parse(raw);observed.push(body);
  res.setHeader('Content-Type','application/json');
  res.end(JSON.stringify({ok:true,value:{method:body.method,action:body.request?.action,accepted:true}}));
 });
 broker.listen(0,'127.0.0.1');await once(broker,'listening');
 t.after(()=>broker.close());
 const reservation=createServer();reservation.listen(0,'127.0.0.1');await once(reservation,'listening');
 const port=(reservation.address() as any).port;await new Promise<void>(resolve=>reservation.close(()=>resolve()));
 const bundled=process.env.SENTRA_GATEWAY_BUNDLE;
 const child=spawn(process.execPath,bundled?[bundled]:[fileURLToPath(new URL('../node_modules/tsx/dist/cli.mjs',import.meta.url)),fileURLToPath(new URL('../src/gateway.ts',import.meta.url))],{stdio:['pipe','pipe','pipe']});
 t.after(()=>child.kill());
 const ready=new Promise<any>((resolve,reject)=>{let buffer='';const timer=setTimeout(()=>reject(Error('gateway startup timeout')),5000);child.stdout.on('data',data=>{buffer+=data;if(buffer.includes('\n')){clearTimeout(timer);resolve(JSON.parse(buffer.split('\n')[0]))}});child.once('exit',()=>{clearTimeout(timer);reject(Error('gateway exited before readiness'))});});
 child.stdin.end(JSON.stringify({bind:'127.0.0.1',port,broker:'http://127.0.0.1:'+(broker.address() as any).port,bearer:'test-host-only',secret_key:randomBytes(32).toString('base64')}));
 const host=await ready,p=primitives(n=>new Uint8Array(randomBytes(n))),keys=p.generateKeyPair();
 const device:Device={device_id:'test-device',credential:'test-device-credential',endpoint:`ws://127.0.0.1:${port}/sentra/mobile/v1`,public_key:host.public_key,keys:{publicKey:p.encodeBase64(keys.publicKey),secretKey:p.encodeBase64(keys.secretKey)},scope:{project_id:'project',space_id:'space',dot_id:'dot',actions:['workspace_inventory','message_send']}};
 const client=new MobileClient(p,url=>new WebSocket(url,{origin:NATIVE_MOBILE_ORIGIN}) as any);t.after(()=>client.disconnect());
 await client.resume(device);
 await client.request({action:'message_send',request_key:'physical-intent-once',content:'test content'});
 await client.rpc({method:'request',public_key:'forged',request:{action:'workspace_inventory'}});
 assert.equal(observed.at(-1).public_key,device.keys.publicKey);
 client.disconnect();await client.resume(device);
 assert.equal(observed.filter(b=>b.request?.action==='message_send').length,1);
 assert.equal(observed.filter(b=>b.request?.action==='workspace_inventory').length,3);
 assert.ok(observed.every(b=>b.public_key===device.keys.publicKey));
 for(const origin of ['https://untrusted.example','null',`http://127.0.0.1:${port}`,'sentra-mobile://native.evil']){
  const browser=new WebSocket(device.endpoint,{origin});
  const [code]=await once(browser,'close');assert.equal(code,1008);
 }
});
