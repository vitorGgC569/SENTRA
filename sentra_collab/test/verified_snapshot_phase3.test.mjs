import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync} from "node:fs";
import {join} from "node:path";
import {tmpdir} from "node:os";
import * as Y from "yjs";
import {HocuspocusProvider} from "@hocuspocus/provider";
import {SQLiteHost} from "../sqlite_host.mjs";
import {createCollabServer} from "../server.mjs";
import {exportVerifiedSnapshot,inspectVerifiedSnapshot,MAX_ENVELOPE_BYTES} from "../verified_snapshot.mjs";
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function until(f,msg){for(let i=0;i<95;i++){if(await f())return;await wait(25);}assert.fail(msg);}
const folder=()=>{const root=mkdtempSync(join(tmpdir(),"sentra-verification-"));return {
 filename:join(root,"sqlite.db"),cleanup:()=>rmSync(root,{force:true,recursive:true})
};};
function ydoc(){
 const d=new Y.Doc();for(const r of ["layout","nodes","notes"])d.getMap(r);return d;
}
function makeSnapshot({forbidden=false}={}){
 const d=ydoc();
 d.getMap(forbidden?"runs":"notes").set("id",forbidden?"untrusted":"hello");
 const bytes=Y.encodeStateAsUpdate(d);d.destroy();return bytes;
}
test("canonical versioned binary envelope: hash, foreign, stale, altered, extra keys and oversized reject",async()=>{
 const snapshot=makeSnapshot();
 const loaded=async()=>({revision:7,snapshot});
 const {bytes,sha256}=await exportVerifiedSnapshot({workspaceId:"snap",authorizeRead:async()=>true,loadSnapshot:loaded});
 const duplicate=await exportVerifiedSnapshot({workspaceId:"snap",authorizeRead:async()=>true,loadSnapshot:loaded});
 assert.equal(sha256,duplicate.sha256);
 assert.deepEqual(bytes,duplicate.bytes);
 const view=inspectVerifiedSnapshot({bytes,workspaceId:"snap",minRevision:7,trustedSha256:sha256});
 assert.equal(view.revision,7);
 assert.equal(view.display.notes.id,"hello");
 assert.equal(view.restoreAllowed,false);
 assert.throws(()=>inspectVerifiedSnapshot({bytes,workspaceId:"foreign",trustedSha256:sha256}),/denied/);
 assert.throws(()=>inspectVerifiedSnapshot({bytes,workspaceId:"snap",minRevision:8,trustedSha256:sha256}),/denied/);
 const tampered=new Uint8Array(bytes);tampered[12]^=4;
 assert.throws(()=>inspectVerifiedSnapshot({bytes:tampered,workspaceId:"snap",trustedSha256:sha256}),/denied/);
 assert.throws(()=>inspectVerifiedSnapshot({bytes,workspaceId:"snap"}),/denied/);
 assert.throws(()=>inspectVerifiedSnapshot({bytes:new Uint8Array(MAX_ENVELOPE_BYTES+1),
   workspaceId:"snap",trustedSha256:sha256}),/denied/);
 assert.equal(Object.isFrozen(view.display.nodes),true);
 const {createHash}=await import("node:crypto");
 const altered=Buffer.from(JSON.stringify({...JSON.parse(Buffer.from(bytes).toString()),privileged:"run"}));
 assert.throws(()=>inspectVerifiedSnapshot({bytes:altered,workspaceId:"snap",
   trustedSha256:createHash("sha256").update(altered).digest("hex")}),/denied/);
 await assert.rejects(exportVerifiedSnapshot({workspaceId:"snap",
   authorizeRead:async()=>false,loadSnapshot:loaded}),/denied/);
 await assert.rejects(exportVerifiedSnapshot({workspaceId:"snap",
   authorizeRead:async()=>true,loadSnapshot:async()=>({revision:1,snapshot:makeSnapshot({forbidden:true})})}),/denied/);
});
test("actual 2-peer Hocuspocus sync, verified SQLite export, process restart reload with exact digest",async()=>{
 const t=folder();let host=new SQLiteHost({filename:t.filename});
 host.setAccess("wsExport","alice","write");host.setAccess("wsExport","bob","read");
 const token=host.issueCredential("wsExport","alice");
 const aliceGrant=await host.callbacks.resolveGrant({token,workspaceId:"wsExport"});
 const start=async()=>{const app=createCollabServer({...host.callbacks,recheckMs:500});await app.listen();return app;};
 let app=await start();let providers=[];
 const client=async(principal,actualToken)=>{
   const doc=ydoc();
   let ready,failed;const connected=new Promise((resolve,reject)=>{ready=resolve;failed=reject;});
   const provider=new HocuspocusProvider({
     url:"ws://127.0.0.1:"+app.server.httpServer.address().port,
     name:"sentra-collab:v1:wsExport",token:actualToken,document:doc,
     onSynced:()=>ready(),onAuthenticationFailed:()=>failed(Error("denied"))
   });
   providers.push({provider,doc});await connected;return doc;
 };
 let verified,revision;
 try{
   const a=await client("alice",token);
   const b=await client("bob",host.issueCredential("wsExport","bob"));
   a.getMap("notes").set("shared","persisted & synchronized");
   await until(()=>b.getMap("notes").get("shared")==="persisted & synchronized","real WS sync");
   await until(async()=> (await host.callbacks.loadSnapshot({workspaceId:"wsExport"})).revision>0,"durable commit");
   verified=await exportVerifiedSnapshot({workspaceId:"wsExport",
     authorizeRead:({workspaceId})=>host.callbacks.checkGrant({...aliceGrant,workspaceId,action:"read"}),
     loadSnapshot:host.callbacks.loadSnapshot});
   revision=inspectVerifiedSnapshot({bytes:verified.bytes,workspaceId:"wsExport",
     minRevision:1,trustedSha256:verified.sha256}).revision;
 }finally{
   for(const p of providers){p.provider.destroy();p.doc.destroy();}
   await app.destroy();host.close();
 }
 host=new SQLiteHost({filename:t.filename});
 app=await start();providers=[];
 try{
   const read=await client("bob",host.issueCredential("wsExport","bob"));
   await until(()=>read.getMap("notes").get("shared")==="persisted & synchronized","disk reload");
   const refreshed=await exportVerifiedSnapshot({workspaceId:"wsExport",
     authorizeRead:async()=>true,loadSnapshot:host.callbacks.loadSnapshot});
   assert.equal(refreshed.sha256,verified.sha256);
   assert.equal(revision,(await host.callbacks.loadSnapshot({workspaceId:"wsExport"})).revision);
   assert.equal(inspectVerifiedSnapshot({bytes:verified.bytes,workspaceId:"wsExport",
     minRevision:revision,trustedSha256:refreshed.sha256}).display.notes.shared,
     "persisted & synchronized");
   assert.equal((await host.callbacks.loadSnapshot({workspaceId:"wsExport"})).revision,revision,
     "preview must not modify SQLite/ControlStore");
 }finally{
   for(const p of providers){p.provider.destroy();p.doc.destroy();}
   await app.destroy();host.close();t.cleanup();
 }
});
