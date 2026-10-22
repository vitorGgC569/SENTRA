import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ScopedRefresh} from '../src/scoped-refresh';
test('stopped or replaced scopes never deliver stale reads, errors or schedule another read',async()=>{
 const pending:Array<{resolve:(value:number)=>void;reject:(error:Error)=>void}>=[],delivered:number[]=[],errors:Error[]=[];
 const feed=new ScopedRefresh(()=>new Promise<number>((resolve,reject)=>pending.push({resolve,reject})),value=>delivered.push(value),error=>errors.push(error));
 feed.start();feed.start();assert.equal(pending.length,1);feed.stop();feed.start();assert.equal(pending.length,2);
 pending[0].resolve(1);await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(delivered,[]);
 pending[1].resolve(2);await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(delivered,[2]);feed.stop();
 feed.start();feed.stop();pending[2].reject(Error('late'));await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(errors,[]);
});
