import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PresentationQueue} from '../src/presentation-queue';

test('bounded observation queue preserves order and releases a waiting consumer',async()=>{
 const queue=new PresentationQueue(),it=queue[Symbol.asyncIterator]();
 const pending=it.next();queue.push({event:'heartbeat',data:{cursor:1}});
 assert.equal((await pending).value!.data.cursor,1);queue.close();assert.equal((await it.next()).done,true);
});
test('slow observers fail with an explicit gap instead of silently dropping frames',async()=>{
 const queue=new PresentationQueue();for(let i=0;i<129;i++)queue.push({event:'heartbeat',data:{cursor:i}});
 await assert.rejects(queue[Symbol.asyncIterator]().next(),/budget/);
});
test('oversized Unicode observations cannot bypass the retained-byte budget',async()=>{
 const queue=new PresentationQueue();queue.push({event:'shell',data:{text:'界'.repeat(700000)}});
 await assert.rejects(queue[Symbol.asyncIterator]().next(),/budget/);
});
