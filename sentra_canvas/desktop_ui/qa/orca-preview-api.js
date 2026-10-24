// Local fixtures. No fetch, credentials, processes, or service calls.
import {canonicalIntent,journalIntent} from '../../../integrations/orca-mobile/transport/src/intent-fingerprint.js';
export const hasCredential=false;
export class ApiError extends Error{constructor(message,status=400){super(message);this.status=status;}}
export const isLocalAuthRecovery=()=>false;
export const route=(path,fields)=>path+'?'+new URLSearchParams(fields);
const scope={project_id:'project-preview',space_id:'space-preview'};
export const dots=[['dot-preview','Sentra Agrt','blue'],['dot-second','dasdas','blue'],['dot-third','Teste','mint'],['dot-fourth','testegpt6','purple'],['dot-fifth','Testando Advanced','blue']].map(([id,name,mascot],index)=>({...scope,dot_id:id,agent_id:'agent-'+id,name,mascot,role:'specialist',status:'active',model:'SENTRA Web · GPT-6',created_at:index+1}));
const children=[['child-review','Revisor','mint'],['child-build','Implementador','purple']].map(([id,name,mascot])=>({...scope,dot_id:id,agent_id:'agent-'+id,canvas_root_dot_id:'dot-preview',name,mascot,status:'active'}));
export const terminals=[['demo-main','dot-preview','SENTRA CLI','sentra-cli'],['demo-review','child-review','OpenCode','opencode'],['demo-build','child-build','PowerShell','powershell']].map(([id,dot_id,name,tool])=>({id,dot_id,name,tool,shell:tool,status:'preview',host_id:'preview-host'}));
const graph={dots:[dots[0],...children],agents:[],terminals:[],tool_sessions:[],nodes:[],links:[],tools:[{id:'sentra-cli',title:'SENTRA CLI · simular perda de confirmação',installed:true},{id:'opencode',title:'OpenCode',installed:false}],tasks:[],teams:[],deliveries:[]};
const previewConversations=[...dots,...children].map(dot=>({...scope,dot_id:dot.dot_id,conversation_id:'conversation-'+dot.dot_id,name:'Conversa com '+dot.name,created_at:1792588005}));
const previewMessages=new Map();
const previewConversationRequests=new Map();
const previewUploads=new Map();
const space={...scope,name:'Oxta',dots,conversations:previewConversations,teams:[]};
const files=[{name:'src',path:'src',directory:true},{name:'docs',path:'docs',directory:true},{name:'README.md',path:'README.md',directory:false},{name:'workspace.ts',path:'src/workspace.ts',directory:false},{name:'package.json',path:'package.json',directory:false}];
const documents={'README.md':'# SENTRA Canvas\n\nO workspace pertence a este Dot.\n\n- Terminais e subagentes lado a lado\n- Abas, splits e explorador dentro do Canvas\n- Home e navegação SENTRA preservadas\n\nEsta prévia usa dados fictícios.','src/workspace.ts':'// Prévia visual — nenhum processo real\nexport const workspace = {\n  dot: "Sentra Agrt",\n  panels: ["terminal", "review", "files"],\n  authority: "SENTRA",\n};','package.json':'{\n  "name": "sentra-canvas-preview",\n  "private": true\n}'};
export const transcripts={
 'demo-main':'\x1b[36m  SENTRA\x1b[0m  CLI\r\n\x1b[90m  Sentra Agrt · máquina local\r\n  Prévia visual · sessão simulada\x1b[0m\r\n\r\n  Seu ambiente de criação e colaboração.\r\n\r\n\x1b[90m  ─────────────────────────────────────\x1b[0m\r\n\r\n  Organizar o workspace deste Dot\r\n\r\n  \x1b[36m›\x1b[0m  Terminais lado a lado\r\n  \x1b[36m›\x1b[0m  Revisor e Implementador vinculados\r\n  \x1b[36m›\x1b[0m  Contexto do projeto em um só lugar\r\n\r\n\x1b[90m  Dados fictícios. Nenhum agente foi executado.\x1b[0m\r\n\r\n\x1b[36m❯\x1b[0m ',
 'demo-review':'\x1b[35mOpenCode\x1b[0m\r\n\x1b[90mRevisor · prévia visual\x1b[0m\r\n\r\n┌─ Contexto ─────────────────────┐\r\n│ SENTRA / Canvas do Dot         │\r\n│ Permissões: solicitadas ao host│\r\n└───────────────────────────────┘\r\n\r\n\x1b[90mNenhuma revisão real em execução.\x1b[0m\r\n\r\n\x1b[35m›\x1b[0m ',
 'demo-build':'\x1b[90mPowerShell · Implementador\r\nPrévia visual · comandos desabilitados\x1b[0m\r\n\r\n\x1b[32mPS\x1b[0m C:\\SENTRA>\r\n',
};
async function bridge(p){switch(p.action){
 case 'attachment_upload_begin':{const upload_id='preview-upload-'+p.request_key;const value={...p,upload_id,chunk_bytes:524288,received_bytes:0,received_chunks:0};previewUploads.set(upload_id,value);return {upload_id,chunk_bytes:524288,simulated:true};}
 case 'attachment_upload_chunk':{const value=previewUploads.get(p.upload_id);if(!value)throw new ApiError('Upload simulado indisponível.');if(p.index===value.received_chunks){value.received_chunks++;value.received_bytes=Math.min(value.total_bytes,value.received_bytes+524288);}return {received_chunks:value.received_chunks,received_bytes:value.received_bytes,simulated:true};}
 case 'attachment_upload_complete':{const value=previewUploads.get(p.upload_id);if(!value||value.received_bytes!==value.total_bytes)throw new ApiError('Upload simulado incompleto.');return {attachments:[{attachment_id:value.upload_id,name:value.name,sha256:value.total_sha256,bytes:value.total_bytes,stored:true,simulated:true}]};}
 case 'attachment_upload_abort':{previewUploads.delete(p.upload_id);return {state:'aborted',simulated:true};}
 case 'conversation_create':{
  if(previewConversationRequests.has(p.request_key))return previewConversationRequests.get(p.request_key);
  const value={project_id:p.project_id,space_id:p.space_id,dot_id:p.dot_id,conversation_id:'preview-'+crypto.randomUUID(),title:p.title,status:'active',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),simulated:true};
  previewConversationRequests.set(p.request_key,value);previewConversations.unshift(value);return value;
 }
 case 'conversation_request_status':{const value=previewConversationRequests.get(p.request_key);return {status:value?'confirmed':'not_found',confirmed:Boolean(value),request_key:p.request_key,conversation:value,automatic_retry:false};}
 case 'message_send':{
  const rows=previewMessages.get(p.conversation_id)||[];
  const existing=rows.find(row=>row.request_key===p.request_key);if(existing)return existing;
  const value={...scope,conversation_id:p.conversation_id,message_id:'message-'+crypto.randomUUID(),request_key:p.request_key,role:'user',content:p.content,status:'not_submitted',simulated:true,created_at:new Date().toISOString()};
  const reply={...scope,conversation_id:p.conversation_id,message_id:'message-'+crypto.randomUUID(),role:'assistant',content:'Esta é uma prévia visual. Sua conversa foi criada com o título da mensagem, mas nenhum agente real foi executado.',status:'completed',simulated:true,created_at:new Date().toISOString()};
  previewMessages.set(p.conversation_id,[...rows,value,reply]);return value;
 }
 case 'message_request_status':{const value=(previewMessages.get(p.conversation_id)||[]).find(row=>row.request_key===p.request_key);return {status:value?'confirmed':'not_found',confirmed:Boolean(value),request_key:p.request_key,message:value,automatic_retry:false};}
 case 'dot_canvas_access':{
  if(p.approved!==true||!['read','ask','none'].includes(p.profile))throw new ApiError('Confirmação da simulação necessária.');
  const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonicalIntent(journalIntent(p))));
  const fingerprint=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
  sessionStorage.setItem('qa-orca-recovery:'+p.request_key,JSON.stringify({fingerprint,action:p.action}));
  return {status:'configured',simulated:true};
 }
 case 'dot_canvas_terminal':{
  const bytes=new TextEncoder().encode(canonicalIntent(journalIntent(p)));
  const hash=await crypto.subtle.digest('SHA-256',bytes);
  const fingerprint=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
  sessionStorage.setItem('qa-orca-recovery:'+p.request_key,JSON.stringify({fingerprint,action:p.action}));
  throw new ApiError('Perda de confirmação simulada. Nenhum processo real foi iniciado.',503);
 }
 case 'workspace_request_status':{
  const row=JSON.parse(sessionStorage.getItem('qa-orca-recovery:'+p.selector?.request_key)||'null');
  if(!row)return {found:false,resolved:false,request_key:p.selector?.request_key,automatic_retry:false,may_resend:false};
  if(row.fingerprint!==p.selector.fingerprint||row.action!==p.selector.action)throw new ApiError('Intenção simulada incompatível.');
  return {found:true,resolved:true,request_key:p.selector.request_key,automatic_retry:false,may_resend:false,result:{status:row.action==='dot_canvas_access'?'configured':'accepted',simulated:true},receipt:{stage:'accepted',source_state:'ACCEPTED',completed:false,requires_reconciliation:false,automatic_retry:false}};
 }
 case 'home':return {...scope,space,spaces:[space],dots,conversations:previewConversations,teams:[],documents:[],capabilities:[],attachments:{available:true,max_attachments:4,simulated:true},run:{state:'RUNNING'},activity:{items:[],cursor:0}};
 case 'space_get':return space;
 case 'dot_list':return {items:dots,page:{}};
 case 'space_list':return {items:[space],page:{}};
 case 'access_status':return {mode:'ask',scope:'workspace',approval:'ask',simulated:true};
 case 'conversation_list':return {items:previewConversations.filter(c=>!p.dot_id||c.dot_id===p.dot_id),page:{}};
 case 'conversation_get':return previewConversations.find(c=>c.conversation_id===p.conversation_id);
 case 'message_list':{const rows=previewMessages.get(p.conversation_id)||[];return {items:rows.slice(-50),page:{total:rows.length,offset:Math.max(0,rows.length-50),tail:true}};}
 case 'dot_preferences_get':case 'document_list':case 'coordinator_approval_list':case 'events':return {items:[],cursor:0};
 case 'workspace_presentation_get':{const row=JSON.parse(sessionStorage.getItem('qa-host-profile:'+p.dot_id)||'null');return {scope:'qa-orca-inner-v2',revision:row?.revision||0,profile:row?.profile||null};}
 case 'workspace_presentation_save':{const old=JSON.parse(sessionStorage.getItem('qa-host-profile:'+p.dot_id)||'null');if((old?.revision||0)!==p.expected_revision)return {saved:false,conflict:true,revision:old.revision,scope:'qa-orca-inner-v2'};const row={profile:p.profile,revision:p.expected_revision+1};sessionStorage.setItem('qa-host-profile:'+p.dot_id,JSON.stringify(row));return {saved:true,revision:row.revision,scope:'qa-orca-inner-v2'};}
 case 'workspace_inventory':return {protocol_version:1,layout_scope:'qa-orca-inner-v2',graph,host:{id:'preview-host',label:'Máquina local'},resources:{terminals},preview:true};
 case 'dot_computer_get':return {machines:[{machine_id:'preview-browser',agent_id:'agent-'+p.dot_id,kind:'browser',profiles:[]}],work_items:[],terminals:terminals.filter(t=>t.dot_id===p.dot_id),dots,simulated:true};
 case 'dot_canvas_get':return graph;
 case 'project_file_list':return {path:p.path||'',items:p.path==='src'?files.filter(f=>f.path.startsWith('src/')):p.path==='docs'?[]:files.filter(f=>f.path!=='src/workspace.ts')};
 case 'project_file_preview':return {path:p.path,content:documents[p.path]||'# Documento de exemplo',sha256:'a'.repeat(64)};
 case 'project_file_diff':return {path:p.path,diff:'Prévia visual: nenhum arquivo real modificado.'};
 case 'project_watch_start':return {watch_id:'demo-watch'};
 case 'project_watch_poll':return {state:'unchanged'};
 case 'project_watch_close':return {closed:true};
 default:throw new ApiError('Esta ação exige o SENTRA conectado. A prévia é somente visual.');
}}
export async function api(path,data){
 if(path==='/api/shell/bridge')return {ok:true,value:await bridge(data)};
 if(path.startsWith('/api/terminal/output')){const p=new URL(path,'http://preview').searchParams;return {text:p.get('cursor')==='0'?transcripts[p.get('id')]||'':'',cursor:1,status:'preview',recoverable:true};}
 if(path==='/api/mobile/control')return {ok:true,value:{devices:[],available:false,reason:'Pareamento indisponível na prévia visual.'}};
 throw new ApiError('Recurso indisponível nesta prévia isolada.');
}
export async function apiBinary(){throw new ApiError('Sem mídia real na prévia.');}
export async function apiStream(){throw new ApiError('Prévia sem feed de serviços.',501);}
