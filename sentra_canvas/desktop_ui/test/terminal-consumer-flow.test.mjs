import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {TerminalReadBudget} from '../../../integrations/orca-terminal/src/consumer-flow.mjs';
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

function harness({slots=1,ignoreAbort=false}={}){
 const requests=[],inputs=[],listeners=new Map(),terms=[];
 class Terminal{
  constructor(options){this.options=options;this.cols=100;this.rows=28;this.writes=[];this.resetCount=0;terms.push(this)}
  loadAddon(){}onData(callback){this.data=callback}open(){}resize(c,r){this.cols=c;this.rows=r}focus(){}
  write(text,ack){this.writes.push({text,ack})}reset(){this.resetCount++}dispose(){this.disposed=true}
 }
 const document={hidden:false,addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),
  createElement:()=>({isConnected:false,clientWidth:300,clientHeight:200,parentElement:null,remove(){this.isConnected=false;this.parentElement=null}})};
 const api=(url,body,options={})=>{
  if(typeof url==='string'){inputs.push({url,body});return Promise.resolve({})}
  return new Promise((resolve,reject)=>{requests.push({url,resolve,reject});if(!ignoreAbort)options.signal?.addEventListener('abort',()=>reject(Error('aborted')),{once:true})});
 };
 const context={Terminal,FitAddon:class{proposeDimensions(){return {cols:100,rows:28}}},Unicode11Addon:class{},activateOrcaTerminalUnicodeProvider:()=>{},
  ResizeObserver:class{constructor(fn){this.callback=fn}observe(){}disconnect(){}},api,route:(path,query)=>({path,query}),
  shouldPollTerminalOutput:()=>true,terminalReconcileAction:enabled=>enabled?'apply':'hold',resetForOutput:()=>false,
  restoreCheckpoint,mayWriteTerminal,writeTerminalFrame,releaseDisposedWrites,TerminalReadBudget,
  AbortController,TextEncoder,document,setTimeout,clearTimeout};
 const source=fs.readFileSync(new URL('../src/terminal-pool.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
 vm.createContext(context);vm.runInContext(source+'\nglobalThis.Pool=TerminalPool;',context);
 const pool=new context.Pool(()=>{},()=>{});pool.readBudget=new TerminalReadBudget({slots});pool.activeWorkspace='project';pool.setOutputEnabled(true);
 const attach=id=>{
  const slot={isConnected:true,append(child){child.isConnected=true;child.parentElement=this}};
  pool.attach('project',{id,status:'running',name:id},slot);
  return pool.entries.get('project:'+id);
 };
 const frame=(text='out')=>({text,cursor:[...text].length,status:'running',recoverable:true,persisted:true});
 return {pool,attach,requests,inputs,terms,document,listeners,frame};
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
