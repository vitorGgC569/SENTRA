import {test} from 'node:test';
import assert from 'node:assert/strict';
import {TerminalFeed} from '../src/terminal-feed';
import type {TerminalOutputFrame} from '../src/contracts';
const frame=(start:number,text:string,extra:Partial<TerminalOutputFrame>={}):TerminalOutputFrame=>({protocol_version:1,terminal_id:'t',
 start,cursor:start+Array.from(text).length,text,truncated:false,has_more:false,read_only:true,automatic_input_replay:false,status:'exited',...extra});
const pause=()=>new Promise(resolve=>setTimeout(resolve,15));

test('terminal observation drains bounded Unicode pages with one in-flight read and no writes',async()=>{
 const reads:number[]=[],delivered:string[]=[],errors:Error[]=[];let active=0,maximum=0;
 const feed=new TerminalFeed('t',async cursor=>{reads.push(cursor);maximum=Math.max(maximum,++active);await pause();active--;
  return cursor===0?frame(0,'🐋x',{has_more:true}):frame(2,'done')},value=>{delivered.push(value.text)},error=>errors.push(error));
 feed.start();feed.start();const deadline=Date.now()+2000;
 while(delivered.length<2&&errors.length===0&&Date.now()<deadline)await pause();
 feed.stop();
 assert.deepEqual(reads,[0,2]);assert.deepEqual(delivered,['🐋x','done']);assert.equal(maximum,1);assert.equal(feed.after,6);assert.deepEqual(errors,[]);
});

test('retired connection callbacks and timers cannot deliver or schedule more reads',async()=>{
 let complete!:(f:TerminalOutputFrame)=>void,calls=0;const delivered:any[]=[];
 const feed=new TerminalFeed('t',()=>{calls++;return new Promise(resolve=>complete=resolve)},f=>{delivered.push(f)},()=>assert.fail('stale error'));
 feed.start();feed.stop();complete(frame(0,'old',{has_more:true}));await pause();assert.equal(calls,1);assert.deepEqual(delivered,[]);
});

test('undeclared gaps, foreign terminals and oversized or inconsistent frames stop observation',async()=>{
 for(const invalid of [frame(2,'gap'),frame(0,'x',{terminal_id:'other'}),frame(0,'🐋',{cursor:2}),frame(0,'x'.repeat(16001))]){
  const errors:Error[]=[];let delivered=0;const feed=new TerminalFeed('t',async()=>invalid,()=>{delivered++},e=>errors.push(e));
  feed.start();await pause();assert.equal(delivered,0);assert.equal(errors.length,1);assert.equal(feed.after,0);
 }
});

test('declared loss resets the view and an explicit restart keeps the observed cursor',async()=>{
 let calls=0;const deliveries:any[]=[],errors:Error[]=[];
 const feed=new TerminalFeed('t',async cursor=>{calls++;if(calls===1)return frame(50,'new',{truncated:true});
  assert.equal(cursor,53);throw Error('revoked')},f=>{deliveries.push(f)},e=>errors.push(e));
 feed.start();await pause();assert.equal(deliveries[0].reset,true);feed.start();await pause();
 assert.equal(errors.length,1);assert.equal(calls,2);feed.stop();
});

test('renderer acknowledgement applies backpressure before advancing the read cursor',async()=>{
 let acknowledge!:(value:{cursor:number})=>void;const reads:number[]=[];
 const feed=new TerminalFeed('t',async cursor=>{reads.push(cursor);return frame(cursor,'x',{has_more:reads.length===1})},
  ()=>reads.length===1?new Promise(resolve=>acknowledge=resolve):undefined,()=>assert.fail('unexpected feed error'));
 feed.start();await pause();assert.deepEqual(reads,[0]);assert.equal(feed.after,0);
 acknowledge({cursor:20});await pause();assert.deepEqual(reads,[0,20]);assert.equal(feed.after,21);feed.stop();
});
