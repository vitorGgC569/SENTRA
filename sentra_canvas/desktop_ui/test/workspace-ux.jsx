// Disposable renderer acceptance fixture. No live Canvas or user profile.
import React,{useState} from 'react';
import {ConversationPermissionCards} from '../src/shell-permission-cards';
import {createRoot} from 'react-dom/client';
import * as Tooltip from '@radix-ui/react-tooltip';
import {DotWorkspace} from '../src/workspace/DotWorkspace';
import {canonicalIntent,journalIntent} from '../src/workspace/request-journal';
import '../src/desktop.css';
import '../src/shell-polish.css';
const scope={project_id:'ux-project',space_id:'ux-space',dot_id:'ux-dot'};
const dot={...scope,name:'Oxta',agent_id:'ux-agent',mascot:'blue'},conversation={...scope,conversation_id:'ux-conversation'};
const graph={dots:[dot],tools:[{id:'sentra-cli',name:'SENTRA CLI',installed:true},{id:'opencode',name:'OpenCode',installed:false}],tasks:[],deliveries:[],terminals:[]};
const records=new Map();window.fixture={effects:0,conversations:0,files:0,recipes:[],permissionEffects:0,resources:[],fileScopes:[],gitReviews:0};
let permissionActive=false;
const permission={operation_id:'fixture-file-action',fingerprint:'f'.repeat(64),arguments:{action:'write',path:'README.md'},summary:{title:'Oxta precisa editar este arquivo',reason:'Para atualizar a documentação que você pediu.',target:'README.md',scope:'Somente esta ação neste caminho do projeto',active:true,expires_at:Math.floor(Date.now()/1000)+300}};
const digest=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonicalIntent(value)))),b=>b.toString(16).padStart(2,'0')).join('');
async function bridge(p){
 if(p.action==='workspace_presentation_get'){const stored=JSON.parse(localStorage.getItem('ux-host-profile')||'null');return {scope:'ux-scope',revision:stored?.revision||0,profile:stored?.profile||null};}
 if(p.action==='workspace_presentation_save'){const old=JSON.parse(localStorage.getItem('ux-host-profile')||'null');if((old?.revision||0)!==p.expected_revision)return {saved:false,conflict:true,revision:old.revision,scope:'ux-scope'};const row={profile:p.profile,revision:p.expected_revision+1};localStorage.setItem('ux-host-profile',JSON.stringify(row));return {saved:true,scope:'ux-scope',revision:row.revision};}
 if(p.action==='workspace_inventory')return {protocol_version:1,layout_scope:'ux-scope',graph,host:{label:'Fixture host'},resources:{terminals:[]}};
 if(p.action==='project_file_list'){window.fixture.files++;return {items:[{name:'README.md',path:'README.md',directory:false}]};}
 if(p.action==='project_file_preview'){window.fixture.fileScopes.push({dot_id:p.dot_id,conversation_id:p.conversation_id,execution_workspace_id:p.execution_workspace_id});return {content:'# Arquivo do projeto\nSomente fixture.'};}
 if(p.action==='dot_worktree_review'){window.fixture.gitReviews++;return {state:'needs_review',reason:'Arquivo novo exige revisão.',publication_performed:false,resources:[]};}
 if(p.action==='access_status')return {mode:'ask',scope:'workspace',approval:'ask',requests:permissionActive?[permission]:[]};
 if(p.action==='coordinator_approval_list')return {items:[]};
 if(p.action==='access_approve'){window.fixture.permissionEffects++;permissionActive=false;const value={result:{state:'SUCCEEDED'},panel_hint:{kind:'files',resourceId:'README.md'}};records.set(p.request_key,{value,fingerprint:await digest(journalIntent(p))});throw Error('Confirmação perdida na fixture; não repetir.');}
 if(p.action==='conversation_permission_status'){const row=records.get(p.selector.request_key);if(!row||row.fingerprint!==p.selector.fingerprint)throw Error('Intenção mudou');return {found:true,resolved:true,request_key:p.selector.request_key,automatic_retry:false,result:row.value};}
 if(p.action==='dot_canvas_access'){window.fixture.effects++;window.fixture.recipes.push(p.profile);const value={status:'configured'};records.set(p.request_key,{value,fingerprint:await digest(journalIntent(p))});return value;}
 if(p.action==='workspace_request_status'){const row=records.get(p.selector.request_key);if(!row||row.fingerprint!==p.selector.fingerprint)throw Error('unknown fixture intent');return {found:true,resolved:true,request_key:p.selector.request_key,automatic_retry:false,result:row.value};}
 throw Error('Unsupported acceptance fixture action: '+p.action);
}
function Fixture(){const [permissions,setPermissions]=useState(false);window.fixture.showPermissions=()=>{permissionActive=true;setPermissions(true)};return <Tooltip.Provider><div className="opendots-shell" style={{height:'100%',display:'flex'}}>{permissions?<ConversationPermissionCards scope={{project_id:scope.project_id,space_id:scope.space_id,conversation_id:conversation.conversation_id}} dot={dot} bridge={bridge} onResource={hint=>window.fixture.resources.push(hint)}/>:<DotWorkspace dot={dot} roots={[dot]} bridge={bridge} conversations={[conversation]} onConversation={(_,options)=>{window.fixture.conversations++;window.fixture.proposed=options?.draft}} onSelect={()=>{}} onCreate={()=>{}} onComputer={()=>{}} onLegacy={()=>{}}/>}</div></Tooltip.Provider>}
createRoot(document.getElementById('root')).render(<Fixture/>);
