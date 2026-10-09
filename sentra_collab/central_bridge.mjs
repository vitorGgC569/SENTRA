/** Actual ControlPlane-backed callbacks for the existing Hocuspocus sidecar. */
import * as Y from 'yjs';
import {createCollabServer} from './server.mjs';
import {validateYDocument,MAX_SNAPSHOT_BYTES} from './policy.mjs';
const unavailable=()=>{throw Error('collaboration-control-plane-unavailable');};

export class CentralCollabBridge {
  constructor({url,token,timeoutMs=3000,fetchImpl=globalThis.fetch}={}) {
    const endpoint=new URL(url);
    if(endpoint.protocol!=='http:'||!['127.0.0.1','[::1]'].includes(endpoint.hostname)||
       endpoint.username||endpoint.password||endpoint.search||endpoint.hash||
       endpoint.pathname!=='/api/collab/host'||typeof token!=='string'||token.length<32||
       !Number.isInteger(timeoutMs)||timeoutMs<100||timeoutMs>10000||typeof fetchImpl!=='function')unavailable();
    this.endpoint=endpoint.href;this.token=token;this.timeoutMs=timeoutMs;this.fetch=fetchImpl;
    this.callbacks=Object.freeze({
      resolveGrant:p=>this.rpc('resolveGrant',p),
      checkGrant:p=>this.rpc('checkGrant',p),
      consumeNonce:p=>this.rpc('consumeNonce',p),
      loadSnapshot:p=>this.loadSnapshot(p),
      commitSnapshot:p=>this.commitSnapshot(p)
    });
  }
  async rpc(method,params) {
    const signal=AbortSignal.timeout(this.timeoutMs);
    const response=await this.fetch(this.endpoint,{method:'POST',redirect:'error',signal,
      headers:{'Authorization':'Bearer '+this.token,'Content-Type':'application/json'},
      body:JSON.stringify({method,params})});
    if(!response.ok)unavailable();
    const limit=Math.ceil(MAX_SNAPSHOT_BYTES*4/3)+16384;
    const length=Number(response.headers.get('content-length'));
    if(Number.isFinite(length)&&length>limit)unavailable();
    const reader=response.body?.getReader();if(!reader)unavailable();
    const chunks=[];let size=0;
    try {
      for(;;){const {done,value}=await reader.read();if(done)break;
        size+=value.byteLength;if(size>limit)unavailable();chunks.push(Buffer.from(value));}
    }finally{reader.releaseLock();}
    const result=JSON.parse(Buffer.concat(chunks,size).toString('utf8'));
    if(!result||result.ok!==true||!Object.hasOwn(result,'value'))unavailable();
    return result.value;
  }
  async loadSnapshot(params) {
    const stored=await this.rpc('loadSnapshot',params);
    if(!stored||!Number.isSafeInteger(stored.revision)||stored.revision<0)unavailable();
    if(stored.snapshot===null)return {revision:stored.revision,snapshot:null};
    if(typeof stored.snapshot!=='string'||stored.snapshot.length>Math.ceil(MAX_SNAPSHOT_BYTES*4/3)+8)unavailable();
    const bytes=Buffer.from(stored.snapshot,'base64');
    if(bytes.byteLength>MAX_SNAPSHOT_BYTES)unavailable();
    return {revision:stored.revision,snapshot:bytes};
  }
  async commitSnapshot(params) {
    if(!(params?.snapshot instanceof Uint8Array)||params.snapshot.length>MAX_SNAPSHOT_BYTES)unavailable();
    const doc=new Y.Doc();let presentation;
    try {
      for(const key of ['layout','nodes','notes'])doc.getMap(key);
      Y.applyUpdate(doc,params.snapshot);validateYDocument(doc,Y);
      presentation=Object.fromEntries(['layout','nodes','notes'].map(key=>[key,doc.getMap(key).toJSON()]));
    }finally{doc.destroy();}
    return await this.rpc('commitSnapshot',{...params,
      snapshot:Buffer.from(params.snapshot).toString('base64'),presentation});
  }
}

export function createCentralCollabServer({bridge,...options}={}) {
  if(!(bridge instanceof CentralCollabBridge))unavailable();
  return createCollabServer({...options,...bridge.callbacks,migrateNotes:true});
}
