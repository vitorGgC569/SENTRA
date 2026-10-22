import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ScopedInputQueue } from '../src/shell-input-queue.js';
test('scope and epoch are copied and pending input is dropped before release',async()=>{
  let unblock; const sent=[];
  const queue=new ScopedInputQueue(async request=>{sent.push(request);if(sent.length===1)await new Promise(resolve=>{unblock=resolve;});return {state:'SUCCEEDED'};});
  const request={dot_id:'first',expected_epoch:3,arguments:{action:'input.key',scancodes:[30]}};
  queue.enqueue(request); await Promise.resolve();
  request.dot_id='second';request.expected_epoch=7;
  queue.enqueue(request);
  const released=queue.release([{dot_id:'first',expected_epoch:3,arguments:{action:'input.key',scancodes:[158]}}]);
  unblock();await released;
  assert.deepEqual(sent.map(item=>[item.dot_id,item.expected_epoch,item.arguments.scancodes]),[['first',3,[30]],['first',3,[158]]]);
});
test('an uncertain input clears pending effects without retry',async()=>{
  const sent=[],errors=[];
  const queue=new ScopedInputQueue(async request=>{sent.push(request);return {state:'UNCERTAIN'};},error=>errors.push(error));
  queue.enqueue({id:1});queue.enqueue({id:2});await queue.serial;
  assert.equal(sent.length,1);assert.equal(errors.length,1);
});
