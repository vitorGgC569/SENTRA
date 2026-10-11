/* Test harness: execute the PRODUCTION MV3 identity block; send REAL HTTP
 * invalidation with a disposable relay bearer. No cookies or real login. */
"use strict";
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const crypto=require("node:crypto");
const mode=process.argv[2], stateFile=process.argv[3];
if (!["prepare","revoke"].includes(mode) || !stateFile) throw Error("invalid test mode");
const source=fs.readFileSync(path.resolve(__dirname,"../../edge_extension/service-worker.js"),"utf8");
const start=source.indexOf("// SENTRA_IDENTITY_REVOCATION_BEGIN");
const end=source.indexOf("// SENTRA_IDENTITY_REVOCATION_END");
if(start<0 || end<=start) throw Error("production MV3 block unavailable");
let state=fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,"utf8")):{};
const store={
 async get(keys){
   if(keys===null)return {...state};
   const names=typeof keys==="string"?[keys]:Array.isArray(keys)?keys:Object.keys(keys);
   return Object.fromEntries(names.filter(k=>Object.hasOwn(state,k)).map(k=>[k,state[k]]));
 },
 async set(values){Object.assign(state,values);fs.writeFileSync(stateFile,JSON.stringify(state));},
 async remove(names){
   for(const key of (typeof names==="string"?[names]:names))delete state[key];
   fs.writeFileSync(stateFile,JSON.stringify(state));
 }
};
const sha=process.env.SENTRA_TEST_SOURCE_HASH;
const url=process.env.SENTRA_TEST_HTTP_URL;
const token=process.env.SENTRA_TEST_HTTP_TOKEN;
if(!/^[a-f0-9]{64}$/.test(sha||"") || !/^http:\/\/127\.0\.0\.1:\d+$/.test(url||"") ||
   !token || token.length<32)throw Error("invalid disposable test HTTP configuration");
const calls=[];
const ctx={
 crypto:{randomUUID:()=>crypto.randomUUID()},
 chrome:{storage:{local:store},tabs:{query:async()=>[]}},
 OMA_SOURCE_HASH:sha,URL,
 omaRelay:async(route,options)=>{
   if(route!=="/browser-evidence/invalidate")throw Error("unexpected relay route");
   const payload=JSON.parse(options.body);
   calls.push({route,keys:Object.keys(payload).sort()});
   const response=await fetch(url+route,{
     method:"POST",headers:{"Content-Type":"application/json",
       "Origin":"chrome-extension://"+"a".repeat(32),
       "Authorization":"Bearer "+token},
     body:options.body
   });
   const result=await response.json();
   if(!response.ok)throw Error("loopback-denied-"+response.status);
   return result;
 }
};
vm.createContext(ctx);
vm.runInContext(source.slice(start,end),ctx,{timeout:2000});
(async()=>{
 if(mode==="prepare"){
   const doc=await ctx.omaIdPrepare(77,"document-abc123456","conversation12345");
   if(!doc || !doc.identity_epoch)throw Error("no V2 document prepared");
   process.stdout.write(JSON.stringify({worker:doc.worker,document_id:doc.document_id,
     identity_epoch:doc.identity_epoch,source_sha256:doc.source_sha256}));
 }else{
   if(!state.sentra_id_doc_77)throw Error("missing V2 document state");
   const ok=await ctx.omaIdInvalidate(77,"signed_out");
   if(!ok || state.sentra_id_revoke_77)throw Error("V2 invalidation not ACKed");
   process.stdout.write(JSON.stringify({ok:true,requests:calls}));
 }
})().catch(e=>{console.error("MV3 loopback producer test failed:",e.message);process.exitCode=1});
