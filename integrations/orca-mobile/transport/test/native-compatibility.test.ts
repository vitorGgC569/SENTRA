import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {createServer} from 'node:http';
import {once} from 'node:events';
import WebSocket,{WebSocketServer} from 'ws';
import {MobileClient} from '../src/client';
import {primitives} from '../src/primitives';

function pendingConnection(){
 const p=primitives(n=>new Uint8Array(randomBytes(n)));
 const socket:any={send(){},close(){},onopen:null,onmessage:null,onclose:null,onerror:null};
 const client=new MobileClient(p,()=>socket);
 const ready=client.connect('ws://127.0.0.1:5197/sentra/mobile/v1',p.encodeBase64(p.generateKeyPair().publicKey));
 return {client,socket,ready};
}

test('policy refusal before authentication suggests checking the desktop version and network',async()=>{
 const {client,socket,ready}=pendingConnection();
 socket.onclose({code:1008});
 await assert.rejects(ready,/computador pode estar desatualizado/);
 assert.equal(client.hasPairedSession,false);
});

test('ordinary disconnect does not diagnose an old desktop',async()=>{
 const {socket,ready}=pendingConnection();
 socket.onclose({code:1006});
 await assert.rejects(ready,error=>error instanceof Error&&/interrompida/.test(error.message)&&!/desatualizado/.test(error.message));
});

test('legacy Origin policy produces an actionable refusal over a real local WebSocket',async t=>{
 const server=createServer(),websockets=new WebSocketServer({server});
 server.listen(0,'127.0.0.1');await once(server,'listening');
 t.after(()=>{for(const socket of websockets.clients)socket.terminate();websockets.close();server.close()});
 let origin='';websockets.on('connection',(socket,request)=>{origin=String(request.headers.origin||'');if(origin)socket.close(1008)});
 const p=primitives(n=>new Uint8Array(randomBytes(n))),port=(server.address() as any).port;
 const client=new MobileClient(p,url=>new WebSocket(url,{headers:{Origin:'sentra-mobile://native'}}) as any);
 t.after(()=>client.disconnect());
 await assert.rejects(client.connect(`ws://127.0.0.1:${port}/sentra/mobile/v1`,p.encodeBase64(p.generateKeyPair().publicKey)),/computador pode estar desatualizado/);
 assert.equal(origin,'sentra-mobile://native');
});
