import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {TerminalReadBudget} from '../../../integrations/orca-terminal/src/consumer-flow.mjs';
import {TerminalInputQueue} from '../../../integrations/orca-terminal/src/input-queue.mjs';
import {TerminalInputJournal,deliveredInput} from '../src/terminal-input-journal.js';
import {createHash,webcrypto} from 'node:crypto';
import {testLocks} from './lock-harness.mjs';
import {restoreCheckpoint,mayWriteTerminal,writeTerminalFrame,releaseDisposedWrites} from '../src/terminal-checkpoint.js';
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('read budget counts in-flight work, serves FIFO and ignores an old release callback',async()=>{
 const budget=new TerminalReadBudget({slots:1,maxWaiting:2});
 const first=await budget.acquire('a');const order=[];
 const second=budget.acquire('b').then(release=>{order.push('b');return release});
 const third=budget.acquire('c').then(release=>{order.push('c');return release});
 await assert.rejects(budget.acquire('overflow'),/exhausted/);
 await assert.rejects(budget.acquire('a'),/already/);
 first();const b=await second;first();assert.equal(budget.status().active,1);
 b();const c=await third;assert.deepEqual(order,['b','c']);c();assert.equal(budget.status().active,0);
});
test('a detached queued viewer never receives the replacement viewer credit',async()=>{
 const budget=new TerminalReadBudget({slots:1});const release=await budget.acquire('busy');
 const controller=new AbortController(),waiting=budget.acquire('view',controller.signal);
 controller.abort();await assert.rejects(waiting,/detached/);
 const replacement=budget.acquire('view');release();(await replacement)();
 assert.deepEqual(budget.status(),{active:0,waiting:0,slots:1,maxWaiting:128});
});
test('an old release cannot debit a replacement read with the same consumer identity',async()=>{
 const budget=new TerminalReadBudget({slots:1});const old=await budget.acquire('same');old();
 const replacement=await budget.acquire('same');old();assert.equal(budget.status().active,1);
 replacement();assert.equal(budget.status().active,0);
});

function harness({slots=1,ignoreAbort=false,sendInput,state={data:new Map(),receipts:new Map()}}={}){
 const requests=[],inputs=[],listeners=new Map(),terms=[];
 class Terminal{
  constructor(options){this.options=options;this.cols=100;this.rows=28;this.writes=[];this.resetCount=0;terms.push(this)}
  loadAddon(){}onData(callback){this.data=callback}open(){}resize(c,r){this.cols=c;this.rows=r}focus(){}
  write(text,ack){this.writes.push({text,ack})}reset(){this.resetCount++}dispose(){this.disposed=true}
 }
 const document={hidden:false,addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),
  createElement:()=>({isConnected:false,clientWidth:300,clientHeight:200,parentElement:null,replaceChildren(){},remove(){this.isConnected=false;this.parentElement=null}})};
 const api=(url,body,options={})=>{
  if(typeof url==='string'){
   inputs.push({url,body});
   if(url==='/api/terminal/input'){
    const value={ok:true,status:'delivered',delivery_stage:'delivered_to_process',task_completion_verified:false,
     automatic_retry:false,request_key:body.request_key,input_target:body.input_target,terminal_id:body.id};
    state.receipts.set(body.request_key,value);
    return sendInput?sendInput(body,value):Promise.resolve(value);
   }
   if(url==='/api/terminal/input-ack')return Promise.resolve({acknowledged:true,request_key:body.request_key,terminal_id:body.id,input_target:state.receipts.get(body.request_key)?.input_target});
   return Promise.resolve({});
  }
  if(url.path==='/api/terminal/input-status'){const value=state.receipts.get(url.query.request_key);return Promise.resolve({found:!!value,resolved:!!value,automatic_retry:false,request_key:url.query.request_key,input_target:value?.input_target,terminal_id:url.query.id,result:value})}
  return new Promise((resolve,reject)=>{requests.push({url,resolve,reject});if(!ignoreAbort)options.signal?.addEventListener('abort',()=>reject(Error('aborted')),{once:true})});
 };
 const storage={getItem:key=>state.data.get(key),setItem:(key,value)=>state.data.set(key,value)};
 state.locks??=testLocks();const locks=state.locks;
 class Journal extends TerminalInputJournal{constructor(scope,id){super(scope,id,{storage,locks,crypto:webcrypto})}}
 const context={Terminal,FitAddon:class{proposeDimensions(){return {cols:100,rows:28}}},Unicode11Addon:class{},activateOrcaTerminalUnicodeProvider:()=>{},
  ResizeObserver:class{constructor(fn){this.callback=fn}observe(){}disconnect(){}},api,route:(path,query)=>({path,query}),
  shouldPollTerminalOutput:()=>true,terminalReconcileAction:enabled=>enabled?'apply':'hold',resetForOutput:()=>false,
  restoreCheckpoint,mayWriteTerminal,writeTerminalFrame,releaseDisposedWrites,TerminalReadBudget,TerminalInputQueue,TerminalInputJournal:Journal,deliveredInput,
  window:{addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)},crypto:webcrypto,
  AbortController,TextEncoder,document,setTimeout,clearTimeout};
 const source=fs.readFileSync(new URL('../src/terminal-pool.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
 vm.createContext(context);vm.runInContext(source+'\nglobalThis.Pool=TerminalPool;',context);
 const pool=new context.Pool(()=>{},()=>{});pool.readBudget=new TerminalReadBudget({slots});pool.activeWorkspace='project';pool.setOutputEnabled(true);
 const attach=id=>{
  const slot={isConnected:true,append(child){child.isConnected=true;child.parentElement=this}};
  pool.attach('project',{id,status:'running',name:id},slot);
  return pool.entries.get('project:'+id);
 };
 const frame=(text='out',id='a')=>({text,cursor:[...text].length,status:'running',recoverable:true,persisted:true,
  input_protocol_version:1,input_scope:createHash('sha256').update(id).digest('hex'),input_target:'e'.repeat(32)});
 return {pool,attach,requests,inputs,terms,document,listeners,frame,state};
}
test('slow xterm ACK holds its read credit while a second terminal waits fairly',async()=>{
 const h=harness();
 try{
  const a=h.attach('a');h.attach('b');await tick();assert.equal(h.requests.length,1);
  h.requests[0].resolve(h.frame());await tick();assert.equal(a.term.writes.length,1);
  assert.equal(h.requests.length,1);assert.deepEqual(h.pool.readBudget.status(),{active:1,waiting:1,slots:1,maxWaiting:128});
  a.term.writes[0].ack();await tick();assert.equal(h.requests.length,2);assert.equal(h.requests[1].url.query.id,'b');
 }finally{h.pool.destroy();await tick()}
});
test('a late HTTP response after suspension cannot write or re-enable input',async()=>{
 const h=harness({ignoreAbort:true});
 try{
  const a=h.attach('a');await tick();h.pool.setOutputEnabled(false);
  h.requests[0].resolve(h.frame());await tick();
  assert.equal(a.term.writes.length,0);assert.equal(a.cursor,0);assert.equal(a.inputSuspended,true);assert.equal(a.term.options.disableStdin,true);
  h.pool.command('project','a','must not be sent');await tick();assert.equal(h.inputs.length,0);
 }finally{h.pool.destroy();await tick()}
});
test('suspension during a write marks partial rendering, retains credit until ACK and never advances cursor',async()=>{
 const h=harness();
 try{
  const a=h.attach('a');await tick();h.requests[0].resolve(h.frame());await tick();h.pool.setOutputEnabled(false);
  assert.equal(h.pool.readBudget.status().active,1);assert.equal(a.renderUncertain,true);
  a.term.writes[0].ack();await tick();assert.equal(a.cursor,0);assert.equal(h.pool.readBudget.status().active,0);
  assert.equal(a.term.options.disableStdin,true);
 }finally{h.pool.destroy();await tick()}
});
test('disposing the emulator releases only its own unfinished write and does not create/close a PTY',async()=>{
 const h=harness();const a=h.attach('a');await tick();h.requests[0].resolve(h.frame());await tick();
 h.pool.destroy();await tick();assert.equal(a.term.disposed,true);assert.equal(h.pool.readBudget.status().active,0);
 assert.equal(h.inputs.length,0);assert.equal(h.listeners.size,0);
});
test('unmounted views do not poll and visibility return resumes observation with input still suspended',async()=>{
 const h=harness();
 try{
  const a=h.pool.ensure('project',{id:'unmounted',status:'running'});await tick();assert.equal(h.requests.length,0);
  const b=h.attach('b');await tick();h.document.hidden=true;h.listeners.get('visibilitychange')();await tick();
  assert.equal(b.inputSuspended,true);h.document.hidden=false;h.listeners.get('visibilitychange')();await tick();
  assert.equal(h.requests.length,2);assert.equal(a.term.writes.length,0);assert.equal(b.term.options.disableStdin,true);
 }finally{h.pool.destroy();await tick()}
});
test('a terminal outside the paintable viewport stops reading without changing process state',async()=>{
 const h=harness();
 try{
  const a=h.attach('a');await tick();a.inViewport=false;h.pool.suspend(a);await tick();
  assert.equal(a.status,'running');assert.equal(a.term.disposed,undefined);assert.equal(a.inputSuspended,true);
  const count=h.requests.length;await h.pool.poll(a);assert.equal(h.requests.length,count);
 }finally{h.pool.destroy();await tick()}
});

const wait=async condition=>{const until=Date.now()+3000;while(!condition()){if(Date.now()>until)throw Error('Input condition timed out');await new Promise(resolve=>setTimeout(resolve,3))}};
async function ready(h,id='a',extra={}){
 const entry=h.attach(id);await tick();h.requests.at(-1).resolve({...h.frame('out',id),...extra});await tick();entry.term.writes.at(-1).ack();
 await wait(()=>entry.inputSuspended===false);return entry;
}
test('pool sends Unicode in bounded acknowledged chunks and stores no original command',async()=>{
 const h=harness();
 try{
  const a=await ready(h),data=('🦊x').repeat(800);
  await h.pool.send(a,data);await tick();
  const sent=h.inputs.filter(row=>row.url==='/api/terminal/input');assert.equal(sent.length,2);
  assert.equal(sent.map(row=>row.body.data).join(''),data);
  assert.ok(sent.every(row=>new TextEncoder().encode(row.body.data).length<=4096));
  assert.ok(![...h.state.data.values()].join('').includes('🦊x'));assert.equal(a.inputPending,null);assert.equal(h.pool.inputQueue.status(a.key).bytes,0);
 }finally{h.pool.destroy();await tick()}
});
test('lost input reply blocks the suffix and receipt consultation never repeats input',async()=>{
 let count=0;const h=harness({sendInput:(_body,value)=>++count===1?Promise.reject(Error('lost reply')):Promise.resolve(value)});
 try{
  const a=await ready(h);await h.pool.send(a,'echo secret\r');await tick();assert.ok(a.inputPending);assert.equal(count,1);
  await h.pool.send(a,'must not follow\r');assert.equal(count,1);
  const observed=await h.pool.inspectInput('project','a');assert.equal(observed.resolved,true);assert.equal(count,1);
  assert.equal(await h.pool.resumeInput('project','a'),true);assert.equal(count,1);
  await h.pool.send(a,'new input only\r');await tick();assert.equal(count,2);
 }finally{h.pool.destroy();await tick()}
});
test('a fresh renderer origin adopts the host selector and only observes the original delivery',async()=>{
 const old=harness({sendInput:()=>Promise.reject(Error('lost reply'))});let next;
 try{
  const a=await ready(old);await old.pool.send(a,'old input\r');await tick();
  const selector=JSON.parse([...old.state.data.values()][0])[0];old.pool.destroy();await tick();
  old.state.data.clear(); // A changed broker port has a distinct browser origin.
  next=harness({state:old.state});const restored=await ready(next,'a',{input_pending:[selector]});
  assert.ok(restored.inputBlocked);assert.equal(restored.inputPending.request_key,selector.request_key);
  await next.pool.inspectInput('project','a');assert.equal(await next.pool.resumeInput('project','a'),true);
  assert.equal(next.inputs.filter(row=>row.url==='/api/terminal/input').length,0);
 }finally{old.pool.destroy();next?.pool.destroy();await tick()}
});
test('hiding an in-flight paste drops its remaining chunks and queued Enter',async()=>{
 let release;const h=harness({sendInput:(_body,value)=>new Promise(resolve=>release=()=>resolve(value))});
 try{
  const a=await ready(h),paste=h.pool.send(a,'x'.repeat(2048)+'\r');
  await wait(()=>!!release);const queued=h.pool.send(a,'queued command\r');h.pool.setOutputEnabled(false);release();
  await paste;await queued;await tick();
  const sent=h.inputs.filter(row=>row.url==='/api/terminal/input');assert.equal(sent.length,1);assert.equal(sent[0].body.data.length,1024);
  assert.ok(!sent[0].body.data.includes('\r'));assert.equal(a.inputBlocked,'view_changed');
 }finally{h.pool.destroy();await tick()}
});
test('input overflow blocks that session before a queued Enter can run',async()=>{
 let release;const h=harness({sendInput:(_body,value)=>new Promise(resolve=>release=()=>resolve(value))});
 try{
  const a=await ready(h);h.pool.inputQueue=new TerminalInputQueue({totalBytes:1024,sessionBytes:512,packetBytes:128});
  const first=h.pool.send(a,'x'.repeat(40));await wait(()=>!!release);
  await h.pool.send(a,'y'.repeat(40));assert.equal(a.inputBlocked,'queue_limit');await h.pool.send(a,'\r');
  release();await first;await tick();assert.equal(h.inputs.filter(row=>row.url==='/api/terminal/input').length,1);
 }finally{h.pool.destroy();await tick()}
});
test('a competing window cannot interleave a second input packet in the active writer lease',async()=>{
 const shared={data:new Map(),receipts:new Map()};let release;
 const first=harness({state:shared,sendInput:(_body,value)=>new Promise(resolve=>release=()=>resolve(value))}),second=harness({state:shared});
 try{
  const a=await ready(first),b=await ready(second);
  const active=first.pool.send(a,'first packet\r');await wait(()=>!!release);
  await second.pool.send(b,'must not interleave\r');await tick();
  assert.equal(second.inputs.filter(row=>row.url==='/api/terminal/input').length,0);assert.ok(b.inputBlocked);
  release();await active;await tick();
 }finally{first.pool.destroy();second.pool.destroy();await tick()}
});
test('a host without the receipt protocol stays read-only rather than falling back to unjournaled input',async()=>{
 const h=harness();
 try{
  const a=await ready(h,'a',{input_protocol_version:0});assert.equal(a.inputProtocol,false);
  await h.pool.send(a,'never send');assert.equal(await h.pool.resumeInput('project','a'),false);
  assert.equal(h.inputs.filter(row=>row.url==='/api/terminal/input').length,0);
 }finally{h.pool.destroy();await tick()}
});


test('lost renderer ACK replaces only its emulator, frees read credit and rejects late ACK',async()=>{
 const h=harness();
 try{
  const a=h.attach('a');a.writeAckTimeoutMs=15;h.attach('b');await tick();
  h.requests[0].resolve(h.frame());await tick();const old=a.term,late=old.writes[0].ack;
  await wait(()=>a.rendererRecoveries===1);await tick();
  assert.equal(old.disposed,true);assert.notEqual(a.term,old);assert.equal(a.cursor,0);
  assert.equal(a.term.options.disableStdin,true);assert.equal(h.requests[1].url.query.id,'b');
  late();await tick();assert.equal(a.cursor,0);assert.equal(h.inputs.length,0);
 }finally{h.pool.destroy();await tick()}
});
test('read timeout releases credit, disables input and never repeats an effect',async()=>{
 const h=harness();
 try{
  const a=h.pool.ensure('project',{id:'a',status:'running'});a.readTimeoutMs=15;
  h.attach('a');h.attach('b');await tick();
  await wait(()=>a.transportUnavailable===true);await tick();
  assert.equal(a.term.options.disableStdin,true);assert.equal(a.cursor,0);
  assert.equal(h.requests[1].url.query.id,'b');assert.equal(h.inputs.length,0);
 }finally{h.pool.destroy();await tick()}
});
