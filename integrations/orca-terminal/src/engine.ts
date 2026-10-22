import {HeadlessEmulator} from '../vendor/orca/src/main/daemon/headless-emulator';
import {captureSavedRegister,restoreSavedRegister,captureSavedRegisters,restoreSavedRegisters} from './saved-register.mjs';
export {activateOrcaTerminalUnicodeProvider} from '../vendor/orca/src/shared/terminal-unicode-provider';

export const ENGINE_VERSION=1;
export const SCROLLBACK=500;
const MAX_CELLS=2_000_000,MAX_FRAME=512*1024;
const cost=(cols:number,rows:number)=>cols*(SCROLLBACK+rows*2);
function dimensions(cols:number,rows:number){
 if(!Number.isInteger(cols)||!Number.isInteger(rows)||cols<20||cols>500||rows<5||rows>200)
  throw Error('Unsupported terminal geometry');
}
class SnapshotTerminal extends HeadlessEmulator {get runtime(){return this.terminal;}}
export class SnapshotEngine {
 sessions=new Map<string,{emulator:SnapshotTerminal;sequence:number;cursor:number;cells:number}>();
 async create(id:string,cols=100,rows=28,seed?:any){
  dimensions(cols,rows);
  if(this.sessions.has(id))throw Error('Mirror already exists');
  const cells=cost(cols,rows),used=[...this.sessions.values()].reduce((n,s)=>n+s.cells,0);
  if(this.sessions.size>=32||used+cells>MAX_CELLS)throw Error('Snapshot mirror cell budget exhausted');
  const emulator=new SnapshotTerminal({cols,rows,scrollback:SCROLLBACK});
  const state={emulator,sequence:0,cursor:0,cells};this.sessions.set(id,state);
  try{if(seed){
   if(seed.engine_version!==ENGINE_VERSION||seed.cols!==cols||seed.rows!==rows)throw Error('Checkpoint engine or geometry mismatch');
   await emulator.write(seed.scrollbackAnsi||'');await emulator.write(seed.rehydrateSequences||'');
   await emulator.write(seed.snapshotAnsi||'');
   await emulator.applyKittyKeyboardFlags(seed.modes?.kittyKeyboardFlags||0);
   await emulator.write(seed.pendingEscapeTailAnsi||'');
   emulator.setRestoredOscLinks(seed.oscLinks);emulator.setCwd(seed.cwd||null);
   if(seed.lastTitle)emulator.setLastTitle(seed.lastTitle);
   restoreSavedRegister(emulator.runtime,seed.savedRegister);
   restoreSavedRegisters(emulator.runtime,seed.savedRegisters);
   state.sequence=seed.sequence;state.cursor=seed.cursor;
  }}catch(error){this.dispose(id);throw error;}
 }
 async apply(id:string,event:any){
  const state=this.sessions.get(id);if(!state)throw Error('Unknown mirror');
  if(event.sequence!==state.sequence+1||event.start!==state.cursor)throw Error('Terminal event gap');
  if(event.kind==='output'){
   if(typeof event.text!=='string'||Buffer.byteLength(event.text)>128*1024)throw Error('Output frame too large');
   await state.emulator.write(event.text);
   // Python cursors count Unicode code points, not JavaScript UTF-16 units.
   state.cursor+=Array.from(event.text).length;
  }else if(event.kind==='resize'){
   dimensions(event.cols,event.rows);const cells=cost(event.cols,event.rows);
   const used=[...this.sessions.values()].reduce((n,s)=>n+s.cells,0);
   if(used-state.cells+cells>MAX_CELLS)throw Error('Snapshot mirror cell budget exhausted');
   state.emulator.resize(event.cols,event.rows);state.cells=cells;
  }else throw Error('Unsupported terminal event');
  state.sequence=event.sequence;
 }
 capture(id:string){
  const state=this.sessions.get(id);if(!state)throw Error('Unknown mirror');
  for(const rows of [SCROLLBACK,100,0]){
   const frame={...state.emulator.getSnapshot({scrollbackRows:rows}),engine_version:ENGINE_VERSION,
    savedRegister:captureSavedRegister(state.emulator.runtime),
    savedRegisters:captureSavedRegisters(state.emulator.runtime),
    sequence:state.sequence,cursor:state.cursor,scrollback_omitted:Math.max(0,state.emulator.getSnapshot({scrollbackRows:0}).scrollbackLines-rows)};
   frame.scrollbackLines=Math.min(rows,frame.scrollbackLines);
   if(Buffer.byteLength(JSON.stringify(frame))<=MAX_FRAME)return frame;
  }
  throw Error('Visible terminal checkpoint exceeds its byte budget');
 }
 inspect(id:string){
  const state=this.sessions.get(id);if(!state)throw Error('Unknown mirror');
  return {lines:state.emulator.getVisibleLines(),rows:state.emulator.getVisibleRows(),snapshot:this.capture(id)};
 }
 dispose(id:string){this.sessions.get(id)?.emulator.dispose();this.sessions.delete(id);}
 close(){for(const id of this.sessions.keys())this.dispose(id);}
}
