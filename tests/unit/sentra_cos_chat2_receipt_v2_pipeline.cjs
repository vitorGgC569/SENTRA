/* Hermetic MV3 production source + committed React + REAL relay HTTP.
 * No Edge account, cookies, tokens from browser, or Web send is performed.
 * Only a synthetic post-click receipt from the already leased job is tested. */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const config = JSON.parse(process.argv[2] || "{}");
const supported = new Set(["valid","approval","missing_metadata","wrong_message","wrong_epoch","downgrade","wrong_document","unknown_profile","no_sending","wrong_worker","uncertain_ack","bad_phase_ack","multi_tab_logout","reload","untracked_logout","wrong_source_sha"]);
assert(supported.has(config.scenario));
const root = path.resolve(__dirname, "../..");
const sw = fs.readFileSync(path.join(root,"edge_extension/service-worker.js"),"utf8");
const reader=fs.readFileSync(path.join(root,"edge_extension/conversation-evidence.js"),"utf8");
const manifest=JSON.parse(fs.readFileSync(path.join(root,"edge_extension/manifest.json"),"utf8"));
const start=sw.indexOf("// SENTRA_IDENTITY_REVOCATION_BEGIN");
const end=sw.indexOf("// SENTRA_IDENTITY_REVOCATION_END");
const receiptStart=sw.indexOf("async function omaRecordDeliveryReceipt(");
const receiptEnd=sw.indexOf("// Budgets MV3",receiptStart);
const phaseStart=sw.indexOf("async function omaProgressPhase(");
const phaseEnd=sw.indexOf("// Renova o lease",phaseStart);
assert(start>0 && end>start && receiptStart>end && receiptEnd>receiptStart && phaseStart>0 && phaseEnd>phaseStart);
const production=sw.slice(start,end)+"\n"+sw.slice(receiptStart,receiptEnd)+"\n"+sw.slice(phaseStart,phaseEnd);
const trace=[];
let generated=0;
const rand=()=> "identity-"+(++generated).toString().padStart(12,"0");
const originalURL="https://chatgpt.com/c/target-chat-123";
const tab={id:337,url:originalURL};
const ownerJob=config.job;
const record={
  job_id:ownerJob.job_id,worker:"TAB-337",lease_token:ownerJob.lease_token,
  sent:false
};
const store={};
const chrome={
  storage:{local:{
    async get(keys){
      if(keys===null)return {...store};
      const names=typeof keys==="string"?[keys]:Array.isArray(keys)?keys:Object.keys(keys);
      return Object.fromEntries(names.filter(key=>Object.hasOwn(store,key)).map(key=>[key,store[key]]));
    },
    async set(items){Object.assign(store,items);},
    async remove(keys){for(const k of (typeof keys==="string"?[keys]:keys))delete store[k];}
  }},
  tabs:{get:async()=>tab,query:async()=>[tab]},
  scripting:{executeScript:async(arg)=>{
    if(arg.files)return [{frameId:0,result:null}];
    if(arg.args)return [{frameId:0,result:page.__sentraConversationEvidence.observe(arg.args[0])}];
    return [{frameId:0,result:page.__sentraConversationEvidence.documentId}];
  }}
};
const message={id:"message-33777",metadata:
  config.scenario==="missing_metadata"?{}:{request_id:"request-metadata-12345"}};
const reactRoot={tag:3,return:null,child:null,memoizedProps:{}};
reactRoot.stateNode={current:reactRoot};
const reactMessage={tag:5,return:reactRoot,memoizedProps:{
  conversationId:"target-chat-123",messages:[message]}};
reactRoot.child=reactMessage;
const anchor={"__reactFiber$test":reactMessage};
const page={
  crypto:{randomUUID:rand},
  location:{origin:"https://chatgpt.com",pathname:"/c/target-chat-123"},
  document:{
    querySelectorAll:()=>[anchor],
    querySelector:sel=>{
      if(config.scenario==="approval" && sel.includes("approval"))return {};
      if(sel.includes("composer-input"))return {};
      return null;
    }
  }
};
page.globalThis=page;
vm.runInNewContext(reader,page,{timeout:1000});
async function relay(route, options){
  const data=JSON.parse(options.body);
  if(route==="/jobs/delivery-receipt") {
    if(config.scenario==="wrong_epoch" && "identity_epoch" in data) data.identity_epoch="wrong-epoch-12345";
    if(config.scenario==="downgrade" && "identity_epoch" in data) delete data.identity_epoch;
    if(config.scenario==="wrong_document" && "document_id" in data) data.document_id="wrong-document-1234";
    if(config.scenario==="wrong_source_sha" && "source_sha256" in data) data.source_sha256="0".repeat(64);
    trace.push({route,keys:Object.keys(data).sort(),v2:"identity_epoch" in data});
  } else trace.push({route});
  const response=await fetch(config.url+route,{
    method:"POST",headers:{"Content-Type":"application/json",
      "Origin":"chrome-extension://"+"a".repeat(32),
      "Authorization":"Bearer "+config.token},body:JSON.stringify(data)});
  const json=await response.json();
  if(!response.ok)throw Error("HTTP_"+response.status);
  if (config.scenario==="uncertain_ack" && route==="/jobs/delivery-receipt")
    throw Error("NETWORK_AFTER_POST");
  if (config.scenario==="bad_phase_ack" && route==="/jobs/progress")
    return {ok:false};
  return json;
}
const ctx={
  crypto:{randomUUID:rand},URL,chrome,
  OMA_SOURCE_HASH:manifest.sentra_source_hash,
  omaEvidenceBusy:new Set(),omaOwnedTabIds:async()=>new Set([337,338]),
  omaJobProvider:()=> "chatgpt",omaLoadActive:async()=>record,
  omaRelay:relay,
};
vm.createContext(ctx);
vm.runInContext(production,ctx,{timeout:2500});
(async()=>{
  const identity={job_id:record.job_id,worker:record.worker,lease_token:record.lease_token};
  if(config.scenario==="wrong_worker")record.worker="TAB-998";
  let phase=false;
  if(config.scenario!=="no_sending") {
    phase=await ctx.omaProgressPhase(337,identity,"sending");
    assert.equal(phase,config.scenario!=="bad_phase_ack");
  }
  if(config.scenario==="unknown_profile") {
    await ctx.omaObserveConversation(337);
    await ctx.omaIdInvalidate(337,"profile_changed");
  }
  if(config.scenario==="multi_tab_logout") {
    await ctx.omaObserveConversation(337);
    await ctx.omaObserveConversation(338);
    await ctx.omaIdOnTabUpdated(338,{url:"https://chatgpt.com/auth/login"});
    assert(store.sentra_id_profile_poison,"profile poison must be persistent");
    assert.equal(store.sentra_id_doc_337,undefined);
    assert.equal(store.sentra_id_doc_338,undefined);
    assert.equal(await ctx.omaIdPrepare(339,"doc-new-tab-12345","target-chat-123"),null);
  }
  if(config.scenario==="reload") {
    await ctx.omaObserveConversation(337);
    await ctx.omaIdOnTabUpdated(337,{status:"loading"});
    assert.equal(store.sentra_id_doc_337,undefined);
  }
  if(config.scenario==="untracked_logout") {
    await ctx.omaObserveConversation(337);
    assert.equal(store.sentra_id_doc_338,undefined);
    await ctx.omaIdOnTabUpdated(338,{url:"https://chatgpt.com/auth/login"});
    assert.equal(store.sentra_id_doc_337,undefined);
    assert.ok(store.sentra_id_profile_poison);
    assert.equal(await ctx.omaIdPrepare(339,"doc-untracked123","target-chat-123"),null);
  }
  const sent={result:{images_attached:0,delivery_receipt:{
    conversation_id:"target-chat-123",
    message_id:config.scenario==="wrong_message"?"message-other98765":"message-33777",
    prompt_sha256:ownerJob.prompt_sha256
  }}};
  let response=null,error=null;
  try {response=await ctx.omaRecordDeliveryReceipt(identity,ownerJob,sent,phase);}
  catch(exc){error=String(exc.message||exc);}
  let duplicate=null;
  if (["valid","uncertain_ack"].includes(config.scenario)) {
    // A fresh MV3 JS global environment with the same persisted local storage:
    // service-worker restart MUST NOT resend a previously emitted receipt.
    const restarted={
      ...ctx,omaEvidenceBusy:new Set(),OMA_ID_RECEIPT_BUSY:undefined
    };
    vm.createContext(restarted);
    vm.runInContext(production,restarted,{timeout:2500});
    duplicate=await restarted.omaRecordDeliveryReceipt(identity,ownerJob,sent,phase);
    assert.equal(duplicate.state,"uncertain","MV3 restart/ACK loss replay blocked");
    assert.equal(trace.filter(item=>item.route==="/jobs/delivery-receipt").length,1);
  }
  console.log("SENTRA_RECEIPT_V2="+JSON.stringify({
    scenario:config.scenario, receiptState:response?.state||null,error,
    duplicateState:duplicate?.state||null,
    profilePoison:!!store.sentra_id_profile_poison,
    v2Count:trace.filter(item=>item.route==="/jobs/delivery-receipt"&&item.v2).length,
    preliminaryCount:trace.filter(item=>item.route==="/jobs/delivery-receipt"&&!item.v2).length,
    observedCount:trace.filter(item=>item.route==="/browser-evidence/observe").length,
    phaseCount:trace.filter(item=>item.route==="/jobs/progress").length,
    requestId:message.metadata?.request_id||null,
    documentId:store.sentra_id_doc_337?.document_id||null,
    routes:trace
  }));
})().catch(err=>{console.error(err.stack);process.exitCode=1;});
