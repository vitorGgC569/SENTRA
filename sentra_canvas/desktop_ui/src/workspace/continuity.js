import {validateLayout} from './layout.js';
export function emptyProfile(){return {version:1,layouts:{},sessionNames:{},recent:[],started:false,focusPanels:true}}
export function validProfile(p){return !!p&&p.version===1&&p.layouts&&Object.keys(p.layouts).every(k=>['simple','advanced'].includes(k)&&validateLayout(p.layouts[k]))&&p.sessionNames&&typeof p.sessionNames==='object'&&!Array.isArray(p.sessionNames)&&Object.keys(p.sessionNames).length<=200&&Object.entries(p.sessionNames).every(([k,v])=>k.length<=128&&typeof v==='string'&&v.length>0&&v.length<=80)&&Array.isArray(p.recent)&&p.recent.length<=12&&p.recent.every(t=>t&&typeof t.id==='string'&&['terminals','files','browser','computer','review','activity','map'].includes(t.kind))&&typeof p.started==='boolean'&&typeof p.focusPanels==='boolean'}
export function rememberPanel(profile,tab){return {...profile,started:true,recent:[tab,...profile.recent.filter(t=>t.id!==tab.id)].slice(0,12)}}
export function resumablePanel(profile,inventory){
 for(const tab of profile.recent){
  if(tab.kind==='terminals'&&tab.resourceId&&!inventory.resources?.terminals?.some(t=>t.id===tab.resourceId))continue;
  if(tab.dotId&&!inventory.graph?.dots?.some(d=>d.dot_id===tab.dotId))continue;
  return tab;
 }return null;
}
export function sessionTitle(terminal,names={},dotName='Dot'){
 if(names[terminal.id])return names[terminal.id];
 const name=terminal.name||'';
 return !name||/^(?:Dot_|SENTRA CLI|OpenCode|PowerShell|CMD|Codex|Grok)/i.test(name)?'Trabalho de '+dotName:name;
}
export function nameSession(profile,id,name){const kept=Object.entries(profile.sessionNames).filter(([key])=>key!==id).slice(-199);return {...profile,sessionNames:Object.fromEntries([...kept,[id,name.trim().slice(0,80)]])}}
export function taskState(row){
 const states=[row.work_item_state,row.operation_state,row.status,row.state].map(s=>String(s||'').toUpperCase());
 let stage;
 if(states.some(s=>['UNCERTAIN','UNCONFIRMED','WAITING_CONFIRMATION'].includes(s)))stage='waiting_confirmation';
 else if(states.includes('FAILED'))stage='failed';
 else if(states.some(s=>['CANCELLED','CANCELED'].includes(s)))stage='cancelled';
 else if(states.includes('EXPIRED'))stage='expired';
 else if(states.some(s=>['INTERRUPTED','PAUSED','RECOVERING'].includes(s)))stage='interrupted';
 else if(states.some(s=>['WAITING_APPROVAL','BLOCKED'].includes(s)))stage='waiting_approval';
 else if(row.lifecycle?.evidence_verified===true&&states.some(s=>['SUCCEEDED','COMPLETED'].includes(s)))stage='verified';
 else if(states.some(s=>['RUNNING','EXECUTING'].includes(s)))stage='running';
 else if(states.some(s=>['SUCCEEDED','COMPLETED'].includes(s)))stage=row.lifecycle?.evidence_verified===true?'verified':'waiting_confirmation';
 else if(states.some(s=>['DELIVERED','RECEIVED','STARTING','DISPATCHED','SENT'].includes(s)))stage='delivered';
 else stage=row.lifecycle?.stage||'requested';
 const values={requested:['Solicitado','waiting','Pedido recebido e registrado.'],delivered:['Entregue ao Dot','waiting','O destinatário confirmou o recebimento; isso não comprova conclusão.'],running:['Em execução','working','O trabalhador iniciou a tarefa.'],waiting_approval:['Aguardando aprovação','attention','Uma decisão é necessária para continuar.'],waiting_confirmation:['Aguardando confirmação','attention','O resultado precisa ser conferido. Se houver incerteza, consulte sem reenviar.'],verified:['Concluído e verificado','done','O resultado foi produzido e sua evidência foi conferida.'],failed:['Falhou','attention','A tarefa falhou; confira o motivo.'],cancelled:['Cancelado','waiting','A tarefa foi cancelada, sem declaração de sucesso.'],expired:['Expirado','attention','O prazo ou a autorização expirou.'],interrupted:['Interrompido','attention','O trabalho foi interrompido; consulte o ponto de retomada.']};
 const [label,tone,detail]=values[stage]||values.requested;return {stage,label,tone,detail};
}

/** Serialized CAS writer. A conflict freezes saves until an explicit reload. */
export class PresentationWriter{
 constructor(save,revision,onError=()=>{}){this.save=save;this.revision=revision;this.onError=onError;this.pending=null;this.busy=false;this.closed=false;this.conflict=false;this.timer=null;this.last=null}
 schedule(profile){if(this.closed||this.conflict)return;this.pending=JSON.stringify(profile);clearTimeout(this.timer);this.timer=setTimeout(()=>void this.flush(),250)}
 observe(value){
  if(this.closed||this.conflict||!Number.isSafeInteger(value?.revision)||value.revision<=this.revision)return null;
  if(!validProfile(value.profile))throw Error('O layout recebido não pôde ser validado.');
  if(this.busy||this.pending&&this.pending!==this.last){
   this.conflict=true;clearTimeout(this.timer);
   this.onError(Error('O layout mudou em outro dispositivo. Suas alterações locais foram preservadas. Reabra o Canvas para escolher a versão salva.'));
   return null;
  }
  this.revision=value.revision;this.last=JSON.stringify(value.profile);this.pending=null;
  return value.profile;
 }
 async flush(){clearTimeout(this.timer);if(this.busy||this.conflict||!this.pending)return;const wire=this.pending;this.pending=null;if(wire===this.last)return;this.busy=true;
  try{const value=await this.save(JSON.parse(wire),this.revision);if(value.saved!==true){this.conflict=true;throw Error('O layout mudou em outra janela. Reabra o Canvas para carregar a versão salva.')}this.revision=value.revision;this.last=wire}
  catch(error){this.conflict=true;this.onError(error)}finally{this.busy=false;if(this.pending&&!this.conflict)void this.flush()}
 }
 close(){this.closed=true;clearTimeout(this.timer);void this.flush()}
}
