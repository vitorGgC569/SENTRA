import test from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import * as Y from "yjs";
import { HocuspocusProvider } from "@hocuspocus/provider";
import { AccessGate, validateCanvasState, validateYDocument, sanitizeAwareness } from "../policy.mjs";
import { createCollabServer } from "../server.mjs";

const docname = ws => "sentra-collab:v1:" + ws;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function fixture(options={}) {
  const issued = options.issued ?? new Map();
  const revoked = options.revoked ?? new Set();
  const snapshots = options.snapshots ?? new Map();
  const revisions = options.revisions ?? new Map();
  const nonces = options.nonces ?? new Set();
  const issue = (ws, principal, permission="write") => {
    const token = randomBytes(32).toString("hex");
    issued.set(token,{workspaceId:ws, principalId:principal, permission,
      expiresAt:Date.now()+60000,epoch:0});
    return token;
  };
  const app = createCollabServer({
    resolveGrant: async ({token}) => issued.get(token),
    checkGrant: async grant => !revoked.has(grant.workspaceId+":"+grant.principalId),
    consumeNonce: async ({fingerprint}) => {
      if (nonces.has(fingerprint)) return false;
      nonces.add(fingerprint); return true;
    },
    loadSnapshot: async ({workspaceId}) => ({
      snapshot:snapshots.get(workspaceId) ?? null,revision:revisions.get(workspaceId) ?? 0
    }),
    commitSnapshot: async request => {
      if (options.beforeCommit) await options.beforeCommit(request);
      const {workspaceId,principalId,expectedRevision,snapshot}=request;
      if (revoked.has(workspaceId+":"+principalId) ||
          (revisions.get(workspaceId) ?? 0) !== expectedRevision) throw Error("fence-denied");
      snapshots.set(workspaceId,snapshot);
      revisions.set(workspaceId,expectedRevision+1);
      return {revision:expectedRevision+1};
    },
    recheckMs: 500
  });
  await app.listen();
  const url = "ws://127.0.0.1:" + app.server.httpServer.address().port;
  const created = [];
  const client = (ws, token, options={}) => {
    const document = new Y.Doc();
    let yes,no;
    const ready = new Promise((resolve,reject)=>{yes=resolve;no=reject;});
    const timeout = setTimeout(()=>no(Error("handshake-timeout")),4000);
    const state = { disconnects: 0 };
    const provider = new HocuspocusProvider({
      url,name:docname(ws),document,token,
      onDisconnect: () => { state.disconnects++; },
      onAuthenticated:()=>{},
      onSynced:()=>{clearTimeout(timeout);yes(true);},
      onAuthenticationFailed:()=>{clearTimeout(timeout);no(Error("collaboration-denied"));}
    });
    created.push({provider,document});
    return {provider,document,ready,state};
  };
  return {app,issued,revoked,snapshots,revisions,nonces,issue,client,
    async close() {
      for (const {provider,document} of created) {provider.destroy();document.destroy();}
      await app.destroy();
    }
  };
}
test("policy is deny by default and forbids runtime keys",async()=>{
  assert.throws(()=>new AccessGate());
  assert.throws(()=>validateCanvasState({layout:{},notes:{},nodes:{},operations:{}}));
  assert.throws(()=>validateCanvasState({layout:{},nodes:{},notes:{n1:{grant:"danger"}}}));
  const doc = new Y.Doc();
  doc.getMap("runs").set("id",{state:"SUCCEEDED"});
  assert.throws(()=>validateYDocument(doc,Y));
  doc.destroy();
});
test("identity binding for awareness prevents another client spoof",()=>{
  const claim = {};
  const ctx = {principalId:"friend"};
  const values = new Map([[123,{user:{id:"admin"},cursor:{x:10,y:15}}]]);
  sanitizeAwareness(values,ctx,claim);
  assert.equal(values.get(123).user.id,"friend");
  assert.deepEqual(Object.keys(values.get(123)).sort(),["cursor","user"]);
  assert.throws(()=>sanitizeAwareness(new Map([[999,{cursor:{x:1,y:1}}]]),ctx,claim));
  assert.throws(()=>sanitizeAwareness(new Map([[123,{cursor:{x:NaN,y:1}}]]),ctx,claim));
  assert.throws(()=>sanitizeAwareness(new Map([
    [123,{cursor:{x:1,y:2}}], [999,{cursor:{x:3,y:4}}]
  ]),ctx,claim),/collaboration-denied/);
  const unauthorizedRemoval = new Map([[999,null]]);
  sanitizeAwareness(unauthorizedRemoval,ctx,claim);
  assert.equal(unauthorizedRemoval.size,0,"cannot remove another client's presence");
  const secrets = new Map([[123,{user:{id:"admin"},secret:"PRIVATE",token:"PRIVATE",grant:{write:true},cursor:{x:1,y:2}}]]);
  sanitizeAwareness(secrets,ctx,claim);
  assert.deepEqual(secrets.get(123),{user:{id:"friend"},cursor:{x:1,y:2}});
});
test("WebSocket rejects unauthenticated, cross-workspace and replay",async()=>{
  const f=await fixture();
  try {
    const valid=f.issue("workspaceA","alice");
    await assert.rejects(f.client("workspaceB",valid).ready);
    await assert.rejects(f.client("workspaceA","not-a-grant").ready);
    const first=f.client("workspaceA",valid);
    await first.ready;
    await assert.rejects(f.client("workspaceA",valid).ready);
    const concurrent=f.issue("workspaceB","racer");
    const results=await Promise.allSettled([
      f.client("workspaceB",concurrent).ready,
      f.client("workspaceB",concurrent).ready,
    ]);
    assert.deepEqual(results.map(r=>r.status).sort(),["fulfilled","rejected"]);
  } finally { await f.close(); }
});
test("two clients sync Yjs display state and workspace remains isolated",async()=>{
  const f=await fixture();
  try {
    const a=f.client("workspaceA",f.issue("workspaceA","alice"));
    const b=f.client("workspaceA",f.issue("workspaceA","bob"));
    const c=f.client("workspaceB",f.issue("workspaceB","alice"));
    await Promise.all([a.ready,b.ready,c.ready]);
    a.document.getMap("nodes").set("node1",{x:10,y:20,width:350,height:220});
    a.document.getMap("notes").set("note1","shared");
    for(let i=0;i<30 && b.document.getMap("notes").get("note1")!=="shared";i++) await delay(50);
    assert.equal(b.document.getMap("notes").get("note1"),"shared");
    assert.equal(c.document.getMap("notes").get("note1"),undefined);
  } finally { await f.close(); }
});
test("revoke active user and prohibit sending runtime updates",async()=>{
  const f=await fixture();
  try {
    const writer=f.client("workspaceA",f.issue("workspaceA","alice"));
    const observer=f.client("workspaceA",f.issue("workspaceA","bob"));
    await Promise.all([writer.ready,observer.ready]);
    // First, revoke a healthy, authenticated session (not a preblocked client).
    writer.document.getMap("notes").set("shared","authorized");
    for(let i=0;i<30 && observer.document.getMap("notes").get("shared")!=="authorized";i++) await delay(30);
    assert.equal(observer.document.getMap("notes").get("shared"),"authorized");
    f.revoked.add("workspaceA:alice");
    for(let i=0;i<30 && f.app.server.hocuspocus.getConnectionsCount()!==1;i++) await delay(100);
    assert.equal(f.app.server.hocuspocus.getConnectionsCount(),1,
      "server must disconnect revoked writer without disconnecting authorized observer");
    writer.document.getMap("notes").set("n1","revoked");
    await delay(150);
    assert.equal(observer.document.getMap("notes").get("n1"),undefined);
    // Separately exercise forbidden root operations without revocation.
    const attacker=f.client("workspaceB",f.issue("workspaceB","alice"));
    const watcher=f.client("workspaceB",f.issue("workspaceB","bob"));
    await Promise.all([attacker.ready,watcher.ready]);
    attacker.document.getMap("operations").set("op1",{state:"SUCCEEDED"});
    await delay(250);
    assert.equal(watcher.document.share.has("operations"),false);
  } finally { await f.close(); }
});
test("reconnection with new grant converges without duplicated entries",async()=>{
  const f=await fixture();
  try {
    const first=f.client("workspaceA",f.issue("workspaceA","alice"));
    await first.ready;
    first.document.getMap("notes").set("memo","before disconnect");
    for(let i=0;i<30 && !f.snapshots.has("workspaceA");i++) await delay(30);
    assert.ok(f.snapshots.has("workspaceA"),"authorized edit must reach persistence");
    first.provider.destroy();
    first.document.destroy();
    for(let i=0;i<30 && f.app.server.hocuspocus.getConnectionsCount()>0;i++) await delay(30);
    assert.equal(f.app.server.hocuspocus.getConnectionsCount(),0);
    const again=f.client("workspaceA",f.issue("workspaceA","alice"));
    await again.ready;
    for(let i=0;i<30 && again.document.getMap("notes").get("memo")===undefined;i++) await delay(50);
    assert.equal(again.document.getMap("notes").get("memo"),"before disconnect");
    assert.equal(again.document.getMap("notes").size,1);
  } finally { await f.close(); }
});
test("read-only websocket synchronizes but cannot publish changes", async () => {
  const f = await fixture();
  try {
    const writer = f.client("readOnlyWs", f.issue("readOnlyWs","editor"));
    const reader = f.client("readOnlyWs", f.issue("readOnlyWs","viewer","read"));
    await Promise.all([writer.ready,reader.ready]);
    writer.document.getMap("notes").set("hello","visible");
    for (let i=0; i<30 && reader.document.getMap("notes").get("hello")!=="visible"; i++) await delay(30);
    assert.equal(reader.document.getMap("notes").get("hello"),"visible");
    reader.document.getMap("notes").set("blocked","cannot publish");
    await delay(200);
    assert.equal(writer.document.getMap("notes").get("blocked"),undefined);
  } finally { await f.close(); }
});

test("display-only allowlist excludes Run, Operation, Grant, Lease", () => {
  for (const field of ["runs","operations","grants","leases","policy"]) {
    const doc = new Y.Doc();
    doc.getMap(field).set("item",{allowed:true});
    assert.throws(() => validateYDocument(doc,Y), /collaboration-denied/);
    doc.destroy();
    assert.throws(() => validateCanvasState({
      layout:{}, nodes:{}, notes:{}, [field]:{item:{allowed:true}}
    }), /collaboration-denied/);
  }
});
test("quotas reject oversize state and multi-map updates", async () => {
  const node = {x:1,y:1,width:300,height:200};
  const many = Object.fromEntries(Array.from({length:513},(_,i)=>["n"+i,node]));
  assert.throws(() => validateCanvasState({layout:{},nodes:many,notes:{}}));
  assert.throws(() => validateCanvasState({
    layout:{},nodes:{},notes:{tooLong:"z".repeat(12001)}
  }));
  const f = await fixture();
  try {
    const a=f.client("quotaWs",f.issue("quotaWs","writer"));
    const b=f.client("quotaWs",f.issue("quotaWs","observer"));
    await Promise.all([a.ready,b.ready]);
    a.document.getMap("notes").set("huge","z".repeat(12001));
    await delay(100);
    assert.equal(b.document.getMap("notes").get("huge"),undefined);
    // Each note is individually valid, but the single binary update exceeds 64 KiB.
    const c=f.client("quota2",f.issue("quota2","writer"));
    const e=f.client("quota2",f.issue("quota2","observer"));
    await Promise.all([c.ready,e.ready]);
    c.document.transact(() => {
      for (let i=0; i<7; i++) c.document.getMap("notes").set("n"+i,"x".repeat(11000));
    });
    await delay(150);
    assert.equal(e.document.getMap("notes").get("n0"),undefined);
  } finally { await f.close(); }
});

test("revocation between update and persistence prevents durable snapshot", async () => {
  const f=await fixture();
  try {
    const writer=f.client("preStoreWs",f.issue("preStoreWs","alice"));
    await writer.ready;
    writer.document.getMap("notes").set("pending","not durable");
    f.revoked.add("preStoreWs:alice");
    f.app.server.hocuspocus.flushPendingStores();
    await delay(250);
    assert.equal(f.snapshots.has("preStoreWs"),false);
  } finally { await f.close(); }
});
test("opt-in browser adapter honors readonly scope and allows viewer presence", async () => {
  const {readFileSync} = await import("node:fs");
  const {runInNewContext} = await import("node:vm");
  class FakeProvider {
    constructor(configuration) {
      this.configuration = configuration;
      this.awareness = {on(){}, getStates(){return new Map()},
        setLocalState(value){this.presence = value;}};
      FakeProvider.latest = this;
    }
    destroy() {this.destroyed = true;}
  }
  const sandbox = {};
  const code = readFileSync(new URL("../../sentra_canvas/static/sentra-collab.js",
    import.meta.url),"utf8");
  runInNewContext(code,sandbox);
  const api = sandbox.SentraCollab.connect({
    workspaceId:"workspaceA",url:"ws://127.0.0.1:11223",getToken:async()=> "x".repeat(32),
    Y,HocuspocusProvider:FakeProvider
  });
  assert.throws(()=>api.setNote("memo","before authorization"));
  const provider=FakeProvider.latest;
  provider.configuration.onAuthenticated({scope:"readonly"});
  provider.configuration.onSynced({state:true});
  assert.equal(api.status().writable,false);
  assert.throws(()=>api.setNode("n",{x:0,y:0,width:300,height:200}));
  api.setPresence({cursor:{x:1,y:2}});
  assert.equal(provider.awareness.presence.cursor.x,1);
  provider.configuration.onDisconnect();
  assert.throws(()=>api.setPresence({cursor:{x:1,y:2}}));
  api.disconnect();
  assert.equal(provider.destroyed,true);
});
test("Run, Grant and Lease updates never reach peers or persistence over WS", async () => {
  const f=await fixture();
  try {
    for (const field of ["runs","grants","leases"]) {
      const workspaceId="deny"+field;
      const a=f.client(workspaceId,f.issue(workspaceId,"alice"));
      const b=f.client(workspaceId,f.issue(workspaceId,"bob"));
      await Promise.all([a.ready,b.ready]);
      a.document.getMap(field).set("forbidden",{state:"approved"});
      await delay(180);
      assert.equal(b.document.share.has(field),false,field+" leaked to peer");
      assert.equal(f.snapshots.has(workspaceId),false,field+" was persisted");
    }
  } finally { await f.close(); }
});
