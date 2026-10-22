import {test} from 'node:test';
import assert from 'node:assert/strict';
import {EffectJournal} from '../src/effect-journal';
test('persist before send, retain after restart and refuse uncertain duplicate',async()=>{
 let saved:string|null=null;const storage={read:async()=>saved,write:async(value:string)=>{saved=value}};
 const journal=new EffectJournal(storage),record={key:'request-1',slot:'phone:conversation',device_id:'phone',action:'message_send',created_at:1};
 await journal.begin(record);assert.equal((await journal.list())[0].key,'request-1');
 const restarted=new EffectJournal(storage);
 await assert.rejects(()=>restarted.begin({...record,key:'request-2'}),/sem confirmação/);
 await restarted.finish(record.key);assert.deepEqual(await restarted.list(),[]);
});
test('concurrent admission and storage failure never authorize two sends',async()=>{
 let raw:string|null=null;const journal=new EffectJournal({read:async()=>raw,write:async v=>{raw=v}});
 const record={key:'a',slot:'same',device_id:'p',action:'terminal:write',created_at:1};
 const results=await Promise.allSettled([journal.begin(record),journal.begin({...record,key:'b'})]);
 assert.equal(results.filter(r=>r.status==='fulfilled').length,1);
 const broken=new EffectJournal({read:async()=>null,write:async()=>{throw Error('storage full')}});
 await assert.rejects(()=>broken.begin(record),/storage full/);
});
