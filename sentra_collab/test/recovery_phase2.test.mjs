import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fork} from "node:child_process";
import {fileURLToPath} from "node:url";
import * as Y from "yjs";
import {HocuspocusProvider} from "@hocuspocus/provider";
import {SQLiteHost} from "../sqlite_host.mjs";
import {createCollabServer} from "../server.mjs";
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(pred,label){for(let n=0;n<90;n++){
  if(await pred())return;await delay(25);}assert.fail(label);}
const temp=()=>{
  const folder=mkdtempSync(join(tmpdir(),"sentra-recovery-"));
  return {filename:join(folder,"store.sqlite"),cleanup:()=>rmSync(folder,{recursive:true,force:true})};
};
const doc=()=>{const d=new Y.Doc();for(const name of ["layout","nodes","notes"])d.getMap(name);return d;};
const encoded=(name,value)=>{
  const d=doc();d.getMap("notes").set(name,value);
  const result=Y.encodeStateAsUpdate(d);d.destroy();return result;
};
function worker(filename){
  const child=fork(fileURLToPath(new URL("./sqlite_worker.mjs",import.meta.url)),
    [filename],{stdio:["ignore","ignore","ignore","ipc"]});
  let counter=0;const pending=new Map();
  child.on("message",m=>{const p=pending.get(m.id);if(!p)return;
    pending.delete(m.id);m.ok?p.resolve(m.value):p.reject(Error(m.error));
  });
  child.on("exit",()=>{
    for(const p of pending.values())p.reject(Error("child-exited"));pending.clear();
  });
  return {
    request(op,args={}){
      return new Promise((resolve,reject)=>{
        const id=++counter;pending.set(id,{resolve,reject});
        child.send({id,op,args},e=>{if(e){pending.delete(id);reject(e);}});
      });
    },
    async close(){
      if(child.exitCode!==null)return;
      child.disconnect();await new Promise(r=>child.once("exit",r));
    }
  };
}
async function sidecar(callbacks) {
  const app=createCollabServer({...callbacks,recheckMs:500});
  await app.listen();
  const connected=[];
  function joinPeer(workspaceId,token){
    const document=doc();
    let success,fail;
    const ready=new Promise((r,j)=>{success=r;fail=j;});
    const provider=new HocuspocusProvider({
      url:"ws://127.0.0.1:"+app.server.httpServer.address().port,
      name:"sentra-collab:v1:"+workspaceId,document,token,
      onSynced:()=>success(),onAuthenticationFailed:()=>fail(Error("denied"))
    });
    connected.push({provider,document});
    return {provider,document,ready};
  }
  return {app,joinPeer,async close(){
    for(const peer of connected){peer.provider.destroy();peer.document.destroy();}
    await app.destroy();
  }};
}
test("SQLite recovery read-only classification: absent, committed, diverged; no replay",async()=>{
  const t=temp(),host=new SQLiteHost({filename:t.filename});
  const token=(host.setAccess("verify","alice","write"),host.issueCredential("verify","alice"));
  try{
    const context=await host.callbacks.resolveGrant({workspaceId:"verify",token});
    const candidate=encoded("a","v1");
    const probe=()=>host.reconcileCommit({workspaceId:"verify",
      expectedRevision:0,candidateSnapshot:candidate});
    assert.deepEqual((await probe()).status,"not-committed");
    assert.equal((await host.callbacks.loadSnapshot({workspaceId:"verify"})).revision,0);
    await host.callbacks.commitSnapshot({
      workspaceId:"verify",principalId:"alice",epoch:context.epoch,context,
      expectedRevision:0,snapshot:candidate
    });
    assert.deepEqual((await probe()).status,"committed");
    assert.equal((await host.reconcileCommit({workspaceId:"verify",expectedRevision:0,
      candidateSnapshot:encoded("other","v1")})).status,"diverged");
    assert.equal((await host.reconcileCommit({workspaceId:"verify",expectedRevision:9,
      candidateSnapshot:candidate})).status,"diverged");
    assert.equal((await host.callbacks.loadSnapshot({workspaceId:"verify"})).revision,1,
      "recovery inspection must not write or reapply updates");
  }finally{host.close();t.cleanup();}
});
test("two real SQLite processes agree on recovered committed revision and consumed nonce",async()=>{
  const t=temp(),host=new SQLiteHost({filename:t.filename});
  const token=(host.setAccess("forked","alice","write"),host.issueCredential("forked","alice"));
  const a=worker(t.filename),b=worker(t.filename);
  try {
    const context=await host.callbacks.resolveGrant({workspaceId:"forked",token});
    const candidate=encoded("memo","committed");
    const request={workspaceId:"forked",principalId:"alice",epoch:context.epoch,
      context,expectedRevision:0,snapshotBase64:Buffer.from(candidate).toString("base64")};
    assert.equal((await a.request("commit",request)).revision,1);
    const query={workspaceId:"forked",expectedRevision:0,
      snapshotBase64:request.snapshotBase64};
    const results=await Promise.all([a.request("reconcile",query),b.request("reconcile",query)]);
    assert.deepEqual(results.map(v=>v.status),["committed","committed"]);
    assert.equal((await host.callbacks.loadSnapshot({workspaceId:"forked"})).revision,1);
    const {createHash}=await import("node:crypto");
    const fingerprint=createHash("sha256").update(token).digest("hex");
    const nonce={workspaceId:"forked",principalId:"alice",
      epoch:context.epoch,expiresAt:context.expiresAt,fingerprint};
    assert.deepEqual((await Promise.all([
      a.request("consume",nonce),b.request("consume",nonce)])).sort(),[false,true]);
  }finally{await Promise.all([a.close(),b.close()]);host.close();t.cleanup();}
});
test("ambiguous WS precommit quarantines the writer but not innocent peer; clean restart reconciles",async()=>{
  const t=temp();let host=new SQLiteHost({filename:t.filename});
  host.setAccess("uncertain","alice","write");
  host.setAccess("uncertain","bob","write");
  const alice=host.issueCredential("uncertain","alice"),bob=host.issueCredential("uncertain","bob");
  let side=await sidecar({...host.callbacks,
    commitSnapshot:async request=>{
      await host.callbacks.commitSnapshot(request);
      throw Error("ack-lost-after-commit");
    }
  });
  try {
    const a=side.joinPeer("uncertain",alice),b=side.joinPeer("uncertain",bob);
    await Promise.all([a.ready,b.ready]);
    a.document.getMap("notes").set("committed","ack-lost");
    await until(async()=> (await host.callbacks.loadSnapshot({workspaceId:"uncertain"})).revision===1,
      "commit was not stored");
    await until(async()=> (await side.app.inspectRecovery("uncertain")).quarantined,
      "ambiguous commit must quarantine live Y.Doc");
    const status=await side.app.inspectRecovery("uncertain");
    assert.equal(status.revision,0);
    assert.equal(status.persistedRevision,1);
    assert.equal(status.restartRequired,true);
    await until(()=>side.app.server.hocuspocus.getConnectionsCount()===1,
      "only the offending writer should disconnect");
    assert.equal(b.document.getMap("notes").get("committed"),undefined,
      "no broadcast before accepted ACK");
    b.document.getMap("notes").set("attempt","blocked-after-uncertain");
    await delay(100);
    assert.equal((await host.callbacks.loadSnapshot({workspaceId:"uncertain"})).revision,1,
      "quarantined document must never commit subsequent updates");
  }finally{await side.close();host.close();}
  host=new SQLiteHost({filename:t.filename});
  side=await sidecar(host.callbacks);
  try {
    await assert.rejects(side.joinPeer("uncertain",alice).ready,/denied/,
      "used grant stays consumed across real storage restart");
    const a=side.joinPeer("uncertain",host.issueCredential("uncertain","alice"));
    await a.ready;
    assert.equal(a.document.getMap("notes").get("committed"),"ack-lost");
    assert.equal(a.document.getMap("notes").get("attempt"),undefined);
    assert.equal((await side.app.inspectRecovery("uncertain")).restartRequired,false);
  }finally{await side.close();host.close();t.cleanup();}
});
test("timeout UNCERTAIN precommit rejects without applying mutation; late commit cannot be replayed",async()=>{
  const t=temp(),host=new SQLiteHost({filename:t.filename});
  const token=(host.setAccess("timeoutWs","alice","write"),
    host.issueCredential("timeoutWs","alice"));
  let complete;
  const pending=new Promise(resolve=>{complete=resolve;});
  const server=await sidecar({...host.callbacks,
    commitSnapshot:async request=>{await pending;return host.callbacks.commitSnapshot(request);}
  });
  try{
    // The server default commit timeout is finite (4 s). Exercise the small
    // deterministic timeout at the exact PrecommitGate class boundary too.
    const {PrecommitGate}=await import("../precommit.mjs");
    const gate=new PrecommitGate({
      authorize:async()=>true,commitTimeoutMs:25,
      commitSnapshot:async()=>{await pending;return {revision:1};}
    });
    const document=doc(),remote=doc();
    remote.getMap("notes").set("uncertain","never auto apply");
    const update=Y.encodeStateAsUpdate(remote);
    const context={workspaceId:"timeoutWs",principalId:"alice",permission:"write",
      epoch:1,expiresAt:Date.now()+10000};
    const connection={context,readOnly:false};
    gate.setRevision("sentra-collab:v1:timeoutWs",0);
    await assert.rejects(gate.authorizeSync({context,connection,
      documentName:"sentra-collab:v1:timeoutWs",document,
      type:2,payload:update}),/denied/);
    assert.equal(gate.recoveryState("sentra-collab:v1:timeoutWs").quarantined,true);
    assert.equal(document.getMap("notes").get("uncertain"),undefined);
    complete();
    await delay(35);
    assert.equal(gate.recoveryState("sentra-collab:v1:timeoutWs").revision,0);
    document.destroy();remote.destroy();
  }finally{complete();await server.close();host.close();t.cleanup();}
});
