import {test} from 'node:test';
import assert from 'node:assert/strict';
import {deflateSync} from 'node:zlib';
import {decodeCheckpoint,restoreCheckpoint,mayWriteTerminal} from '../src/terminal-checkpoint.js';
const packet=frame=>({version:1,encoding:'deflate-json-base64',cursor:frame.cursor,sequence:frame.sequence,
 data:deflateSync(Buffer.from(JSON.stringify(frame))).toString('base64')});
const frame={engine_version:1,cursor:12,sequence:3,cols:40,rows:8,scrollbackAnsi:'normal',
 rehydrateSequences:'\x1b[?1049h',snapshotAnsi:'screen',pendingEscapeTailAnsi:'\x1b[31',modes:{}};
test('checkpoint decoding is bounded and validates cursor, geometry and version',async()=>{
 assert.deepEqual(await decodeCheckpoint(packet(frame)),frame);
 await assert.rejects(decodeCheckpoint({...packet(frame),cursor:13}));
 await assert.rejects(decodeCheckpoint(packet({...frame,cols:0})));
 await assert.rejects(decodeCheckpoint({...packet(frame),version:2}));
 await assert.rejects(decodeCheckpoint(packet({...frame,snapshotAnsi:'x'.repeat(1024*1024+1)})),/limite/);
});
test('replay suppresses terminal responses and invalidates queued input',async()=>{
 const writes=[],effects=[],entry={alive:true,inputEpoch:0,term:{options:{disableStdin:false},
  reset(){writes.push('reset')},resize(cols,rows){writes.push([cols,rows])},
  write(text,done){writes.push(text);if(mayWriteTerminal(entry))effects.push('query reply');done();}}};
 const oldEpoch=entry.inputEpoch;
 await restoreCheckpoint(entry,{checkpoint:packet({...frame,scrollbackLines:500}),geometry_sequence:2});
 assert.deepEqual(effects,[]);assert.equal(entry.cursor,12);assert.equal(entry.replaying,false);
 assert.equal(entry.term.options.disableStdin,true);assert.equal(entry.geometrySequence,2);
 assert.equal(entry.scrollbackOmitted,true);
 assert.equal(writes.at(-1),'\x1b[31');
 entry.term.options.disableStdin=false;
 assert.equal(mayWriteTerminal(entry,oldEpoch),false);assert.equal(mayWriteTerminal(entry),true);
});
