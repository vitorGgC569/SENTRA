import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ReconnectLoop} from '../src/reconnect';

const wait=async(condition:()=>boolean)=>{
 const deadline=Date.now()+1000;
 while(!condition()){if(Date.now()>deadline)throw Error('reconnect test timed out');await new Promise(r=>setTimeout(r,2));}
};

test('reopens only the transport, deduplicates triggers and stops after success',async()=>{
 let attempts=0,exhausted=0;
 const loop=new ReconnectLoop({eligible:()=>true,baseDelayMs:2,attempt:async()=>{
  attempts++;if(attempts<3)throw Error('offline');
 },stopOn:()=>false,onExhausted:()=>exhausted++});
 loop.trigger();loop.trigger();
 await wait(()=>!loop.active);
 assert.equal(attempts,3);assert.equal(exhausted,0);
});

test('revoked authorization terminates without another attempt',async()=>{
 let attempts=0,exhausted=0;
 const loop=new ReconnectLoop({eligible:()=>true,baseDelayMs:2,attempt:async()=>{
  attempts++;throw Object.assign(Error('revoked'),{status:403});
 },stopOn:error=>(error as any).status===403,onExhausted:()=>exhausted++});
 loop.trigger();await wait(()=>!loop.active);await new Promise(r=>setTimeout(r,20));
 assert.equal(attempts,1);assert.equal(exhausted,1);
});

test('foreground, device or pairing change cancels a pending reconnect',async()=>{
 let eligible=true,aborted=false,attempts=0,finish!:()=>void;
 const loop=new ReconnectLoop({eligible:()=>eligible,attempt:signal=>{
  attempts++;signal.addEventListener('abort',()=>aborted=true);
  return new Promise<void>(resolve=>finish=resolve);
 },stopOn:()=>false,onExhausted:()=>assert.fail('cancel is not an error')});
 loop.trigger();eligible=false;loop.cancel();assert.equal(aborted,true);finish();
 await new Promise(r=>setTimeout(r,10));assert.equal(loop.active,false);
 loop.trigger();assert.equal(attempts,1);
});

test('late result from a cancelled attempt cannot finish its replacement',async()=>{
 const pending:Array<()=>void>=[];let attempts=0;
 const loop=new ReconnectLoop({eligible:()=>true,attempt:()=>{
  attempts++;return new Promise<void>(resolve=>pending.push(resolve));
 },stopOn:()=>false,onExhausted:()=>assert.fail('unexpected failure')});
 loop.trigger();loop.cancel();loop.trigger();assert.equal(attempts,2);
 pending[0]();await Promise.resolve();assert.equal(loop.active,true);
 pending[1]();await wait(()=>!loop.active);
});
