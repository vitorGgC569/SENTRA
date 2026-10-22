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
export async function restoreCheckpoint(entry,value){
 const frame=await decodeCheckpoint(value.checkpoint);
 entry.replaying=true;entry.inputEpoch=(entry.inputEpoch||0)+1;entry.term.options.disableStdin=true;
 try{
  entry.term.reset();entry.term.resize(frame.cols,frame.rows);
  const write=text=>new Promise(resolve=>entry.term.write(text,resolve));
  await write(frame.scrollbackAnsi);await write(frame.rehydrateSequences);await write(frame.snapshotAnsi);
  if(frame.modes?.kittyKeyboardFlags)await write(`\x1b[=${frame.modes.kittyKeyboardFlags};1u`);
  await write(frame.pendingEscapeTailAnsi||'');
  restoreSavedRegister(entry.term,frame.savedRegister);
  restoreSavedRegisters(entry.term,frame.savedRegisters);
  entry.cursor=frame.cursor;entry.geometrySequence=value.geometry_sequence;
  entry.snapshotRestored=true;entry.needsServerResize=true;
  entry.scrollbackOmitted=Boolean(frame.scrollback_omitted)||frame.scrollbackLines>=500;
 }finally{entry.replaying=false;}
}
export function mayWriteTerminal(entry,epoch=entry.inputEpoch){
 return entry.alive&&!entry.replaying&&!entry.term.options.disableStdin&&!entry.transportUnavailable&&entry.inputEpoch===epoch;
}
