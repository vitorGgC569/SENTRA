import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync, rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {fork} from "node:child_process";
import * as Y from "yjs";
import {HocuspocusProvider} from "@hocuspocus/provider";
import * as encoding from "lib0/encoding";
import {encodeAwarenessUpdate} from "y-protocols/awareness";
import {SQLiteHost} from "../sqlite_host.mjs";
import {createCollabServer} from "../server.mjs";
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,msg){
  for(let i=0;i<100;i++){if(await fn())return;await delay(25);}
  assert.fail(msg);
}
function localFile(){
  const folder=mkdtempSync(join(tmpdir(),"sentra-collab-sqlite-"));
  return {filename:join(folder,"fixture.sqlite"),cleanup:()=>rmSync(folder,{recursive:true,force:true})};
}
function issue(db,ws,principal,permission="write"){
  db.setAccess(ws,principal,permission);
  return db.issueCredential(ws,principal);
}
function makeDoc(){
  const doc=new Y.Doc();
  for(const name of ["layout","nodes","notes"])doc.getMap(name);
  return doc;
}
async function startSidecar(db) {
  const app=createCollabServer({...db.callbacks,recheckMs:500});
  await app.listen();
  assert.equal(app.server.httpServer.address().address,"127.0.0.1");
  const clients=[];
  function joinPeer(ws,token) {
    const document=makeDoc();
    let resolve,reject;
    const ready=new Promise((ok,fail)=>{resolve=ok;reject=fail;});
    const provider=new HocuspocusProvider({
      url:"ws://127.0.0.1:"+app.server.httpServer.address().port,
      name:"sentra-collab:v1:"+ws,document,token,
      onSynced:()=>resolve(),
      onAuthenticationFailed:()=>reject(Error("collaboration-denied"))
    });
    clients.push({document,provider});
    return {document,provider,ready};
  }
  return {app,joinPeer,async close(){
    for(const c of clients){c.provider.destroy();c.document.destroy();}
    await app.destroy();
  }};
}
function worker(filename,crash=false){
  const child=fork(fileURLToPath(new URL("./sqlite_worker.mjs",import.meta.url)),
    [filename,...(crash?["crash"]:[])],{stdio:["ignore","ignore","ignore","ipc"]});
  let seq=0;
  const waiting=new Map();
  child.on("message",m=>{
    const p=waiting.get(m.id);if(!p)return;
    waiting.delete(m.id);
    m.ok?p.resolve(m.value):p.reject(Error(m.error));
  });
  child.on("exit",code=>{
    for(const p of waiting.values())p.reject(Error("child-exit:"+code));
    waiting.clear();
  });
  return {child,request(op,args={}){
    const id=++seq;
    return new Promise((resolve,reject)=>{
      waiting.set(id,{resolve,reject});
      child.send({id,op,args},err=>{if(err){waiting.delete(id);reject(err);}});
    });
  },async close(){
    if(child.exitCode!==null)return;
    child.disconnect();
    await new Promise(resolve=>child.once("exit",resolve));
  }};
}
function update(field,value){
  const doc=makeDoc();
  doc.getMap("notes").set(field,value);
  const bytes=Y.encodeStateAsUpdate(doc);
  doc.destroy();
  return bytes;
}
test("YJS+SQLite real WS: viewport, nodes, notes, concurrent independent edits and convergence",async()=>{
  const dir=localFile(),store=new SQLiteHost({filename:dir.filename});
  const alice=issue(store,"geom","alice"),bob=issue(store,"geom","bob");
  const sidecar=await startSidecar(store);
  try {
    const a=sidecar.joinPeer("geom",alice),b=sidecar.joinPeer("geom",bob);
    await Promise.all([a.ready,b.ready]);
    a.document.getMap("layout").set("viewport",{x:42,y:-12,zoom:1.2});
    a.document.getMap("nodes").set("terminalA",{x:10,y:15,width:280,height:170});
    await until(()=>b.document.getMap("nodes").has("terminalA"),"geometry never reached peer");
    await until(()=>b.document.getMap("layout").has("viewport"),"viewport never reached peer");
    a.document.getMap("notes").set("aliceNote","hello from A");
    b.document.getMap("notes").set("bobNote","hello from B");
    await until(()=>a.document.getMap("notes").has("bobNote")&&
      b.document.getMap("notes").has("aliceNote"),"concurrent notes did not converge");
    assert.deepEqual(a.document.getMap("layout").toJSON(),b.document.getMap("layout").toJSON());
    assert.deepEqual(a.document.getMap("nodes").toJSON(),b.document.getMap("nodes").toJSON());
    assert.deepEqual(a.document.getMap("notes").toJSON(),b.document.getMap("notes").toJSON());
    assert.equal(a.document.share.has("runs"),false);
    assert.equal(a.document.share.has("leases"),false);
    const snapshot=await store.callbacks.loadSnapshot({workspaceId:"geom"});
    assert.ok(snapshot.revision>=4,"all four display updates are persisted");
    const saved=makeDoc();Y.applyUpdate(saved,snapshot.snapshot);
    assert.deepEqual(saved.getMap("notes").toJSON(),a.document.getMap("notes").toJSON());
    saved.destroy();
  }finally{await sidecar.close();store.close();dir.cleanup();}
});
test("YJS+SQLite WS: real on-disk reload, replay deny, new nonce and workspace isolation",async()=>{
  const dir=localFile();
  let host=new SQLiteHost({filename:dir.filename});
  const original=issue(host,"reload","alice");
  let sidecar=await startSidecar(host);
  try {
    const a=sidecar.joinPeer("reload",original);
    await a.ready;
    a.document.getMap("notes").set("persisted","SQLite WAL durable");
    await until(async()=> (await host.callbacks.loadSnapshot({workspaceId:"reload"})).revision===1,
      "SQLite commit timed out");
    const stored=await host.callbacks.loadSnapshot({workspaceId:"reload"});
    assert.equal(stored.revision,1);
  }finally{await sidecar.close();host.close();}
  host=new SQLiteHost({filename:dir.filename});
  sidecar=await startSidecar(host);
  try {
    await assert.rejects(sidecar.joinPeer("reload",original).ready,/denied/);
    const a=sidecar.joinPeer("reload",host.issueCredential("reload","alice"));
    await a.ready;
    await until(()=>a.document.getMap("notes").get("persisted")==="SQLite WAL durable",
      "state did not reload from disk");
    assert.equal((await host.callbacks.loadSnapshot({workspaceId:"reload"})).revision,1);
    host.setAccess("otherWS","alice","read");
    await assert.rejects(sidecar.joinPeer("otherWS",
      host.issueCredential("reload","alice")).ready,/denied/);
  }finally{await sidecar.close();host.close();dir.cleanup();}
});
test("SQLite grant epoch checked inside atomic commit; denial has no new snapshot",async()=>{
  const dir=localFile(),db=new SQLiteHost({filename:dir.filename});
  try {
    const token=issue(db,"revoke","alice");
    const context=await db.callbacks.resolveGrant({workspaceId:"revoke",token});
    db.revoke("revoke","alice");
    assert.equal(await db.callbacks.checkGrant({...context,action:"write"}),false);
    await assert.rejects(db.callbacks.commitSnapshot({
      workspaceId:"revoke",principalId:"alice",epoch:context.epoch,context,
      expectedRevision:0,snapshot:update("foo","deny")
    }),/denied/);
    assert.equal((await db.callbacks.loadSnapshot({workspaceId:"revoke"})).revision,0);
    assert.equal(await db.callbacks.consumeNonce({
      fingerprint:"0".repeat(64),workspaceId:"revoke",principalId:"alice",
      epoch:context.epoch,expiresAt:context.expiresAt
    }),false);
  }finally{db.close();dir.cleanup();}
});
test("SQLite injected failure inside transaction rolls back snapshot and revision",async()=>{
  const dir=localFile();
  const db=new SQLiteHost({filename:dir.filename,
    fault:stage=>{if(stage==="after-write-before-commit")throw Error("simulated-disk-failure");}
  });
  try {
    const token=issue(db,"dbError","alice");
    const context=await db.callbacks.resolveGrant({token,workspaceId:"dbError"});
    await assert.rejects(db.callbacks.commitSnapshot({
      workspaceId:"dbError",principalId:"alice",epoch:context.epoch,
      context,expectedRevision:0,snapshot:update("bad","rollback")
    }),/denied/);
    assert.equal((await db.callbacks.loadSnapshot({workspaceId:"dbError"})).revision,0);
  }finally{db.close();dir.cleanup();}
});
test("SQLite TWO REAL PROCESSES: global nonce uniqueness and competing revision CAS",async()=>{
  const dir=localFile(),db=new SQLiteHost({filename:dir.filename});
  const token=issue(db,"multi","alice");
  const context=await db.callbacks.resolveGrant({token,workspaceId:"multi"});
  const a=worker(dir.filename),b=worker(dir.filename);
  try {
    const {createHash}=await import("node:crypto");
    const fingerprint=createHash("sha256").update(token).digest("hex");
    const nonce={fingerprint,workspaceId:"multi",principalId:"alice",
      epoch:context.epoch,expiresAt:context.expiresAt};
    const results=await Promise.all([a.request("consume",nonce),b.request("consume",nonce)]);
    assert.deepEqual(results.sort(),[false,true],"one-use nonce must hold across real processes");
    const payload={
      workspaceId:"multi",principalId:"alice",epoch:context.epoch,context,
      expectedRevision:0,snapshotBase64:Buffer.from(update("win","only-one")).toString("base64")
    };
    const commitments=await Promise.allSettled([
      a.request("commit",payload),b.request("commit",payload)
    ]);
    assert.deepEqual(commitments.map(x=>x.status).sort(),["fulfilled","rejected"]);
    const loaded=await b.request("snapshot",{workspaceId:"multi"});
    assert.equal(loaded.revision,1);
    assert.ok(loaded.snapshotBase64);
    const recovered=makeDoc();
    Y.applyUpdate(recovered,Buffer.from(loaded.snapshotBase64,"base64"));
    assert.equal(recovered.getMap("notes").get("win"),"only-one");
    recovered.destroy();
  }finally{await Promise.all([a.close(),b.close()]);db.close();dir.cleanup();}
});
test("SQLite TWO REAL PROCESSES: epoch revocation fences writer across instances",async()=>{
  const dir=localFile(),db=new SQLiteHost({filename:dir.filename});
  const token=issue(db,"revokedMulti","alice");
  const context=await db.callbacks.resolveGrant({token,workspaceId:"revokedMulti"});
  const a=worker(dir.filename),b=worker(dir.filename);
  try {
    await a.request("revoke",{workspaceId:"revokedMulti",principalId:"alice"});
    assert.equal(await b.request("check",{...context,action:"write"}),false);
    const denied={
      workspaceId:"revokedMulti",principalId:"alice",epoch:context.epoch,context,
      expectedRevision:0,snapshotBase64:Buffer.from(update("outdated","reject")).toString("base64")
    };
    await assert.rejects(b.request("commit",denied),/denied/);
    assert.equal((await a.request("snapshot",{workspaceId:"revokedMulti"})).revision,0);
  }finally{await Promise.all([a.close(),b.close()]);db.close();dir.cleanup();}
});
test("SQLite child-process CRASH during uncommitted WAL write rolls back on reopen",async()=>{
  const dir=localFile(),db=new SQLiteHost({filename:dir.filename});
  const token=issue(db,"crashWS","alice");
  const context=await db.callbacks.resolveGrant({token,workspaceId:"crashWS"});
  const killer=worker(dir.filename,true);
  try {
    const request={
      workspaceId:"crashWS",principalId:"alice",epoch:context.epoch,context,
      expectedRevision:0,snapshotBase64:Buffer.from(update("crash","not-durable")).toString("base64")
    };
    await assert.rejects(killer.request("commit",request),/child-exit:77/);
    assert.equal(killer.child.exitCode,77);
    assert.equal((await db.callbacks.loadSnapshot({workspaceId:"crashWS"})).revision,0);
    const fresh=new SQLiteHost({filename:dir.filename});
    try {
      assert.equal((await fresh.callbacks.loadSnapshot({workspaceId:"crashWS"})).revision,0);
      const successful=await fresh.callbacks.commitSnapshot({
        workspaceId:"crashWS",principalId:"alice",epoch:context.epoch,context,
        expectedRevision:0,snapshot:update("after","recovery")
      });
      assert.equal(successful.revision,1);
    }finally{fresh.close();}
  }finally{await killer.close();db.close();dir.cleanup();}
});
function sendAwarenessForgery(peer,clients,states) {
  const ws=peer.provider.configuration.websocketProvider.webSocket;
  assert.ok(ws&&ws.readyState===1,"real authenticated websocket required");
  const bytes=encodeAwarenessUpdate(peer.provider.awareness,clients,states);
  const frame=encoding.createEncoder();
  encoding.writeVarString(frame,peer.provider.effectiveName);
  encoding.writeVarUint(frame,1); // upstream @hocuspocus MessageType.Awareness
  encoding.writeVarUint8Array(frame,bytes);
  ws.send(encoding.toUint8Array(frame));
}
const identityStates=peer=>[...peer.provider.awareness.getStates().values()];
test("y-protocols real WS: server-stamped identity/cursor/selection, reader presence, tenant isolation, tombstone",async()=>{
  const dir=localFile(),db=new SQLiteHost({filename:dir.filename});
  const alice=issue(db,"presenceDb","alice"),bob=issue(db,"presenceDb","bob","read");
  const outsider=issue(db,"otherPresenceDb","eve","read");
  const ws=await startSidecar(db);
  try{
    const a=ws.joinPeer("presenceDb",alice);
    const b=ws.joinPeer("presenceDb",bob);
    const c=ws.joinPeer("otherPresenceDb",outsider);
    await Promise.all([a.ready,b.ready,c.ready]);
    a.provider.awareness.setLocalState({
      user:{id:"admin"},token:"DO-NOT-LEAK-TOKEN",
      secret:"PRIVATE",grant:{write:true},lease:{id:"lease"},
      cursor:{x:13,y:29},selection:"terminalA"
    });
    await until(()=>identityStates(b).some(v=>v?.user?.id==="alice"),
      "peer must see sanitized sender");
    const state=identityStates(b).find(v=>v?.user?.id==="alice");
    assert.deepEqual(state,{user:{id:"alice"},cursor:{x:13,y:29},selection:"terminalA"});
    assert.equal(identityStates(c).some(v=>v?.user?.id==="alice"),false);
    b.provider.awareness.setLocalState({user:{id:"superuser"},cursor:{x:50,y:51}});
    await until(()=>identityStates(a).some(v=>v?.user?.id==="bob"),
      "read-only member must be allowed to send non-privileged presence");
    assert.deepEqual(identityStates(a).find(v=>v?.user?.id==="bob"),
      {user:{id:"bob"},cursor:{x:50,y:51}});
    a.provider.awareness.setLocalState(null); // owned tombstone
    await until(()=>!identityStates(b).some(v=>v?.user?.id==="alice"),
      "owned tombstone should remove presence");
    assert.equal(identityStates(b).some(v=>JSON.stringify(v).includes("PRIVATE")),false);
  }finally{await ws.close();db.close();dir.cleanup();}
});
test("y-protocols real WS: foreign tombstone is discarded; forged victim ID fails closed",async()=>{
  const dir=localFile(),db=new SQLiteHost({filename:dir.filename});
  const aToken=issue(db,"tombWS","alice"),bToken=issue(db,"tombWS","bob","read");
  const ws=await startSidecar(db);
  try{
    const a=ws.joinPeer("tombWS",aToken),b=ws.joinPeer("tombWS",bToken);
    await Promise.all([a.ready,b.ready]);
    a.provider.awareness.setLocalState({cursor:{x:1,y:2}});
    b.provider.awareness.setLocalState({cursor:{x:3,y:4}});
    await until(()=>identityStates(a).some(v=>v?.user?.id==="bob")&&
      identityStates(b).some(v=>v?.user?.id==="alice"),"missing both identities");
    const victimId=b.document.clientID;
    // Raw forged awareness frame over real authenticated loopback WebSocket:
    // attacker tries to set another client's presence to null (offline).
    sendAwarenessForgery(a,[victimId],new Map([[victimId,null]]));
    await until(()=>ws.app.server.hocuspocus.getConnectionsCount()===1,
      "foreign tombstone must disconnect the offender");
    // The offender's local provider may clear its remote state on disconnect.
    // Only the innocent peer's state/ownership matters.
    assert.deepEqual(b.provider.awareness.getLocalState().cursor,{x:3,y:4});
    const watcher=ws.joinPeer("tombWS",issue(db,"tombWS","charlie","read"));
    await watcher.ready;
    await until(()=>identityStates(watcher).some(v=>v?.user?.id==="bob"),
      "innocent victim must remain visible to a newly authenticated reader");
    const reconnected=ws.joinPeer("tombWS",db.issueCredential("tombWS","alice"));
    await reconnected.ready;
    reconnected.provider.awareness.setLocalState({cursor:{x:5,y:6}});
    await until(()=>identityStates(b).some(v=>v?.user?.id==="alice"),
      "freshly authenticated peer should rejoin without stealing identity");
    // Now try non-null impersonation from a new valid connection.
    sendAwarenessForgery(reconnected,[victimId],
      new Map([[victimId,{user:{id:"admin"},cursor:{x:8,y:9}}]]));
    await until(()=>ws.app.server.hocuspocus.getConnectionsCount()===2,
      "client ID impersonation should close the offender");
    assert.equal(identityStates(watcher).some(v=>v?.user?.id==="bob"),true);
    assert.equal((await db.callbacks.loadSnapshot({workspaceId:"tombWS"})).revision,0);
  }finally{await ws.close();db.close();dir.cleanup();}
});
test("SQLite real WS: transaction write fault rejects without peer broadcast; new process can recover",async()=>{
  const dir=localFile();
  let db=new SQLiteHost({filename:dir.filename,
    fault:()=>{throw Error("injected-I/O-denial");}
  });
  const alice=issue(db,"ioFail","alice"),bob=issue(db,"ioFail","bob","read");
  let sidecar=await startSidecar(db);
  try{
    const writer=sidecar.joinPeer("ioFail",alice);
    const viewer=sidecar.joinPeer("ioFail",bob);
    await Promise.all([writer.ready,viewer.ready]);
    writer.document.getMap("notes").set("rejected","must-not-reach-bob");
    await until(()=>sidecar.app.server.hocuspocus.getConnectionsCount()===1,
      "failing precommit should evict writer");
    assert.equal(viewer.document.getMap("notes").get("rejected"),undefined);
    assert.equal((await db.callbacks.loadSnapshot({workspaceId:"ioFail"})).revision,0);
  }finally{await sidecar.close();db.close();}
  db=new SQLiteHost({filename:dir.filename});
  sidecar=await startSidecar(db);
  try{
    await assert.rejects(sidecar.joinPeer("ioFail",alice).ready,/denied/,
      "old token was spent even though persistence rolled back");
    const writer=sidecar.joinPeer("ioFail",db.issueCredential("ioFail","alice"));
    const viewer=sidecar.joinPeer("ioFail",db.issueCredential("ioFail","bob"));
    await Promise.all([writer.ready,viewer.ready]);
    writer.document.getMap("notes").set("accepted","after-recovery");
    await until(()=>viewer.document.getMap("notes").get("accepted")==="after-recovery",
      "fresh write should become visible after recovered DB");
    assert.equal((await db.callbacks.loadSnapshot({workspaceId:"ioFail"})).revision,1);
  }finally{await sidecar.close();db.close();dir.cleanup();}
});
