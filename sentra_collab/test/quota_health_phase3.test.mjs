import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync} from "node:fs";
import {join} from "node:path";
import {tmpdir} from "node:os";
import * as Y from "yjs";
import * as encoding from "lib0/encoding";
import {HocuspocusProvider} from "@hocuspocus/provider";
import {SQLiteHost} from "../sqlite_host.mjs";
import {createCollabServer} from "../server.mjs";
import {LocalAdmission} from "../local_admission.mjs";
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(predicate,reason){
 for(let i=0;i<100;i++){if(predicate())return;await pause(25);}
 assert.fail(reason);
}
async function fixture(quotas){
 const folder=mkdtempSync(join(tmpdir(),"sentra-admission-"));
 const host=new SQLiteHost({filename:join(folder,"admission.sqlite")});
 for(const ws of ["alpha","beta"]){
   for(const who of ["alice","bob","charlie"])
     host.setAccess(ws,who,who==="bob"?"read":"write");
 }
 const sidecar=createCollabServer({...host.callbacks,quotas,recheckMs:500});
 await sidecar.listen();
 assert.equal(sidecar.server.httpServer.address().address,"127.0.0.1");
 const peers=[];
 function connect(ws,who,token=host.issueCredential(ws,who)){
   const document=new Y.Doc();
   for(const r of ["layout","nodes","notes"])document.getMap(r);
   let ok,no;
   const ready=new Promise((resolve,reject)=>{ok=resolve;no=reject;});
   const provider=new HocuspocusProvider({
     url:"ws://127.0.0.1:"+sidecar.server.httpServer.address().port,
     name:"sentra-collab:v1:"+ws,token,document,
     onSynced:()=>ok(),onAuthenticationFailed:()=>{
       no(Error("collaboration-denied"));
       provider.destroy(); // do not retry an intentionally rejected one-use token
     }
   });
   peers.push({provider,document});
   return {ready,provider,document,token};
 }
 return {host,sidecar,connect,async close(){
   for(const p of peers){p.provider.destroy();p.document.destroy();}
   await sidecar.destroy();host.close();rmSync(folder,{force:true,recursive:true});
 }};
}
test("local admissions: principal/workspace caps, one-use, revoke, fresh-grant reconnect and health no PII",async()=>{
 const f=await fixture({maxPerPrincipal:1,maxPerWorkspace:2,maxTotal:3,maxFramesPerWindow:120});
 try {
   const alice=f.connect("alpha","alice");
   const bob=f.connect("alpha","bob");
   await Promise.all([alice.ready,bob.ready]);
   const duplicate=f.connect("beta","alice");
   await assert.rejects(duplicate.ready,/denied/,"principal cap must deny a second workspace socket");
   const overflow=f.connect("alpha","charlie");
   await assert.rejects(overflow.ready,/denied/,"workspace cap must deny third connection");
   const h=f.sidecar.localHealth();
   console.info("CRIT003_HEALTH_ADMISSION",JSON.stringify(h));
   assert.equal(h.activeSessions,2);
   assert.equal(h.activeWorkspaces,1);
   assert.ok(h.accepted>=2);
   assert.ok(h.rejected>=2);
   assert.ok(Number.isFinite(h.admissionLatencyP95Ms));
   const publicHealth=JSON.stringify(h);
   for(const secret of ["alice","bob","alpha","beta","principalId","workspaceId","token"])
     assert.equal(publicHealth.includes(secret),false,"health leaked a sensitive field");
   assert.equal(typeof f.sidecar.server.localHealth,"undefined",
     "health must never appear on WS/HTTP Server");
   // Forbidden replay of an already consumed grant.
   const used=f.connect("alpha","alice",alice.token);
   await assert.rejects(used.ready,/denied/);
   alice.provider.destroy();alice.document.destroy();
   await until(()=>f.sidecar.localHealth().activeSessions===1,"old socket release failed");
   const fresh=f.connect("beta","alice");
   await fresh.ready;
   fresh.document.getMap("notes").set("safe","display only");
   await until(async()=> (await f.host.callbacks.loadSnapshot({workspaceId:"beta"})).revision===1,
     "fresh grant failed to commit display-only state");
   f.host.revoke("beta","alice");
   await until(()=>f.sidecar.localHealth().activeSessions===1,
     "revoked alpha/beta socket must be released by heartbeat");
   const metadata=f.sidecar.localHealth();
   assert.equal(metadata.activeSessions,1);
   assert.equal(bob.document.getMap("notes").get("safe"),undefined,
     "cross-workspace state leaked");
 }finally {
   await f.close();
   assert.equal(f.sidecar.localHealth().closed,true);
   assert.equal(f.sidecar.localHealth().activeSessions,0);
 }
});
test("real WS backpressure rejects burst only on offender; read-only peer remains",async()=>{
 const f=await fixture({maxPerPrincipal:2,maxPerWorkspace:3,maxTotal:4,
   maxFramesPerWindow:12,windowMs:10000});
 try {
   const a=f.connect("alpha","alice"),b=f.connect("alpha","bob");
   await Promise.all([a.ready,b.ready]);
   // Real upstream-framed SyncStep1 updates: read-only harmless request,
   // still subject to bounded client message budgets.
   const frame=encoding.createEncoder();
   encoding.writeVarString(frame,"sentra-collab:v1:alpha");
   encoding.writeVarUint(frame,0); // Hocuspocus sync
   encoding.writeVarUint(frame,0); // y-protocols SyncStep1
   encoding.writeVarUint8Array(frame,Y.encodeStateVector(a.document));
   const raw=encoding.toUint8Array(frame);
   const socket=a.provider.configuration.websocketProvider.webSocket;
   assert.equal(socket.readyState,1);
   for(let i=0;i<22&&socket.readyState===1;i++){
     if(f.sidecar.localHealth().framesRejected>0)break;
     socket.send(raw);
     await pause(20); // allow rejection to propagate; never flood a closing socket
   }
   await until(()=>f.sidecar.localHealth().framesRejected>0,
     "burst backpressure did not reject");
   await until(()=>f.sidecar.localHealth().activeSessions===1,
     "only the offender should have been disconnected");
   assert.ok(b.provider.synced,"innocent peer should still be live");
   assert.equal(f.sidecar.localHealth().activeWorkspaces,1);
   assert.equal(f.sidecar.localHealth().framesRejected>0,true);
   console.info("CRIT003_HEALTH_BACKPRESSURE",JSON.stringify(f.sidecar.localHealth()));
 }finally{await f.close();}
});
test("LocalAdmission unit: bounded time window, resource cleanup and invalid config",()=>{
 let now=1000;
 const guard=new LocalAdmission({clock:()=>now,maxPerPrincipal:1,maxPerWorkspace:1,
   maxTotal:1,maxFramesPerWindow:2,windowMs:100});
 guard.admit("socket-1",{workspaceId:"ws",principalId:"alice"},1.25);
 guard.frame("socket-1",128);guard.frame("socket-1",128);
 assert.throws(()=>guard.frame("socket-1",128),/denied/);
 now+=101;guard.frame("socket-1",128);
 assert.equal(guard.inspect().framesRejected,1);
 guard.release("socket-1");
 guard.close();assert.equal(guard.inspect().activeSessions,0);
 assert.throws(()=>guard.admit("s",{workspaceId:"ws",principalId:"alice"}),/denied/);
 assert.throws(()=>new LocalAdmission({maxPerPrincipal:0}),/denied/);
});
