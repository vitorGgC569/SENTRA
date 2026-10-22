// Trusted host sidecar. Secrets arrive through the parent's private pipe, never argv.
import {WebSocketServer} from 'ws';
import {createServer} from 'node:http';
import {networkInterfaces} from 'node:os';
import {createInterface} from 'node:readline';
import {randomBytes} from 'node:crypto';
import nacl from 'tweetnacl';
import {primitives} from './primitives';
import {ServerSession} from './server-session';
import {isLocalIPv4,lanAddresses} from './lan-address';

const lines=createInterface({input:process.stdin,crlfDelay:Infinity})[Symbol.asyncIterator]();
const first=await lines.next();
if(!first.value||first.value.length>20000)throw Error('Configuration missing or too large');
const config=JSON.parse(first.value);
function brokerTarget(value:any){
 if(typeof value.broker!=='string'||!/^http:\/\/127\.0\.0\.1:\d+$/.test(value.broker)||
    !new URL(value.broker).port||typeof value.bearer!=='string'||!value.bearer||value.bearer.length>1024)
  throw Error('Authenticated loopback broker required');
 return {broker:value.broker,bearer:value.bearer,runtime_id:String(value.runtime_id||'initial')};
}
let target:ReturnType<typeof brokerTarget>|null=brokerTarget(config);
if(config.bind!=='auto'&&!isLocalIPv4(config.bind)||!Number.isInteger(config.port)||config.port<1||config.port>65535)
 throw Error('Explicit private IPv4 bind or auto LAN required');
const choices=lanAddresses(networkInterfaces(),config.bind);
const bind=config.bind==='auto'?choices.find(v=>!v.virtual)?.address:config.bind;
if(!bind)throw Error('No physical LAN IPv4 found; select a local address explicitly');
const p=primitives(n=>new Uint8Array(randomBytes(n)));
const secret=p.decodeBase64(config.secret_key);
if(secret.length!==32)throw Error('Stable host key required');
const keys=nacl.box.keyPair.fromSecretKey(secret),publicKey=p.encodeBase64(keys.publicKey);
const endpoint=`ws://${bind}:${config.port}/sentra/mobile/v1`;
const http=createServer((req,res)=>{
 if(req.method!=='GET'||req.url!=='/sentra/mobile/health'){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');
 res.end(JSON.stringify({ok:true,protocol_version:1,public_key:publicKey,endpoint,broker_available:target!==null}));
});
const server=new WebSocketServer({server:http,path:'/sentra/mobile/v1',maxPayload:400000,perMessageDeflate:false});
http.listen(config.port,bind,()=>process.stdout.write(JSON.stringify({ready:true,public_key:publicKey,
 endpoint,bind,addresses:lanAddresses(networkInterfaces(),bind),protocol_version:1,pid:process.pid})+'\n'));
// A broker update changes future requests only. Lost effects are never retried.
void(async()=>{try{for await(const line of { [Symbol.asyncIterator]:()=>lines }){
 if(line.length>20000)throw Error('Control frame too large');
 const update=JSON.parse(line);
 if(update.type!=='broker_update')throw Error('Unsupported gateway control');
 target=update.available===false?null:brokerTarget(update);
 process.stdout.write(JSON.stringify({broker_updated:true,runtime_id:target?.runtime_id||null})+'\n');
 }}catch{target=null;}finally{if(config.supervised===true){target=null;
  for(const socket of server.clients)socket.terminate();server.close();http.close();
 }}})();
server.on('connection',(socket,request)=>{
 const remote=request.socket.remoteAddress?.replace(/^::ffff:/,'')||'';
 if(server.clients.size>16||request.headers.origin||!isLocalIPv4(remote)){socket.close(1008);return;}
 let session:ServerSession|null=null,queue=Promise.resolve(),count=0,queued=0;
 const budget=setInterval(()=>count=0,1000),expiry=setTimeout(()=>socket.close(1000),30*60*1000);
 const helloTimer=setTimeout(()=>{if(!session)socket.close(1008)},5000);
 socket.on('close',()=>{clearTimeout(helloTimer);clearTimeout(expiry);clearInterval(budget)});
 socket.on('message',data=>{
 if(++queued>4||++count>30||socket.bufferedAmount>1024*1024){socket.close(1008);return;}
 queue=queue.then(async()=>{
 if(socket.readyState!==socket.OPEN)return;
 try{
  if(!session){session=new ServerSession(JSON.parse(String(data)),keys.secretKey,keys.publicKey,p);
   socket.send(JSON.stringify(session.ready));clearTimeout(helloTimer);return;}
  const plain=session.open(String(data));if(plain===null)throw Error('Replay or invalid frame');
  const body=JSON.parse(plain);if(typeof body.id!=='string'||body.id.length>128)throw Error('Invalid request');
  let result;const destination=target;
  try{
   if(!destination)throw Error('Broker restarting');
   const response=await fetch(destination.broker+'/api/mobile/rpc',{method:'POST',redirect:'error',
    headers:{Authorization:'Bearer '+destination.bearer,'Content-Type':'application/json'},
    body:JSON.stringify({...body,public_key:session.peer}),signal:AbortSignal.timeout(14000)});
   const value=await response.json() as any;
   result=response.ok?{id:body.id,ok:true,value:value.value}:{id:body.id,ok:false,error:'Pedido recusado pelo SENTRA'};
  }catch{result={id:body.id,ok:false,error:'Resultado não confirmado. Consulte antes de repetir.'};}
  if(socket.readyState===socket.OPEN){let json=JSON.stringify(result);
   if(Buffer.byteLength(json)>4*1024*1024)json=JSON.stringify({id:body.id,ok:false,error:'Resultado excede o limite mobile; consulte no desktop.'});
   socket.send(session.seal(json));}
 }catch{socket.close(1008);}
 }).finally(()=>{queued--});
 });
});
