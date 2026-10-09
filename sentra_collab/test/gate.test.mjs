import test from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { createCollabServer } from "../server.mjs";
import { HocuspocusProvider } from "@hocuspocus/provider";
import * as Y from "yjs";

const pause=ms=>new Promise(r=>setTimeout(r,ms));
const fresh=()=>randomBytes(32).toString("hex");
function deferred() {
  let resolve;
  const promise=new Promise(r=>resolve=r);
  return {promise,resolve};
}
async function harness({issued=new Map(),nonces=new Set(),snapshots=new Map(),
  revisions=new Map(),revoked=new Set(),beforeCommit=async()=>{}}={}) {
  const app=createCollabServer({
    resolveGrant:async ({token})=>issued.get(token),
    consumeNonce:async ({fingerprint})=>{
      if(nonces.has(fingerprint))return false;
      nonces.add(fingerprint);return true;
    },
    checkGrant:async c=> !revoked.has(c.workspaceId+":"+c.principalId),
    loadSnapshot:async ({workspaceId})=>({
      snapshot:snapshots.get(workspaceId)??null,revision:revisions.get(workspaceId)??0
    }),
    commitSnapshot:async request=>{
      await beforeCommit(request);
      const {workspaceId,principalId,expectedRevision,snapshot}=request;
      if(revoked.has(workspaceId+":"+principalId) ||
         (revisions.get(workspaceId)??0)!==expectedRevision)throw Error("fenced");
      snapshots.set(workspaceId,snapshot);
      revisions.set(workspaceId,expectedRevision+1);
      return {revision:expectedRevision+1};
    },recheckMs:500
  });
  await app.listen();
  const clients=[];
  const issue=(workspaceId,principalId,permission="write")=>{
    const token=fresh();
    issued.set(token,{workspaceId,principalId,permission,epoch:0,expiresAt:Date.now()+30000});
    return token;
  };
  const join=(workspaceId,token)=>{
    const document=new Y.Doc();
    let ok,fail;
    const ready=new Promise((resolve,reject)=>{ok=resolve;fail=reject;});
    const provider=new HocuspocusProvider({
      url:"ws://127.0.0.1:"+app.server.httpServer.address().port,
      name:"sentra-collab:v1:"+workspaceId,token,document,
      onSynced:()=>ok(),onAuthenticationFailed:()=>fail(Error("denied"))
    });
    clients.push({provider,document});
    return {document,provider,ready};
  };
  return {app,issue,join,issued,nonces,snapshots,revisions,revoked,
    close:async()=>{
      for(const {provider,document} of clients){provider.destroy();document.destroy();}
      await app.destroy();
    }};
}
test("precommit waits for durable fenced decision BEFORE any peer visibility",async()=>{
  const entered=deferred(), release=deferred();
  const h=await harness({beforeCommit:async()=>{entered.resolve();await release.promise;}});
  try {
    const writer=h.join("blocked",h.issue("blocked","alice"));
    const peer=h.join("blocked",h.issue("blocked","bob"));
    await Promise.all([writer.ready,peer.ready]);
    writer.document.getMap("notes").set("secret","MUST_NOT_LEAK");
    await entered.promise;
    // Deterministic negative assertion: commit is currently held, not a timing guess.
    assert.equal(peer.document.getMap("notes").get("secret"),undefined);
    assert.equal(h.snapshots.has("blocked"),false);
    h.revoked.add("blocked:alice");
    release.resolve();
    for(let i=0;i<40&&h.app.server.hocuspocus.getConnectionsCount()>1;i++) await pause(30);
    assert.equal(h.app.server.hocuspocus.getConnectionsCount(),1);
    assert.equal(peer.document.getMap("notes").get("secret"),undefined);
    assert.equal(h.snapshots.has("blocked"),false);
  }finally{release.resolve();await h.close();}
});
test("nonce remains consumed after server restart; fresh token reconnects",async()=>{
  const deps={issued:new Map(),nonces:new Set(),snapshots:new Map(),revisions:new Map()};
  const first=await harness(deps);
  const used=first.issue("restart","alice");
  try {await first.join("restart",used).ready;}finally{await first.close();}
  const again=await harness(deps);
  try {
    await assert.rejects(again.join("restart",used).ready,/denied/);
    const freshToken=again.issue("restart","alice");
    await again.join("restart",freshToken).ready;
    assert.equal(again.nonces.size,2);
  }finally{await again.close();}
});
test("awareness removes secrets and impersonation fields before peer broadcast",async()=>{
  const h=await harness();
  try {
    const a=h.join("presence",h.issue("presence","alice"));
    const b=h.join("presence",h.issue("presence","bob","read"));
    await Promise.all([a.ready,b.ready]);
    a.provider.awareness.setLocalState({
      user:{id:"admin"},token:"PRIVATE_TOKEN",secret:"HIDDEN",grant:{scope:"admin"},
      cursor:{x:10,y:20}
    });
    let state;
    for(let i=0;i<40;i++){
      state=[...b.provider.awareness.getStates().values()].find(v=>v?.user?.id==="alice");
      if(state)break;
      await pause(30);
    }
    assert.ok(state,"peer should see sanitized presence");
    assert.deepEqual(state.user,{id:"alice"});
    assert.deepEqual(state.cursor,{x:10,y:20});
    assert.equal(JSON.stringify(state).includes("PRIVATE_TOKEN"),false);
    assert.equal(JSON.stringify(state).includes("HIDDEN"),false);
    assert.equal("grant" in state,false);
  }finally{await h.close();}
});
test("explicit workspace switch requires new scoped token",async()=>{
  const h=await harness();
  try {
    const token=h.issue("firstWs","alice");
    const first=h.join("firstWs",token);
    await first.ready;
    first.provider.destroy();first.document.destroy();
    await assert.rejects(h.join("secondWs",token).ready,/denied/);
    const next=h.join("secondWs",h.issue("secondWs","alice"));
    await next.ready;
    next.document.getMap("notes").set("workspace","second only");
    for(let i=0;i<30&&!h.snapshots.has("secondWs");i++) await pause(30);
    assert.ok(h.snapshots.has("secondWs"));
    assert.equal(h.snapshots.has("firstWs"),false);
  }finally{await h.close();}
});
test("concurrent writers serialize fenced precommits before broadcast",async()=>{
  const entered=deferred(),release=deferred();
  let commits=0;
  const h=await harness({beforeCommit:async()=>{
    commits++;
    if(commits===1){entered.resolve();await release.promise;}
  }});
  try {
    const a=h.join("serialize",h.issue("serialize","alice"));
    const b=h.join("serialize",h.issue("serialize","bob"));
    await Promise.all([a.ready,b.ready]);
    a.document.getMap("notes").set("a","first");
    await entered.promise;
    b.document.getMap("notes").set("b","second");
    assert.equal(commits,1);
    assert.equal(b.document.getMap("notes").get("a"),undefined);
    release.resolve();
    for(let i=0;i<40 && h.revisions.get("serialize")!==2;i++) await pause(30);
    assert.equal(h.revisions.get("serialize"),2);
    assert.equal(commits,2);
    const stored=new Y.Doc();
    for(const name of ["layout","nodes","notes"])stored.getMap(name);
    Y.applyUpdate(stored,h.snapshots.get("serialize"));
    assert.equal(stored.getMap("notes").get("a"),"first");
    assert.equal(stored.getMap("notes").get("b"),"second");
    stored.destroy();
  }finally{release.resolve();await h.close();}
});
