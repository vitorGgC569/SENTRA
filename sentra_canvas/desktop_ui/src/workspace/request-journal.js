import {canonicalIntent,journalIntent} from '../../../../integrations/orca-mobile/transport/src/intent-fingerprint.js';
export {canonicalIntent,journalIntent};
export function inspectionRequest(scope,row,selector){
 return {action:'workspace_request_status',project_id:row.project_id||scope.project_id,
  space_id:row.space_id||scope.space_id,dot_id:row.dot_id||scope.dot_id,selector};
}
// Renderer persistence contains selectors only; original content stays on the host.
export class WorkspaceRequestJournal{
 constructor(scope,{storage=globalThis.localStorage,locks=globalThis.navigator?.locks,crypto=globalThis.crypto,changed=()=>{}}={}){
  if(!scope)throw Error('Inventário autorizado ainda não disponível.');
  this.key='sentra-workspace-intents-v1:'+scope;this.storage=storage;this.locks=locks;this.crypto=crypto;this.changed=changed;
 }
 list(){
  const raw=this.storage.getItem(this.key);if(!raw)return [];
  if(raw.length>128000)throw Error('Diário de pedidos excedeu o limite. Consulte o diagnóstico.');
  const rows=JSON.parse(raw);
  if(!Array.isArray(rows)||rows.length>128||!rows.every(r=>r&&Object.keys(r).every(k=>['action','request_key','fingerprint','conversation_id','project_id','space_id','dot_id','slot','created_at'].includes(k))&&typeof r.action==='string'&&typeof r.slot==='string'&&r.slot.length<=512&&typeof r.request_key==='string'&&r.request_key.length<=200&&/^[0-9a-f]{64}$/.test(r.fingerprint)&&['project_id','space_id','dot_id','conversation_id'].every(k=>r[k]===undefined||(typeof r[k]==='string'&&r[k].length>0&&r[k].length<=200))))throw Error('Diário de pedidos inválido. Consulte o diagnóstico sem reenviar.');
  return rows;
 }
 async locked(callback){
  if(!this.locks?.request)throw Error('Este ambiente não permite coordenar pedidos entre janelas.');
  return this.locks.request(this.key,()=>{const result=callback();this.changed();return result});
 }
 async begin(request,slot){
  if(typeof slot!=='string'||!slot||slot.length>512)throw Error('Recurso de execução inválido.');
  const bytes=new TextEncoder().encode(canonicalIntent(journalIntent(request)));
  const hash=await this.crypto.subtle.digest('SHA-256',bytes);
  const row={action:request.action,request_key:request.request_key,project_id:request.project_id,space_id:request.space_id,dot_id:request.dot_id,fingerprint:Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join(''),slot,created_at:Date.now(),...(request.conversation_id?{conversation_id:request.conversation_id}:{})};
  return this.locked(()=>{const rows=this.list();if(rows.some(r=>r.slot===slot||r.request_key===row.request_key))throw Error('Há um pedido deste recurso sem confirmação. Consulte-o antes de enviar outro.');if(rows.length>=128)throw Error('Resolva os pedidos pendentes antes de continuar.');this.storage.setItem(this.key,JSON.stringify([...rows,row]));return row});
 }
 async resolve(row,observation){
  if(observation?.request_key!==row.request_key||observation?.resolved!==true||observation?.automatic_retry!==false)throw Error('O host ainda não confirmou esta intenção.');
  return this.locked(()=>{const rows=this.list(),existing=rows.find(r=>r.request_key===row.request_key);if(existing&&existing.fingerprint!==row.fingerprint)throw Error('A identidade do pedido mudou.');this.storage.setItem(this.key,JSON.stringify(rows.filter(r=>r.request_key!==row.request_key)))});
 }
 selector(row){const {action,request_key,fingerprint,conversation_id}=row;return {action,request_key,fingerprint,...(conversation_id?{conversation_id}:{})};}
}
