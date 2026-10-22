import {createRequire} from 'node:module';
import {createInterface} from 'node:readline';
import {readFileSync} from 'node:fs';
const {SnapshotEngine,ENGINE_VERSION}=createRequire(import.meta.url)('../dist/engine.cjs');
const engine=new SnapshotEngine();
const manifest=JSON.parse(readFileSync(new URL('../dist/manifest.json',import.meta.url),'utf8'));
process.stdout.write(JSON.stringify({ready:true,engine_version:ENGINE_VERSION,pid:process.pid,build_id:manifest.build_id})+'\n');
try{for await(const line of createInterface({input:process.stdin,crlfDelay:Infinity})){
 let request;try{
  if(Buffer.byteLength(line)>1024*1024)throw Error('Mirror frame too large');
  request=JSON.parse(line);let value;
  if(request.method==='create'){await engine.create(request.terminal_id,request.cols,request.rows,request.seed);value={created:true};}
  else if(request.method==='apply'){await engine.apply(request.terminal_id,request.event);value={applied:true};}
  else if(request.method==='batch'){
   if(!Array.isArray(request.events)||request.events.length<1||request.events.length>64)throw Error('Mirror batch limit');
   for(const event of request.events)await engine.apply(request.terminal_id,event);
   value={applied:true,count:request.events.length};
  }
  else if(request.method==='capture')value=engine.capture(request.terminal_id);
  else if(request.method==='dispose'){engine.dispose(request.terminal_id);value={disposed:true};}
  else throw Error('Unsupported mirror request');
  process.stdout.write(JSON.stringify({id:request.id,ok:true,value})+'\n');
 }catch{process.stdout.write(JSON.stringify({id:request?.id,ok:false,error:'Terminal checkpoint unavailable'})+'\n');}
}}finally{engine.close();}
