import {canonicalIntent} from '../../../integrations/orca-mobile/transport/src/intent-fingerprint.js';
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
  if(raw.length>2048)throw Error('Diário de entrada inválido.');
  const rows=JSON.parse(raw);
  if(!Array.isArray(rows)||rows.length>1||!rows.every(validRow))throw Error('Diário de entrada inválido.');
  return rows;
 }
 async locked(callback){if(!this.locks?.request)throw Error('A entrada exige coordenação entre janelas.');return this.locks.request(this.key,callback)}
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
  return this.locked(()=>{const existing=this.list()[0];if(existing&&(existing.request_key!==row.request_key||existing.fingerprint!==row.fingerprint))throw Error('A identidade da entrada mudou.');this.storage.setItem(this.key,'[]')});
 }
 async cancelBeforeDispatch(row){
  return this.locked(()=>{const existing=this.list()[0];if(existing?.request_key===row.request_key&&existing.fingerprint===row.fingerprint)this.storage.setItem(this.key,'[]')});
 }
 async adopt(row){
  if(!row)return;
  if(!validRow(row))throw Error('Seletor de entrada do host inválido.');
  return this.locked(()=>{
   const existing=this.list()[0];
   if(existing){if(existing.request_key!==row.request_key||existing.fingerprint!==row.fingerprint)throw Error('Há confirmações diferentes entre esta janela e o host.');return;}
   this.storage.setItem(this.key,JSON.stringify([row]));this.list();
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
