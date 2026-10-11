/* Real HTTP loopback with real SENTRA MV3 observe+invalidation functions.
 * Node/vm is a hermetic test harness; NEVER product Code Mode or live ChatGPT.
 * No credentials, cookies or text of real chats are accessed. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "../../");
const workerSource = fs.readFileSync(path.join(root,"edge_extension/service-worker.js"),"utf8");
const readerSource = fs.readFileSync(path.join(root,"edge_extension/conversation-evidence.js"),"utf8");
const manifest = JSON.parse(fs.readFileSync(path.join(root,"edge_extension/manifest.json"),"utf8"));
const start = workerSource.indexOf("// SENTRA_IDENTITY_REVOCATION_BEGIN");
const end = workerSource.indexOf("// SENTRA_IDENTITY_REVOCATION_END");
const a = workerSource.indexOf("async function omaObserveConversation(tabId, expected = null)");
const b = workerSource.indexOf("// Budgets MV3",a);
assert.ok(start > 0 && end > start && a > end && b > a);
const script = workerSource.slice(start,end) + "\n" + workerSource.slice(a,b);
const port = Number(process.argv[2]);
assert.ok(port > 0 && port <= 65535);
const endpoint = "http://127.0.0.1:" + port;
const id = "a".repeat(32);
const store = Object.create(null);
const page = {};
let url = "https://chatgpt.com/c/conversation12345";
let approval = false;
let online = true;
let raceInvalidate = false;
let swRef = null;
let held = null;
let calls = [];
let index = 0;
let tab = {id:77, get url(){return url;}};
const dataStore = {
  async get(keys) {
    if (keys === null) return {...store};
    const names=typeof keys==="string" ? [keys] : keys;
    return Object.fromEntries(names.filter(k=>Object.hasOwn(store,k)).map(k=>[k,store[k]]));
  },
  async set(values) {Object.assign(store,values);},
  async remove(keys) {
    for(const k of typeof keys==="string" ? [keys] : keys) delete store[k];
  }
};
const owner="local-operator";
const msg={id:"message-abcdef123",metadata:{request_id:"request-abcdef123"}};
const rootFiber={tag:3, child:null, return:null, memoizedProps:{}};
rootFiber.stateNode={current:rootFiber};
const child={tag:5,return:rootFiber,memoizedProps:{
  conversationId:"conversation12345",messages:[msg]
}};
rootFiber.child=child;
const anchor={"__reactFiber$test":child};
const pageCtx={
  crypto:{randomUUID:()=> "document-" + (++index).toString().padStart(12,"0")},
  location:{origin:"https://chatgpt.com",pathname:"/c/conversation12345"},
  document:{
    querySelectorAll:()=>[anchor],
    querySelector:(sel)=>sel.includes("connector-approval") && approval ? {} :
      sel.includes("composer-input") ? {} : null
  }
};
pageCtx.globalThis=pageCtx;
vm.runInNewContext(readerSource,pageCtx,{timeout:1000});
async function bridgeRelay(target,options) {
  calls.push(target);
  if(!online) throw Error("network offline");
  const response=await fetch(endpoint+target,{
    method:options.method||"GET",body:options.body,
    headers:{"Content-Type":"application/json",
      "Origin":"chrome-extension://"+id,
      "Authorization":"Bearer fixture-loopback-only"}
  });
  if(!response.ok) throw Error("HTTP "+response.status);
  return response.json();
}
function makeVm() {
  const ctx={
    crypto:{randomUUID:()=> "epoch-"+(++index).toString().padStart(12,"0")},
    OMA_SOURCE_HASH:manifest.sentra_source_hash,
    omaEvidenceBusy:new Set(),
    omaRelay:bridgeRelay,
    omaOwnedTabIds:async()=>new Set([77]),
    chrome:{
      storage:{local:dataStore},
      tabs:{get:async()=>tab,query:async()=>[tab]},
      scripting:{executeScript:async(args)=>{
        if(args.files) return [{frameId:0,result:null}];
        if(args.args) {
          const observed = pageCtx.__sentraConversationEvidence.observe(args.args[0]);
          if (raceInvalidate && swRef) {
            raceInvalidate = false;
            // Chrome navigation runs during an awaited MAIN-world scan.
            // The pending invalidation MUST prohibit its delayed POST.
            await swRef.omaIdInvalidate(77,"identity_unknown");
          }
          return [{frameId:0,result:observed}];
        }
        return [{frameId:0,result:pageCtx.__sentraConversationEvidence.documentId}];
      }}
    },
    URL
  };
  vm.createContext(ctx);
  vm.runInContext(script,ctx,{timeout:2000});
  return ctx;
}
(async()=>{
  let sw=makeVm();
  await sw.omaObserveConversation(77);
  const proof=store.sentra_id_doc_77;
  assert.ok(proof?.observed === true,"HTTP challenge/observe not delivered");
  assert.equal(proof.document_id,pageCtx.__sentraConversationEvidence.documentId);
  assert.deepEqual(calls.slice(0,2),[
    "/browser-evidence/challenge","/browser-evidence/observe"]);
  const first=proof.identity_epoch;
  // Approval is a page hint to DENY, never a human-authorized grant.
  approval=true;
  await sw.omaObserveConversation(77);
  // Fail closed on unknown/redirect: notification queued without HTTPS/relay.
  online=false;
  url="https://chatgpt.com/auth/login";
  await sw.omaIdOnTabUpdated(77,{url},{id:77});
  const notice=store.sentra_id_revoke_77;
  assert.equal(notice.reason,"signed_out");
  assert.equal(notice.identity_epoch,first);
  assert.equal(store.sentra_id_doc_77,undefined);
  assert.equal(await sw.omaIdPrepare(77,"document-next12345","conversation12345"),null);
  // Recreate worker globals, same persistent Chrome storage, then ACK.
  sw=makeVm();
  online=true;
  await sw.omaIdFlushInvalidations();
  assert.equal(store.sentra_id_revoke_77,undefined);
  // Re-entering a chat after the redirect rotates the MAIN-world document,
  // but does not prove recovery of the account. Simulate navigation while
  // the second scan is awaiting Chrome.scripting.
  url="https://chatgpt.com/c/conversation12345";
  pageCtx.location.pathname="/auth/login";
  void pageCtx.__sentraConversationEvidence.documentId;
  pageCtx.location.pathname="/c/conversation12345";
  const beforeObserve=calls.filter(k=>k==="/browser-evidence/observe").length;
  swRef=sw;
  raceInvalidate=true;
  await sw.omaObserveConversation(77);
  assert.equal(calls.filter(k=>k==="/browser-evidence/observe").length,beforeObserve);
  assert.equal(store.sentra_id_doc_77,undefined);
  assert.equal(store.sentra_id_revoke_77,undefined,
    "host confirmed revocation of the in-flight challenged document");
  // Body is exact and truly transported over HTTP to Python SQLite.
  console.log("SENTRA_MV3_HTTP="+JSON.stringify({
    document_id:proof.document_id,identity_epoch:first,
    worker:"TAB-77",message_id:msg.id,request_id:msg.metadata.request_id,
    notice,challenge:true,observed:true,recovered:true,
    paths:calls
  }));
})().catch(e=>{console.error(String(e.stack||e));process.exitCode=1;});
