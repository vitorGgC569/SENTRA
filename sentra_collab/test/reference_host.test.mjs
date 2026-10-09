import test from "node:test";
import assert from "node:assert/strict";
import * as Y from "yjs";
import {HocuspocusProvider} from "@hocuspocus/provider";
import {ReferenceHost} from "../reference_host.mjs";
import {createCollabServer} from "../server.mjs";

const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(predicate,why,attempts=80) {
  for(let i=0;i<attempts;i++){if(predicate())return;await delay(25);}
  assert.fail(why);
}
async function launch(host) {
  const app=createCollabServer({...host.callbacks,recheckMs:500});
  await app.listen();
  const clients=[];
  function join(workspaceId,token) {
    const document=new Y.Doc();
    let resolve,reject;
    const ready=new Promise((ok,fail)=>{resolve=ok;reject=fail;});
    const provider=new HocuspocusProvider({
      url:"ws://127.0.0.1:"+app.server.httpServer.address().port,
      name:"sentra-collab:v1:"+workspaceId,document,token,
      onSynced:()=>resolve(),
      onAuthenticationFailed:()=>reject(Error("collaboration-denied"))
    });
    clients.push({provider,document});
    return {provider,document,ready};
  }
  return {app,join,async close(){
    for(const c of clients){c.provider.destroy();c.document.destroy();}
    await app.destroy();
  }};
}
function grant(host,ws,principal,permission="write"){
  host.setAccess(ws,principal,permission);
  return host.issueCredential(ws,principal);
}
function docWithNote(field,value) {
  const d=new Y.Doc();
  for(const root of ["layout","nodes","notes"])d.getMap(root);
  d.getMap("notes").set(field,value);
  const snapshot=Y.encodeStateAsUpdate(d);
  d.destroy();
  return snapshot;
}
test("reference host: two authenticated peers share display state; read-only cannot write",async()=>{
  const host=new ReferenceHost();
  const alice=grant(host,"workspaceA","alice");
  const bob=grant(host,"workspaceA","bob","read");
  const charlie=grant(host,"workspaceB","charlie");
  const sidecar=await launch(host);
  try {
    const a=sidecar.join("workspaceA",alice);
    const b=sidecar.join("workspaceA",bob);
    const c=sidecar.join("workspaceB",charlie);
    await Promise.all([a.ready,b.ready,c.ready]);
    a.document.getMap("notes").set("memo","shared safely");
    await until(()=>b.document.getMap("notes").get("memo")==="shared safely",
      "read-only peer should receive authorized note");
    assert.equal(host.snapshotRevision("workspaceA"),1);
    assert.equal(c.document.getMap("notes").get("memo"),undefined);
    b.document.getMap("notes").set("attack","viewer cannot commit");
    await delay(120);
    assert.equal(a.document.getMap("notes").get("attack"),undefined);
    assert.equal(host.snapshotRevision("workspaceA"),1);
  }finally{await sidecar.close();}
});

test("reference host: restart retains nonce and snapshots while fresh scoped token works",async()=>{
  const host=new ReferenceHost();
  const firstToken=grant(host,"restartWS","alice");
  const first=await launch(host);
  try {
    const a=first.join("restartWS",firstToken);
    await a.ready;
    a.document.getMap("notes").set("memo","durable in shared fixture");
    await until(()=>host.snapshotRevision("restartWS")===1,"snapshot was not committed");
  }finally{await first.close();}
  const restarted=await launch(host);
  try {
    await assert.rejects(restarted.join("restartWS",firstToken).ready,/collaboration-denied/);
    const fresh=host.issueCredential("restartWS","alice");
    const a=restarted.join("restartWS",fresh);
    await a.ready;
    await until(()=>a.document.getMap("notes").get("memo")==="durable in shared fixture",
      "committed state not restored after restarting the server");
    assert.equal(a.document.getMap("notes").size,1);
    assert.equal(host.snapshotRevision("restartWS"),1);
  }finally{await restarted.close();}
});

test("reference host: epochs and revocation invalidate unused and active credentials",async()=>{
  const host=new ReferenceHost();
  const stale=grant(host,"epochWS","alice");
  const old=await host.callbacks.resolveGrant({workspaceId:"epochWS",token:stale});
  assert.equal(await host.callbacks.checkGrant({...old,action:"write"}),true);
  host.revoke("epochWS","alice");
  assert.equal(await host.callbacks.checkGrant({...old,action:"read"}),false);
  await assert.rejects(host.callbacks.resolveGrant({workspaceId:"epochWS",token:stale}));
  assert.throws(()=>host.issueCredential("epochWS","alice"));
  host.setAccess("epochWS","alice","write");
  await assert.rejects(host.callbacks.resolveGrant({workspaceId:"epochWS",token:stale}),
    "old unused token must not regain authority on regrant");
  const fresh=host.issueCredential("epochWS","alice");
  assert.ok((await host.callbacks.resolveGrant({workspaceId:"epochWS",token:fresh})).epoch>old.epoch);
});

test("reference host: workspace switch never transfers credentials or CRDT state",async()=>{
  const host=new ReferenceHost();
  const first=grant(host,"firstWS","alice");
  const second=grant(host,"secondWS","alice");
  const sidecar=await launch(host);
  try{
    const a=sidecar.join("firstWS",first);
    await a.ready;
    a.document.getMap("notes").set("a","only first");
    await until(()=>host.snapshotRevision("firstWS")===1,"initial snapshot missing");
    await assert.rejects(sidecar.join("secondWS",first).ready,/collaboration-denied/);
    const b=sidecar.join("secondWS",second);
    await b.ready;
    assert.equal(b.document.getMap("notes").get("a"),undefined);
    b.document.getMap("notes").set("b","only second");
    await until(()=>host.snapshotRevision("secondWS")===1,"new workspace snapshot missing");
    assert.equal(a.document.getMap("notes").get("b"),undefined);
  }finally{await sidecar.close();}
});
test("reference host: ambiguous post-commit ACK is fail closed and reconciles after restart",async()=>{
  const host=new ReferenceHost();
  const writerToken=grant(host,"ambiguousWS","alice");
  const readerToken=grant(host,"ambiguousWS","bob","read");
  const first=await launch(host);
  try {
    const a=first.join("ambiguousWS",writerToken);
    const b=first.join("ambiguousWS",readerToken);
    await Promise.all([a.ready,b.ready]);
    host.faultAfterCommitOnce("ambiguousWS");
    a.document.getMap("notes").set("committed","ACK LOST");
    await until(()=>host.snapshotRevision("ambiguousWS")===1,
      "the reference store must simulate durable write before ambiguous ACK");
    await until(()=>first.app.server.hocuspocus.getConnectionsCount()===1,
      "writer must be closed instead of receiving a false commit acknowledgement");
    assert.equal(b.document.getMap("notes").get("committed"),undefined,
      "no premature broadcast after ambiguous callback result");
  }finally{await first.close();}
  const second=await launch(host);
  try {
    await assert.rejects(second.join("ambiguousWS",writerToken).ready,
      /collaboration-denied/);
    const a=second.join("ambiguousWS",host.issueCredential("ambiguousWS","alice"));
    await a.ready;
    assert.equal(a.document.getMap("notes").get("committed"),"ACK LOST",
      "reconnect must reconcile source-of-truth revision, not assume rollback");
    assert.equal(host.snapshotRevision("ambiguousWS"),1);
  }finally{await second.close();}
});

test("reference host: compare-and-swap rejects stale revisions and forbidden Yjs schema",async()=>{
  const host=new ReferenceHost();
  const token=grant(host,"casWS","alice");
  const grantContext=await host.callbacks.resolveGrant({token,workspaceId:"casWS"});
  const request={
    workspaceId:"casWS",principalId:"alice",epoch:grantContext.epoch,
    context:grantContext,expectedRevision:0,snapshot:docWithNote("item","value")
  };
  const results=await Promise.allSettled([
    host.callbacks.commitSnapshot(request),host.callbacks.commitSnapshot(request)
  ]);
  assert.deepEqual(results.map(x=>x.status).sort(),["fulfilled","rejected"]);
  assert.equal(host.snapshotRevision("casWS"),1);
  const unsafeDoc=new Y.Doc();
  unsafeDoc.getMap("runs").set("grant","must be rejected");
  const unsafe=Y.encodeStateAsUpdate(unsafeDoc);
  unsafeDoc.destroy();
  await assert.rejects(host.callbacks.commitSnapshot({
    ...request,expectedRevision:1,snapshot:unsafe
  }));
  assert.equal(host.snapshotRevision("casWS"),1);
});

test("reference host: revoked grant cannot commit after deterministic policy epoch change",async()=>{
  const host=new ReferenceHost();
  const token=grant(host,"fenceWS","alice");
  const grantContext=await host.callbacks.resolveGrant({token,workspaceId:"fenceWS"});
  host.revoke("fenceWS","alice");
  await assert.rejects(host.callbacks.commitSnapshot({
    workspaceId:"fenceWS",principalId:"alice",epoch:grantContext.epoch,
    context:grantContext,expectedRevision:0,
    snapshot:docWithNote("memo","forbidden")
  }));
  assert.equal(host.snapshotRevision("fenceWS"),0);
});

test("reference host: sanitized awareness never forwards privileged fields",async()=>{
  const host=new ReferenceHost();
  const aToken=grant(host,"awarenessWS","alice");
  const bToken=grant(host,"awarenessWS","bob","read");
  const sidecar=await launch(host);
  try {
    const a=sidecar.join("awarenessWS",aToken);
    const b=sidecar.join("awarenessWS",bToken);
    await Promise.all([a.ready,b.ready]);
    a.provider.awareness.setLocalState({
      user:{id:"admin"},secret:"CREDENTIAL-DO-NOT-FORWARD",
      token:"opaque-private",grant:{admin:true},lease:"privileged",cursor:{x:25,y:30}
    });
    let visible;
    await until(()=>{
      visible=[...b.provider.awareness.getStates().values()]
        .find(x=>x?.user?.id==="alice");
      return !!visible;
    },"sanitized presence not delivered");
    assert.deepEqual(visible,{user:{id:"alice"},cursor:{x:25,y:30}});
    assert.equal(JSON.stringify(visible).includes("CREDENTIAL"),false);
    assert.equal(JSON.stringify(visible).includes("opaque-private"),false);
  }finally{await sidecar.close();}
});

test("reference host: epoch revocation at paused commit gate prevents peer visibility",async()=>{
  let enter,release;
  const entered=new Promise(resolve=>{enter=resolve;});
  const proceed=new Promise(resolve=>{release=resolve;});
  const host=new ReferenceHost({beforeCommit:async()=>{
    enter();
    await proceed;
  }});
  const token=grant(host,"raceEpoch","alice");
  const reader=grant(host,"raceEpoch","bob","read");
  const sidecar=await launch(host);
  try {
    const a=sidecar.join("raceEpoch",token);
    const b=sidecar.join("raceEpoch",reader);
    await Promise.all([a.ready,b.ready]);
    a.document.getMap("notes").set("rejected","should not broadcast");
    await entered; // deterministic: commit now blocked inside the fixture
    assert.equal(host.snapshotRevision("raceEpoch"),0);
    assert.equal(b.document.getMap("notes").get("rejected"),undefined);
    host.revoke("raceEpoch","alice"); // atomic commit checks epoch after the barrier
    release();
    await until(()=>sidecar.app.server.hocuspocus.getConnectionsCount()===1,
      "revoked writer should be disconnected");
    assert.equal(host.snapshotRevision("raceEpoch"),0);
    assert.equal(b.document.getMap("notes").get("rejected"),undefined);
  }finally{release();await sidecar.close();}
});
