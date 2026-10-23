const MAX_COMPRESSED=196608,MAX_PLAIN=1024*1024;
import {restoreSavedRegister,restoreSavedRegisters} from '../../../integrations/orca-terminal/src/saved-register.mjs';
export async function decodeCheckpoint(packet){
 if(packet?.version!==1||packet.encoding!=='deflate-json-base64'||typeof packet.data!=='string'||packet.data.length>MAX_COMPRESSED)
  throw Error('Checkpoint de terminal incompatível.');
 const bytes=Uint8Array.from(atob(packet.data),c=>c.charCodeAt(0));
 const reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
 const chunks=[];let size=0;
 try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;
  if(size>MAX_PLAIN)throw Error('Checkpoint excede o limite de leitura.');chunks.push(value);}
 }finally{await reader.cancel().catch(()=>{});}
 const raw=new Uint8Array(size);let offset=0;for(const chunk of chunks){raw.set(chunk,offset);offset+=chunk.length;}
 const frame=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
 if(frame.engine_version!==1||frame.cursor!==packet.cursor||frame.sequence!==packet.sequence||
  !Number.isSafeInteger(frame.cursor)||frame.cursor<0||!Number.isSafeInteger(frame.sequence)||frame.sequence<0||
  !Number.isInteger(frame.cols)||frame.cols<20||frame.cols>500||!Number.isInteger(frame.rows)||frame.rows<5||frame.rows>200||
  !['snapshotAnsi','scrollbackAnsi','rehydrateSequences'].every(key=>typeof frame[key]==='string')||
  frame.pendingEscapeTailAnsi!==undefined&&typeof frame.pendingEscapeTailAnsi!=='string')
  throw Error('Identidade ou geometria do checkpoint inválida.');
 return frame;
}
export async function writeTerminalFrame(entry,text,current=()=>entry.alive!==false){
 if(!current())throw Error('Visualização de terminal substituída.');
 await new Promise((resolve,reject)=>{
  entry.pendingWrites??=new Set();
  let settled=false;
  const finish=error=>{if(settled)return;settled=true;clearTimeout(timer);entry.pendingWrites.delete(done);error?reject(error):resolve()};
  const done=()=>finish();
  const timer=setTimeout(()=>{
   // A lost xterm ACK cannot retain a global read credit forever. Dispose the
   // emulator before releasing its writes; a late ACK belongs to that emulator.
   finish(Error('A visualização do terminal parou de responder. Restaurando o histórico.'));
   entry.renderUncertain=true;entry.snapshotRestored=false;entry.inputSuspended=true;
   entry.term.options.disableStdin=true;
   if(entry.onRendererStall)entry.onRendererStall();
   else {entry.term.dispose();releaseDisposedWrites(entry)}
  },entry.writeAckTimeoutMs??10000);
  entry.pendingWrites.add(done);
  try{entry.term.write(text,done)}catch(error){finish(error)}
 });
 if(!current())throw Error('Visualização de terminal substituída.');
}
// Call only after disposing this emulator, never merely on temporary suspension.
export function releaseDisposedWrites(entry){for(const done of [...(entry.pendingWrites||[])])done()}
export async function restoreCheckpoint(entry,value,current=()=>entry.alive!==false){
 const frame=await decodeCheckpoint(value.checkpoint);
 if(!current())return false;
 entry.replaying=true;entry.inputEpoch=(entry.inputEpoch||0)+1;entry.term.options.disableStdin=true;
 try{
  if(entry.resizeRenderer)entry.resizeRenderer(frame.cols,frame.rows);else entry.term.resize(frame.cols,frame.rows);
  entry.term.reset();
  const write=text=>writeTerminalFrame(entry,text,current);
  await write(frame.scrollbackAnsi);await write(frame.rehydrateSequences);await write(frame.snapshotAnsi);
  if(frame.modes?.kittyKeyboardFlags)await write(`\x1b[=${frame.modes.kittyKeyboardFlags};1u`);
  await write(frame.pendingEscapeTailAnsi||'');
  restoreSavedRegister(entry.term,frame.savedRegister);
  restoreSavedRegisters(entry.term,frame.savedRegisters);
  entry.cursor=frame.cursor;entry.geometrySequence=value.geometry_sequence;
  entry.snapshotRestored=true;entry.needsServerResize=true;
  entry.renderUncertain=false;
  entry.scrollbackOmitted=Boolean(frame.scrollback_omitted)||frame.scrollbackLines>=500;
  return true;
 }finally{entry.replaying=false;}
}
export function mayWriteTerminal(entry,epoch=entry.inputEpoch){
 return entry.alive&&!entry.inputSuspended&&!entry.inputBlocked&&!entry.replaying&&!entry.term.options.disableStdin&&!entry.transportUnavailable&&entry.inputEpoch===epoch;
}
