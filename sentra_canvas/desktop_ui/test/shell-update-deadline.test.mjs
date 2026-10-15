import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createUpdateDeadline} from '../src/shell-update-deadline.js';

test('deadline starts before any native call and ends spinner on a stranded promise', () => {
  let callback, delay, expired = 0;
  const deadline = createUpdateDeadline({
    schedule(fn, ms){callback=fn;delay=ms;return 12;},
    cancel(){},
    timeoutMs:45000,
    onTimeout(){expired++;},
  });
  deadline.arm();
  assert.equal(delay,45000);
  assert.equal(deadline.isArmed(),true);
  callback();
  assert.equal(expired,1);
  assert.equal(deadline.isArmed(),false);
});

test('successful completion disarms deadline; no delayed timeout', () => {
  let callback, cancelled = 0, expired=0;
  const deadline = createUpdateDeadline({
    schedule(fn){callback=fn;return 7;},
    cancel(id){assert.equal(id,7);cancelled++;},
    onTimeout(){expired++;}
  });
  deadline.arm();
  deadline.disarm();
  assert.equal(cancelled,1);
  assert.equal(deadline.isArmed(),false);
  assert.equal(expired,0);
});

test('re-arming cancels an older timeout before the new one starts', () => {
  const cancelled=[];
  let next=0;
  const d=createUpdateDeadline({
    schedule(){return ++next;},cancel(v){cancelled.push(v);},onTimeout(){}
  });
  d.arm();d.arm();d.disarm();
  assert.deepEqual(cancelled,[1,2]);
});
