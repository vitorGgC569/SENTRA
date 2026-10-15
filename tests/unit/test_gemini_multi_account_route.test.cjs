const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const sw=fs.readFileSync(path.join(root,'edge_extension/service-worker.js'),'utf8');
const cs=fs.readFileSync(path.join(root,'edge_extension/content-script.js'),'utf8');
function extract(source, start, end){
  const a=source.indexOf(start),b=source.indexOf(end,a+start.length);
  assert.ok(a>=0 && b>a,'missing function '+start);
  return source.slice(a,b);
}
test('Gemini home preserves /u/N/ account context for NEW_CHAT',()=>{
 const helper=extract(cs,'function omaHomeUrl() {','\nasync function omaWaitForComposer');
 for(const [pathname,search,expected] of [
  ['/u/7/app','?pageId=123','https://gemini.google.com/u/7/app'],
  ['/u/7/app/conv-123','', 'https://gemini.google.com/u/7/app'],
  ['/app','?authuser=7','https://gemini.google.com/app?authuser=7'],
  ['/app','', 'https://gemini.google.com/app']]){
  const context={window:{location:{pathname,search}},omaProvider:()=> 'gemini',URLSearchParams};
  vm.runInNewContext(helper,context);
  assert.equal(vm.runInNewContext('omaHomeUrl()',context),expected);
 }
});
test('Conversation ids recognize scoped and unscoped Gemini URLs',()=>{
 const content=extract(cs,'function omaConversationId() {','\nfunction omaGeminiModelLabel');
 const worker=extract(sw,'function omaConversationIdFromUrl(value, provider) {','\nfunction omaConversationKey');
 for(const url of ['https://gemini.google.com/u/7/app/chat123','https://gemini.google.com/app/chat123']){
  const u=new URL(url);
  const c={window:{location:{pathname:u.pathname}},omaProvider:()=> 'gemini'};
  vm.runInNewContext(content,c);
  assert.equal(vm.runInNewContext('omaConversationId()',c),'chat123');
  const s={};
  vm.runInNewContext(worker,s);
  assert.equal(vm.runInNewContext('omaConversationIdFromUrl('+JSON.stringify(url)+', "gemini")',s),'chat123');
 }
});
test('A new Gemini review opens fresh within the existing account',async()=>{
 const source=extract(sw,'async function omaOpenFreshControllerChat(tabId, job) {','\nasync function omaApplyRequestedModel');
 const navigations=[];
 const c={
  chrome:{tabs:{get:async()=>({url:'https://gemini.google.com/u/7/app?pageId=7'}),
    update:async(_,opts)=>{navigations.push(opts.url)},reload:async()=>{throw Error('unexpected retry')}}},
  omaJobProvider:()=> 'gemini',
  omaProviderHome:()=> 'https://gemini.google.com/app',
  omaProjectTargetUrl:()=>null,
  omaWaitTabDeparted:async()=>{},
  omaWaitTabComplete:async()=>{},
  omaWaitTabReady:async()=>{},
  omaEnsureFreshScript:async()=>{},
  omaSendToTab:async()=>({result:{is_fresh_chat:true,provider:'gemini'}}),
  URL
 };
 vm.runInNewContext(source,c);
 await c.omaOpenFreshControllerChat(123,{provider:'gemini',new_chat:true});
 assert.deepEqual(navigations,['https://gemini.google.com/u/7/app']);
});
