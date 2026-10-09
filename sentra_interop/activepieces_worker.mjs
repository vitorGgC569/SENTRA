// Owned, one-invocation Activepieces SDK worker. No package install, fake SDK,
// retry loop or arbitrary import from untrusted catalog data.
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import readline from 'node:readline';
const MAX_FRAME=32*1024*1024;
const originalWrite=process.stdout.write.bind(process.stdout);
for(const name of ['log','info','debug','warn','error']) console[name]=()=>{};
const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
let firstResolve;
const first=new Promise(resolve=>{firstResolve=resolve;});
const pending=new Map();
const inFlight=new Set();
let rpcFailure=null;
let sequence=0;
function send(value){const text=JSON.stringify(value);if(Buffer.byteLength(text)>MAX_FRAME)throw new Error('FRAME_LIMIT');originalWrite(text+'\n');}
lines.on('line',line=>{
  try{
    if(Buffer.byteLength(line)>MAX_FRAME)throw new Error('FRAME_LIMIT');
    const message=JSON.parse(line);
    if(firstResolve){const resolve=firstResolve;firstResolve=null;resolve(message);return;}
    const callback=pending.get(message.id);
    if(!callback)throw new Error('UNKNOWN_RPC_RESPONSE');
    pending.delete(message.id);
    if(message.error)callback.reject(new Error('HOST_CONTEXT_DENIED'));
    else callback.resolve(message.value);
  }catch{finish({type:'failure',code:'PROTOCOL_ERROR'});}
});
function rpc(method,args){
  if(pending.size>=128)throw new Error('RPC_LIMIT');
  const id=++sequence;
  const promise=new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});send({type:'rpc',id,method,args});});
  inFlight.add(promise);
  promise.then(()=>inFlight.delete(promise),error=>{rpcFailure=error;inFlight.delete(promise);});
  return promise;
}
function unsupported(name){throw new Error('UNSUPPORTED_CONTEXT:'+name);}
function deniedObject(name){return new Proxy({}, {get(){unsupported(name);}});}
function finish(value){
  lines.close();process.stdin.pause();
  const text=JSON.stringify(value)+'\n';
  originalWrite(text,()=>process.exit(value.type==='result'?0:1));
}
async function bytes(data){
  if(Buffer.isBuffer(data))return data;
  if(typeof data==='string')return Buffer.from(data);
  if(data && typeof data[Symbol.asyncIterator]==='function'){
    const chunks=[];let size=0;
    for await(const chunk of data){const b=Buffer.from(chunk);size+=b.length;if(size>16*1024*1024)throw new Error('FILE_LIMIT');chunks.push(b);}
    return Buffer.concat(chunks);
  }
  throw new Error('INVALID_FILE_DATA');
}
try{
  const input=await first;
  if(input.version!==1 || typeof input.module_path!=='string' || typeof input.export_name!=='string')throw new Error('INVALID_HOST_CONFIG');
  const module=await import(pathToFileURL(input.module_path).href);
  const piece=module[input.export_name] ?? module.default?.[input.export_name];
  if(!piece || typeof piece.metadata!=='function' || typeof piece.getAction!=='function' || typeof piece.getTrigger!=='function')throw new Error('PIECE_SDK_INTERFACE_MISSING');
  const metadata=piece.metadata();
  if(input.command==='metadata'){finish({type:'result',output:{name:input.piece_name,version:input.piece_version,metadata}});}
  else{
    const contextVersion=piece.getContextInfo?.().version;
    if(contextVersion!=='2')throw new Error('UNSUPPORTED_CONTEXT_VERSION');
    await rpc('metadata.verify',{metadata});
    const hook=input.hook;
    const member=hook==='action'?piece.getAction(input.member):piece.getTrigger(input.member);
    if(!member)throw new Error('MEMBER_NOT_FOUND');
    const context={
      auth:input.auth ?? undefined,propsValue:input.props,
      executionType:input.execution_type ?? 'BEGIN',
      project:{id:input.project_id,externalId:()=>rpc('project.externalId',{})},
      flows:{current:{id:input.flow_id,version:{id:input.flow_version}},list:()=>unsupported('flows.list')},
      step:{name:input.member},
      store:{get:(key,scope)=>rpc('store.get',{key,scope}),put:(key,value,scope)=>rpc('store.put',{key,value,scope}),
             delete:(key,scope)=>rpc('store.delete',{key,scope})},
      connections:{get:key=>rpc('connections.get',{key})},
      files:{write:async({fileName,data})=>rpc('files.write',{fileName,data:(await bytes(data)).toString('base64')}),
             upload:async({fileName,data})=>rpc('files.upload',{fileName,data:(await bytes(data)).toString('base64')})},
      output:{update:params=>rpc('output.update',params)},
      tags:{add:params=>rpc('tags.add',params)},
      run:{id:input.operation_id,canPause:false,stop:()=>unsupported('run.stop'),respond:()=>unsupported('run.respond'),
           createWaitpoint:()=>unsupported('run.createWaitpoint'),waitForWaitpoint:()=>unsupported('run.waitForWaitpoint')},
      server:input.server ?? deniedObject('server'),
      webhookUrl:input.webhook_url,
      payload:input.trigger_payload,
      setSchedule:schedule=>rpc('schedule.set',schedule),
    };
    if(input.execution_type==='RESUME')context.resumePayload=input.resume_payload;
    const fn=hook==='action'?member.run:hook==='trigger-run'?member.run:member[hook];
    if(typeof fn!=='function')throw new Error('HOOK_NOT_SUPPORTED');
    send({type:'started',member:input.member});
    const output=await fn(context);
    // Some SDK methods such as setSchedule have a void signature. Do not
    // declare success while their real host RPC is still outstanding.
    while(inFlight.size)await Promise.all([...inFlight]);
    if(rpcFailure)throw rpcFailure;
    finish({type:'result',output:output===undefined?null:output});
  }
}catch{finish({type:'failure',code:'PIECE_EXECUTION_UNKNOWN'});}
