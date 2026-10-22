import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {SnapshotEngine}=createRequire(import.meta.url)('../dist/engine.cjs');
const output=async(engine,id,text,sequence,start)=>engine.apply(id,{kind:'output',text,sequence,start});
test('normal and alternate buffers, cursor, modes and Unicode survive a fresh mirror',async()=>{
 const e=new SnapshotEngine();try{
  await e.create('original',40,8);
  const text='normal 🐋\r\nsecond\x1b[?1049h\x1b[2J\x1b[3;4H\x1b[1;31mBOLD\x1b[0m\x1b7\x1b[6;7H\x1b[?2004h\x1b[?1002h\x1b[?1006h';
  await output(e,'original',text,1,0);const snapshot=e.capture('original');
  await e.create('restored',40,8,snapshot);
  assert.deepEqual(e.inspect('restored').lines,e.inspect('original').lines);
  assert.deepEqual(e.capture('restored').modes,snapshot.modes);
  const next='\x1b8X\x1b[?1049l';
  await output(e,'original',next,2,snapshot.cursor);await output(e,'restored',next,2,snapshot.cursor);
  assert.deepEqual(e.inspect('restored').lines,e.inspect('original').lines);
  assert.match(e.inspect('restored').lines.join('\n'),/normal 🐋/);
 }finally{e.close();}
});
test('split escape sequences and wrap-pending state survive a checkpoint',async()=>{
 const e=new SnapshotEngine();try{
  await e.create('source',20,5);const first='12345678901234567890\x1b[31';
  await output(e,'source',first,1,0);const frame=e.capture('source');
  assert.equal(frame.pendingEscapeTailAnsi,'\x1b[31');
  await e.create('clone',20,5,frame);const next='m🐋 next';
  await output(e,'source',next,2,frame.cursor);await output(e,'clone',next,2,frame.cursor);
  assert.deepEqual(e.inspect('clone').lines,e.inspect('source').lines);
 }finally{e.close();}
});
test('resize order and sequence gaps are explicit',async()=>{
 const e=new SnapshotEngine();try{
  await e.create('t',20,5);await output(e,'t','one\r\ntwo',1,0);
  await e.apply('t',{kind:'resize',cols:30,rows:7,sequence:2,start:8});
  const frame=e.capture('t');assert.equal(frame.cols,30);assert.equal(frame.rows,7);
  await assert.rejects(output(e,'t','lost',4,frame.cursor),/gap/);
 }finally{e.close();}
});
test('SGR intensity patch and OSC hyperlink metadata are retained',async()=>{
 const e=new SnapshotEngine();try{
  await e.create('s',30,5);const text='\x1b[2mA\x1b[22m\x1b[1mB\x1b[0m\x1b]8;;https://example.invalid/\x07link\x1b]8;;\x07';
  await output(e,'s',text,1,0);const snapshot=e.capture('s');
  await e.create('d',30,5,snapshot);
  assert.deepEqual(e.inspect('d').lines,e.inspect('s').lines);
  assert.deepEqual(e.capture('d').oscLinks,snapshot.oscLinks);
  const terminal=e.sessions.get('d').emulator.terminal;
  const buffer=terminal.buffer.active,cell=buffer.getLine(buffer.baseY).getCell(1);
  assert.equal(!!cell.isBold(),true);assert.equal(!!cell.isDim(),false);
 }finally{e.close();}
});
