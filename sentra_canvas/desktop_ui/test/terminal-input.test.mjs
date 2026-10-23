import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {TerminalInputQueue} from '../../../integrations/orca-terminal/src/input-queue.mjs';
import {TerminalInputJournal,deliveredInput} from '../src/terminal-input-journal.js';
import {testLocks} from './lock-harness.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function store(){const data=new Map();return {data,options:{crypto:webcrypto,
 storage:{getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)},
 locks:testLocks()}}
}
test('input queue counts active packets and metadata, preserves order and rejects excess',async()=>{
 const queue=new TerminalInputQueue({totalBytes:2048,sessionBytes:1024,packetBytes:512}),sent=[];let release;
 const first=queue.enqueue('a','x'.repeat(256),async data=>{sent.push(data);await new Promise(resolve=>release=resolve)});
 const second=queue.enqueue('a','y'.repeat(256),data=>sent.push(data));
 assert.equal(queue.status('a').sessionBytes,1024);assert.throws(()=>queue.enqueue('a','z',()=>{}),/queue_limit/);
 await tick();assert.equal(sent.length,1);release();await first;await second;await tick();
 assert.deepEqual(sent,['x'.repeat(256),'y'.repeat(256)]);assert.equal(queue.status('a').bytes,0);
});
test('cancelling queued input releases only unsent bytes and never replays active input',async()=>{
 const queue=new TerminalInputQueue();let release;const sent=[];
 const active=queue.enqueue('a','active',async data=>{sent.push(data);await new Promise(resolve=>release=resolve)});
 const cancelled=queue.enqueue('a','must not send',data=>sent.push(data));await tick();
 assert.equal(queue.cancel('a'),1);assert.equal((await cancelled).cancelled,true);assert.equal(queue.status('a').count,1);
 release();await active;await tick();assert.deepEqual(sent,['active']);assert.equal(queue.status('a').bytes,0);
});
test('a failed write drops that terminal suffix while another terminal continues',async()=>{
 const queue=new TerminalInputQueue(),sent=[];
 const bad=queue.enqueue('a','first',async()=>{throw Error('lost ACK')});
 const tail=queue.enqueue('a','never resend',data=>sent.push(data));
 const quiet=queue.enqueue('b','quiet',data=>sent.push(data));
 await assert.rejects(bad,/lost ACK/);assert.equal((await tail).cancelled,true);await quiet;await tick();
 assert.deepEqual(sent,['quiet']);assert.equal(queue.status('a').bytes,0);
});
test('UTF-8 payload bounds and invalid Unicode are checked before enqueue',()=>{
 const queue=new TerminalInputQueue({totalBytes:2048,sessionBytes:1024,packetBytes:256});
 assert.throws(()=>queue.enqueue('a','🦊'.repeat(65),()=>{}),/queue_limit/);
 assert.throws(()=>queue.enqueue('a','\ud800',()=>{}),/invalid_unicode/);
 assert.equal(queue.status('a').count,0);
});
test('one saturated terminal leaves room for a quiet terminal to progress',async()=>{
 const queue=new TerminalInputQueue();let release;
 const active=queue.enqueue('flood','x'.repeat(15000),()=>new Promise(resolve=>release=resolve));
 const backlog=Array.from({length:3},()=>queue.enqueue('flood','x'.repeat(15000),()=>assert.fail('cancelled backlog must not run')));
 assert.throws(()=>queue.enqueue('flood','x'.repeat(15000),()=>{}),/queue_limit/);
 let quiet=false;await queue.enqueue('quiet','quiet',()=>{quiet=true});assert.equal(quiet,true);
 await tick();queue.cancel('flood');release();await active;await Promise.all(backlog);await tick();assert.equal(queue.status('flood').bytes,0);
});
test('journal persists only selectors and computes the protected host fingerprint',async()=>{
 const {data,options}=store(),scope='a'.repeat(64),target='b'.repeat(32);
 const journal=new TerminalInputJournal(scope,'terminal',options);
 const row=await journal.begin('request-123',target,'SECRET 😀\r');
 assert.ok(![...data.values()].join('').includes('SECRET'));
 const payload={terminal_id:'terminal',data:'SECRET 😀\r',input_target:target};
 // canonicalIntent follows Python ensure_ascii=True, including surrogate pairs.
 const expected='["terminal_input",{"data":"SECRET \\ud83d\\ude00\\r","input_target":"'+target+'","terminal_id":"terminal"}]';
 assert.equal(row.fingerprint,createHash('sha256').update(expected).digest('hex'));
 assert.equal(new TerminalInputJournal(scope,'terminal',options).list()[0].request_key,'request-123');
 assert.equal(new TerminalInputJournal('c'.repeat(64),'terminal',options).list().length,0);
});
test('two windows cannot dispatch competing entries and an unresolved receipt cannot clear a selector',async()=>{
 const {options}=store(),scope='a'.repeat(64),target='b'.repeat(32);
 const a=new TerminalInputJournal(scope,'terminal',options),b=new TerminalInputJournal(scope,'terminal',options);
 const rows=await Promise.allSettled([a.begin('request-111',target,'one'),b.begin('request-222',target,'two')]);
 assert.equal(rows.filter(row=>row.status==='fulfilled').length,1);const row=a.list()[0];
 await assert.rejects(a.resolve(row,{resolved:false,request_key:row.request_key,input_target:target,automatic_retry:false}),/confirmada/);
 await a.resolve(row,{resolved:true,request_key:row.request_key,input_target:target,automatic_retry:false});assert.equal(a.list().length,0);
});
test('storage failure prevents reservation and cancellation is explicit before dispatch only',async()=>{
 const {options}=store(),scope='a'.repeat(64),target='b'.repeat(32),journal=new TerminalInputJournal(scope,'t',options);
 const row=await journal.begin('request-123',target,'never dispatched');await journal.cancelBeforeDispatch(row);assert.equal(journal.list().length,0);
 options.storage.setItem=()=>{throw Error('disk full')};
 await assert.rejects(journal.begin('request-234',target,'not sent'),/disk full/);
});
test('delivery metadata cannot be confused with task completion or another terminal request',()=>{
 const row={request_key:'key',input_target:'target'},value={ok:true,status:'delivered',delivery_stage:'delivered_to_process',
  task_completion_verified:false,automatic_retry:false,request_key:'key',input_target:'target',terminal_id:'terminal'};
 assert.equal(deliveredInput(value,row,'terminal'),true);
 for(const change of [{status:'uncertain'},{request_key:'other'},{input_target:'other'},{terminal_id:'other'},{task_completion_verified:true},{delivery_stage:'accepted'}])assert.equal(deliveredInput({...value,...change},row,'terminal'),false);
});
test('malformed or competing host selectors cannot overwrite the local unresolved selector',async()=>{
 const {options}=store(),journal=new TerminalInputJournal('a'.repeat(64),'terminal',options);
 const row=await journal.begin('original-key','b'.repeat(32),'private');
 await assert.rejects(journal.adopt({...row,data:'must not persist'}),/inválido/);
 await assert.rejects(journal.adopt({...row,fingerprint:'c'.repeat(64)}),/diferentes/);
 assert.deepEqual(journal.list(),[row]);
});

test('multiple host selectors retain exact identity and resolve independently across reopen',async()=>{
 const {options}=store(),scope='a'.repeat(64),a=new TerminalInputJournal(scope,'terminal',options);
 const local=await a.begin('local-request','b'.repeat(32),'PRIVATE COMMAND');
 const remote={...local,request_key:'remote-request',fingerprint:'c'.repeat(64),input_target:'d'.repeat(32)};
 await a.adoptMany([remote],{revision:1});assert.equal(a.list().length,2);
 const reopened=new TerminalInputJournal(scope,'terminal',options);
 await assert.rejects(reopened.begin('must-not-send','b'.repeat(32),'another command'),/sem confirmação/);
 await reopened.resolve(remote,{resolved:true,automatic_retry:false,request_key:remote.request_key,input_target:remote.input_target,input_pending_revision:2});
 assert.deepEqual(a.list(),[local]);
 await a.cancelBeforeDispatch(remote);assert.deepEqual(a.list(),[local]);
 await a.cancelBeforeDispatch(local);assert.deepEqual(a.list(),[]);
});

test('an older host projection cannot restore acknowledged input in another window',async()=>{
 const {options}=store(),a=new TerminalInputJournal('a'.repeat(64),'terminal',options),b=new TerminalInputJournal('a'.repeat(64),'terminal',options);
 const row={request_key:'host-request',fingerprint:'c'.repeat(64),input_target:'b'.repeat(32),created_at:1};
 assert.equal(await a.adoptMany([row],{revision:4}),true);
 await a.resolve(row,{resolved:true,automatic_retry:false,request_key:row.request_key,input_target:row.input_target,input_pending_revision:5});
 assert.equal(await b.adoptMany([row],{revision:4}),false);assert.deepEqual(b.list(),[]);
 const next={...row,request_key:'host-request-next'};
 assert.equal(await b.adoptMany([next],{revision:6}),true);
 assert.equal(await a.adoptMany([],{revision:5}),false);assert.deepEqual(a.list(),[next]);
});

test('adopting conflicting or over-budget batches preserves every original selector',async()=>{
 const {options}=store(),a=new TerminalInputJournal('a'.repeat(64),'terminal',options);
 const row={request_key:'host-request-0',fingerprint:'c'.repeat(64),input_target:'b'.repeat(32),created_at:1};
 const batch=offset=>Array.from({length:16},(_,i)=>({...row,request_key:'host-request-'+(i+offset)}));
 await a.adoptMany(batch(0));await a.adoptMany(batch(16));assert.equal(a.list().length,32);
 const before=a.list();
 await assert.rejects(a.adoptMany([{...row,request_key:'host-request-extra'}]),/Limite/);
 await assert.rejects(a.adoptMany([{...row,fingerprint:'d'.repeat(64)}]),/diferentes/);
 assert.deepEqual(a.list(),before);
});

test('a new broker epoch can expose a lower restored revision without losing selectors',async()=>{
 const {options}=store(),journal=new TerminalInputJournal('a'.repeat(64),'terminal',options);
 const row={request_key:'old-receipt',fingerprint:'c'.repeat(64),input_target:'b'.repeat(32),created_at:1};
 await journal.adoptMany([row],{revision:100,epoch:'a'.repeat(32)});
 await journal.resolve(row,{resolved:true,automatic_retry:false,request_key:row.request_key,input_target:row.input_target,input_pending_revision:101,input_pending_epoch:'a'.repeat(32)});
 assert.equal(await journal.adoptMany([row],{revision:100,epoch:'a'.repeat(32)}),false);
 const restored={...row,request_key:'restored-receipt'};
 assert.equal(await journal.adoptMany([restored],{revision:2,epoch:'d'.repeat(32)}),true);
 assert.deepEqual(journal.list(),[restored]);
});
