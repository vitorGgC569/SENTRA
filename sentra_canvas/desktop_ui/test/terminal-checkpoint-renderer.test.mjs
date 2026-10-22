import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {deflateSync} from 'node:zlib';
import {restoreCheckpoint,mayWriteTerminal} from '../src/terminal-checkpoint.js';
globalThis.window=globalThis;
const require=createRequire(import.meta.url);
const {Terminal}=require('@xterm/xterm'),{Unicode11Addon}=require('@xterm/addon-unicode11');
const {SnapshotEngine,activateOrcaTerminalUnicodeProvider}=require('../../../integrations/orca-terminal/dist/engine.cjs');
function cells(terminal){
 const b=terminal.buffer.active,rows=[];
 for(let y=0;y<terminal.rows;y++){
  const line=b.getLine(b.baseY+y),row=[];
  for(let x=0;x<terminal.cols;x++){
   const cell=line.getCell(x);
   row.push([cell.getChars(),cell.getWidth(),cell.getFgColorMode(),cell.getFgColor(),cell.getBgColorMode(),
    cell.getBgColor(),!!cell.isBold(),!!cell.isDim(),!!cell.isItalic(),!!cell.isUnderline()]);
  }rows.push(row);
 }return {rows,x:b.cursorX,y:b.cursorY,mode:b.type};
}
test('real desktop terminal restores headless colors, saved attributes and a torn escape',async()=>{
 const engine=new SnapshotEngine(),terminal=new Terminal({cols:40,rows:8,allowProposedApi:true,vtExtensions:{kittyKeyboard:true}});
 terminal.loadAddon(new Unicode11Addon());activateOrcaTerminalUnicodeProvider(terminal);
 const entry={term:terminal,alive:true,inputEpoch:0};let effects=0;
 terminal.onData(()=>{if(mayWriteTerminal(entry))effects++;});
 try{
  await engine.create('source',40,8);
  const text='normal 🐋\r\nsecond\x1b[32m\x1b[?1049h\x1b[2J\x1b[3;4H\x1b[1;34mBOLD\x1b7\x1b[0m\x1b[6;7H\x1b[?2004h\x1b[32';
  await engine.apply('source',{kind:'output',sequence:1,start:0,text});const frame=engine.capture('source');
  const packet={version:1,encoding:'deflate-json-base64',cursor:frame.cursor,sequence:frame.sequence,
   data:deflateSync(Buffer.from(JSON.stringify(frame))).toString('base64')};
  await restoreCheckpoint(entry,{checkpoint:packet,geometry_sequence:0});
  const source=engine.sessions.get('source').emulator.runtime;
  assert.deepEqual(cells(terminal),cells(source));
  const next='m\x1b8X';await engine.apply('source',{kind:'output',sequence:2,start:frame.cursor,text:next});
  await new Promise(resolve=>terminal.write(next,resolve));
  assert.deepEqual(cells(terminal),cells(source));
  assert.equal(effects,0);
  const leave='\x1b[?1049lZ';await engine.apply('source',{kind:'output',sequence:3,start:frame.cursor+next.length,text:leave});
  await new Promise(resolve=>terminal.write(leave,resolve));assert.deepEqual(cells(terminal),cells(source));
 }finally{terminal.dispose();engine.close();}
});
