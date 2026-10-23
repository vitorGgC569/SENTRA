import {canonicalIntent} from '../../../integrations/orca-mobile/transport/src/intent-fingerprint.js';
const MAX_PENDING=32;
const validRow=row=>row&&Object.keys(row).sort().join(',')==='created_at,fingerprint,input_target,request_key'&&
 typeof row.request_key==='string'&&row.request_key.length>=8&&row.request_key.length<=200&&typeof row.fingerprint==='string'&&/^[0-9a-f]{64}$/.test(row.fingerprint)&&typeof row.input_target==='string'&&/^[0-9a-f]{32}$/.test(row.input_target)&&Number.isSafeInteger(row.created_at)&&row.created_at>0;

/** Only selectors persist here. Original input remains encrypted in the host. */
export class TerminalInputJournal{
 constructor(scope,terminalId,{storage=globalThis.localStorage,locks=globalThis.navigator?.locks,crypto=globalThis.crypto}={}){
  if(!/^[0-9a-f]{64}$/.test(scope))throw Error('Escopo de entrada não confirmado.');
  if(typeof terminalId!=='string'||!terminalId||terminalId.length>128)throw Error('Sessão de entrada inválida.');
  Object.assign(this,{scope,terminalId,storage,locks,crypto});this.key='sentra-terminal-input-v1:'+scope;
 }
 list(){
  const raw=this.storage.getItem(this.key);if(!raw)return [];
  if(raw.length>32768)throw Error('Diário de entrada inválido.');
  const rows=JSON.parse(raw);
  if(!Array.isArray(rows)||rows.length>MAX_PENDING||!rows.every(validRow)||new Set(rows.map(row=>row.request_key)).size!==rows.length)throw Error('Diário de entrada inválido.');
  return rows;
 }
 async locked(callback){if(!this.locks?.request)throw Error('A entrada exige coordenação entre janelas.');return this.locks.request(this.key,callback)}
 revisionKey(epoch){
  if(epoch!==undefined&&(typeof epoch!=='string'||!/^[0-9a-f]{32}$/.test(epoch)))throw Error('Época do host inválida.');
  return this.key+':revision'+(epoch?':'+epoch:'');
 }
 revision(epoch){
  const raw=this.storage.getItem(this.revisionKey(epoch));if(raw===null||raw===undefined)return 0;
  const value=JSON.parse(raw);if(!Number.isSafeInteger(value)||value<0)throw Error('Revisão do diário inválida.');return value;
 }
 advanceRevision(value,epoch){
  if(value===undefined)return;
  if(!Number.isSafeInteger(value)||value<0)throw Error('Revisão do host inválida.');
  this.storage.setItem(this.revisionKey(epoch),JSON.stringify(Math.max(this.revision(epoch),value)));
 }
 async begin(key,target,data){
  // terminalId is set by the host-scoped caller, never read from browser storage.
  if(typeof this.terminalId!=='string'||!this.terminalId||typeof key!=='string'||key.length<8||key.length>200||!/^[0-9a-f]{32}$/.test(target)||typeof data!=='string'||new TextEncoder().encode(data).length>4096)throw Error('Identidade de entrada inválida.');
  const bytes=new TextEncoder().encode(canonicalIntent(['terminal_input',{terminal_id:this.terminalId,data,input_target:target}]));
  const hash=await this.crypto.subtle.digest('SHA-256',bytes);
  const row={request_key:key,input_target:target,fingerprint:Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join(''),created_at:Date.now()};
  return this.locked(()=>{if(this.list().length)throw Error('Há uma entrada sem confirmação nesta sessão.');this.storage.setItem(this.key,JSON.stringify([row]));return row});
 }
 async resolve(row,value){
  if(value?.resolved!==true||value.automatic_retry!==false||value.request_key!==row.request_key||value.input_target!==row.input_target)throw Error('Entrada ainda não confirmada pelo host.');
  return this.locked(()=>{
   const rows=this.list(),existing=rows.find(item=>item.request_key===row.request_key);
   if(existing&&(existing.fingerprint!==row.fingerprint||existing.input_target!==row.input_target))throw Error('A identidade da entrada mudou.');
   this.advanceRevision(value.input_pending_revision,value.input_pending_epoch);
   this.storage.setItem(this.key,JSON.stringify(rows.filter(item=>item.request_key!==row.request_key)));
  });
 }
 async cancelBeforeDispatch(row){
  return this.locked(()=>{
   const rows=this.list();
   this.storage.setItem(this.key,JSON.stringify(rows.filter(item=>!(item.request_key===row.request_key&&item.fingerprint===row.fingerprint&&item.input_target===row.input_target))));
  });
 }
 async adopt(row){
  if(!row)return;
  return this.adoptMany([row]);
 }
 async adoptMany(rows,{revision,epoch}={}){
  if(!Array.isArray(rows)||rows.length>16||!rows.every(validRow)||new Set(rows.map(row=>row.request_key)).size!==rows.length)throw Error('Seletores de entrada do host inválidos.');
  if(revision!==undefined&&(!Number.isSafeInteger(revision)||revision<0))throw Error('Revisão do host inválida.');
  return this.locked(()=>{
   if(revision!==undefined&&revision<this.revision(epoch))return false;
   const merged=new Map(this.list().map(row=>[row.request_key,row]));
   for(const row of rows){
    const existing=merged.get(row.request_key);
    if(existing&&(existing.fingerprint!==row.fingerprint||existing.input_target!==row.input_target))throw Error('Há confirmações diferentes entre esta janela e o host.');
    if(!existing)merged.set(row.request_key,row);
   }
   if(merged.size>MAX_PENDING)throw Error('Limite de confirmações locais atingido. As entradas existentes foram preservadas.');
   const next=[...merged.values()].sort((a,b)=>a.created_at-b.created_at||(a.request_key<b.request_key?-1:a.request_key>b.request_key?1:0));
   this.advanceRevision(revision,epoch);
   this.storage.setItem(this.key,JSON.stringify(next));
   return true;
  });
 }
 async writer(run){
  if(!this.locks?.request)throw Error('A entrada exige coordenação entre janelas.');
  return this.locks.request(this.key+':writer',{ifAvailable:true},lock=>{
   if(!lock)throw Error('Esta sessão recebe entrada em outra janela.');return run();
  });
 }
}
export function deliveredInput(value,row,id){return value?.ok===true&&value.status==='delivered'&&value.delivery_stage==='delivered_to_process'&&value.task_completion_verified===false&&value.automatic_retry===false&&value.request_key===row.request_key&&value.input_target===row.input_target&&value.terminal_id===id}
