import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import orcaLicense from '../../../../vendor/orca/LICENSE?raw';
import {Modal,ActionMenu} from '../primitives';
import {NewSession,WorkspaceAccess} from './NewSession';
import {emptyProfile,validProfile,rememberPanel,resumablePanel,sessionTitle,nameSession,taskState,PresentationWriter} from './continuity';
import {readMode,writeMode,layoutStorageKey,simpleLayout,restoreModeLayout} from './presentation';
import {X,Plus,Columns2,Rows2,Maximize2,Minimize2,RefreshCw,Map as MapIcon,TerminalSquare,FileText,GitCompare,Globe,Monitor,Activity,ArrowLeft,Layers} from 'lucide-react';
import {ShellDotCanvas} from '../shell-dot-canvas';
import {ShellDotComputer} from '../shell-dot-computer';
import {DocumentProjectFiles} from '../document-project-files';
import {ProjectReviewDialog} from '../project-review-dialog';
import {DotMascot} from '../shell-mascot';
import {OrcaTabStrip} from './OrcaTabStrip';
import {WorkspaceExplorer,WorkspaceFile} from './WorkspaceExplorer';
import {WorktreeReview} from './WorktreeReview';
import {WorkspaceTerminal} from './WorkspaceTerminal';
import {useWorkspaceEffects,WorkspacePending} from './useWorkspaceEffects';
import {Bot,MessageCircle,PanelLeft,PanelRight,GitBranch,Smartphone,QrCode,SlidersHorizontal,ShieldCheck,Files} from 'lucide-react';
import {MobileDevices} from './MobileDevices';
import {BrowserPane} from './BrowserPane';
import {OrcaSplit} from './OrcaSplit';
import {initialLayout,restoreLayout,saveLayout,leaf,groups,updateTree,removeGroup,setRatio,moveTab,dropTabAtEdge,dropEdge} from './layout';
import './workspace.css';
import '../document-panel.css';

const labels={map:'Mapa',terminals:'Terminais',files:'Arquivos',review:'Revisão',browser:'Navegador',computer:'Computador',activity:'Atividade'};
const icons={map:MapIcon,terminals:TerminalSquare,files:FileText,review:GitCompare,browser:Globe,computer:Monitor,activity:Activity};
function storage(){try{return localStorage;}catch{return null;}}

export function CanvasWorkspace(props){
 const [enabled,setEnabled]=useState(()=>storage()?.getItem('sentra-orca-workspace-enabled')==='1');
 const [mobile,setMobile]=useState(false);
 if(!enabled)return <div className="sw-feature-gate"><div className="sw-feature-offer"><span>Canvas experimental · SENTRA</span><button onClick={()=>setMobile(true)}><QrCode size={14}/>Celular · QR Code</button><button onClick={()=>{storage()?.setItem('sentra-orca-workspace-enabled','1');setEnabled(true)}}>Experimentar abas e painéis<Layers size={14}/></button></div><ShellDotCanvas {...props}/>{mobile&&<MobileDevices key={props.dot.dot_id} dot={props.dot} onClose={()=>setMobile(false)}/>}</div>;
 return <DotWorkspace {...props} onLegacy={()=>{storage()?.setItem('sentra-orca-workspace-enabled','0');setEnabled(false)}}/>;
}

function RetainedTab({active,children}){const [visited,setVisited]=useState(active);useEffect(()=>{if(active)setVisited(true)},[active]);return active||visited?children:null;}

// The split tree can change shape without remounting provider panels. Stable
// portal roots keep the file selection, scroll and viewer state on maximize.
function PaneMount({container,enabled=true}){
 const host=useRef(null);
 useLayoutEffect(()=>{if(!enabled||!host.current)return;const mount=host.current;mount.appendChild(container);return()=>{if(container.parentNode===mount)mount.removeChild(container)}},[container,enabled]);
 return <div ref={host} className="sw-pane-mount"/>;
}

export function DotWorkspace({dot,roots,bridge,conversations=[],onSelect,onCreate,onConversation,onComputer,onLegacy}){
 const [mode,setMode]=useState(()=>readMode(storage())),[sessionGroup,setSessionGroup]=useState(null),[diagnostics,setDiagnostics]=useState(false),[accessOpen,setAccessOpen]=useState(false);
 const [profile,setProfile]=useState(emptyProfile),[renaming,setRenaming]=useState(null),[renameText,setRenameText]=useState('');
 const profileRef=useRef(profile),writer=useRef(null),observedTerminals=useRef(null);profileRef.current=profile;
 const advanced=mode==='advanced';
 const [snapshot,setSnapshot]=useState(null),[layout,setLayout]=useState(()=>readMode(storage())==='simple'?simpleLayout():initialLayout()),[scopeKey,setScopeKey]=useState(null),[error,setError]=useState(''),[maximized,setMaximized]=useState(null),[busy,setBusy]=useState(false),[review,setReview]=useState(false),[mobile,setMobile]=useState(false);
 const errorKind=useRef('');
 const [layoutConflict,setLayoutConflict]=useState(false),[resolvingLayout,setResolvingLayout]=useState(false),[dragging,setDragging]=useState(false),[edgeTarget,setEdgeTarget]=useState(null),[quickOpen,setQuickOpen]=useState(false),[quickQuery,setQuickQuery]=useState('');
 const modeRef=useRef(mode);modeRef.current=mode;
 const generation=useRef(0),alive=useRef(true),drag=useRef(null),layoutKey=useRef(null),paneRoots=useRef(new Map());
 function containerFor(id){if(!paneRoots.current.has(id)){const node=document.createElement('div');node.className='sw-pane-container';paneRoots.current.set(id,node)}return paneRoots.current.get(id);}
 const scope={project_id:dot.project_id,space_id:dot.space_id,dot_id:dot.dot_id};
 const effects=useWorkspaceEffects(scopeKey,scope,bridge);
 const [memberId,setMemberId]=useState(dot.dot_id);
 const [credits,setCredits]=useState(false),[membersOpen,setMembersOpen]=useState(false),[explorerOpen,setExplorerOpen]=useState(false);
 useEffect(()=>{const query=window.matchMedia('(min-width:1050px)');const adapt=()=>{if(!query.matches){setMembersOpen(false);setExplorerOpen(false)}};query.addEventListener('change',adapt);return()=>query.removeEventListener('change',adapt)},[]);
 const explorerRatio=Number.isFinite(layout.chrome?.explorerRatio)?Math.max(.15,Math.min(.85,layout.chrome.explorerRatio)):.8;
 const graph=snapshot?.graph;
 const terminals=snapshot?.resources?.terminals||graph?.terminals||[];
 const member=graph?.dots.find(d=>d.dot_id===memberId)||dot;
 const conversation=conversations.find(c=>c.dot_id===member.dot_id&&c.space_id===member.space_id);
 const hasPreviousWork=profile.started||terminals.length>0||!!graph?.tasks?.length||!!(conversation&&(conversation.message_count>0||conversation.updated_at>conversation.created_at));
 const hasOpenTerminal=Object.values(layout.panes).some(group=>group.tabs.some(tab=>tab.kind==='terminals'&&tab.resourceId));
 useEffect(()=>{const ids=new Set(groups(layout.tree));for(const id of paneRoots.current.keys())if(!ids.has(id))paneRoots.current.delete(id)},[layout.tree]);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;generation.current++}},[]);
 async function refresh(clearError=false){
  const ticket=++generation.current;
  try{
   const value=await bridge({action:'workspace_inventory',...scope});
   if(!alive.current||ticket!==generation.current)return;
   if(value.protocol_version!==1)throw Error('Versão de workspace incompatível. Use a interface anterior.');
   if(layoutKey.current!==value.layout_scope){
    const saved=await bridge({action:'workspace_presentation_get',...scope});
    if(!alive.current||ticket!==generation.current)return;
    if(saved.scope!==value.layout_scope||saved.profile&&!validProfile(saved.profile))throw Error('A retomada deste Canvas não pôde ser validada.');
    const next=saved.profile||emptyProfile(),currentMode=modeRef.current;
    let nextLayout=next.layouts[currentMode]||restoreModeLayout(storage(),value.layout_scope,currentMode);
    if(!Object.values(nextLayout.panes).some(p=>p.tabs.length)){
     const last=resumablePanel(next,value)||(value.resources?.terminals?.length?{id:'terminals:'+value.resources.terminals[0].id,kind:'terminals',resourceId:value.resources.terminals[0].id}:value.graph?.tasks?.length?{id:'activity',kind:'activity'}:null);
     if(last){nextLayout={...nextLayout,panes:{...nextLayout.panes,[nextLayout.focused]:{tabs:[last],active:last.id}}};next.started=true}
    }
    writer.current?.close();writer.current=new PresentationWriter((p,revision)=>bridge({action:'workspace_presentation_save',...scope,profile:p,expected_revision:revision}),saved.revision,e=>{if(alive.current){setError(e.message);setLayoutConflict(true)}});
    profileRef.current=next;setProfile(next);layoutKey.current=value.layout_scope;setLayout(nextLayout);setScopeKey(value.layout_scope);
    observedTerminals.current=new Set((value.resources?.terminals||[]).map(t=>t.id));
   }else{
    // Adopt a remote layout only when the local writer has no unsaved edit.
    // Layout restoration points at existing resources and never starts them.
    if(!drag.current&&!busy&&!document.querySelector('[role=dialog]')&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)){
     const saved=await bridge({action:'workspace_presentation_get',...scope});
     if(!alive.current||ticket!==generation.current)return;
     if(saved.scope!==value.layout_scope)throw Error('Layout recebido de outro contexto.');
     const adopted=writer.current?.observe(saved);
     if(adopted){profileRef.current=adopted;setProfile(adopted);const next=adopted.layouts[modeRef.current];if(next)setLayout(next)}
    }
    const added=(value.resources?.terminals||[]).filter(t=>!observedTerminals.current?.has(t.id));
    observedTerminals.current=new Set((value.resources?.terminals||[]).map(t=>t.id));
    if(added.length&&profileRef.current.focusPanels&&!document.querySelector('[role=dialog]')&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName))add(null,'terminals',added[0].id);
   }
   setSnapshot(value);if(clearError===true||errorKind.current==='connection'){errorKind.current='';setError('')}
  }catch(e){if(alive.current&&ticket===generation.current&&errorKind.current!=='action'){errorKind.current='connection';setError(e.message)}}
 }

 useEffect(()=>{void refresh();const timer=setInterval(()=>{if(!document.hidden)void refresh()},4000);return()=>clearInterval(timer)},[dot.dot_id,dot.project_id,dot.space_id]);
 useEffect(()=>{if(scopeKey&&layoutKey.current===scopeKey){saveLayout(storage(),layoutStorageKey(scopeKey,mode),layout);const value={...profile,layouts:{...profile.layouts,[mode]:layout}};profileRef.current=value;writer.current?.schedule(value)}},[layout,scopeKey,mode,profile]);
 useEffect(()=>{const flush=()=>void writer.current?.flush();window.addEventListener('blur',flush);document.addEventListener('visibilitychange',flush);return()=>{window.removeEventListener('blur',flush);document.removeEventListener('visibilitychange',flush);writer.current?.close()}},[]);
 function changeMode(next){
  if(next===mode)return;
  const record={...profileRef.current,layouts:{...profileRef.current.layouts,[mode]:layout}};profileRef.current=record;setProfile(record);
  if(scopeKey){saveLayout(storage(),layoutStorageKey(scopeKey,mode),layout);setLayout(profileRef.current.layouts[next]||restoreModeLayout(storage(),scopeKey,next));}
  modeRef.current=next;writeMode(storage(),next);setMode(next);setMaximized(null);setSessionGroup(null);setMembersOpen(false);setExplorerOpen(false);
 }
 async function resolveLayout(choice){
  if(resolvingLayout)return;setResolvingLayout(true);
  try{const current=await bridge({action:'workspace_presentation_get',...scope});if(current.scope!==scopeKey)throw Error('Layout recebido de outro contexto.');
   const local={...profileRef.current,layouts:{...profileRef.current.layouts,[modeRef.current]:layout}};
   const selected=await writer.current.resolve(current,choice,local);
   if(selected){profileRef.current=selected;setProfile(selected);setLayout(selected.layouts[modeRef.current]||(modeRef.current==='simple'?simpleLayout():initialLayout()));setLayoutConflict(false);setError('')}
  }catch(issue){setError(issue.message)}finally{setResolvingLayout(false)}
 }
 function openSession(id=layout.focused){setSessionGroup(id)}
 function active(id,tab){const opened=layout.panes[id]?.tabs.find(t=>t.id===tab);if(opened)setProfile(p=>rememberPanel(p,opened));setLayout(s=>({...s,focused:id,panes:{...s.panes,[id]:{...s.panes[id],active:tab}}}));}
 function add(id,kind,resourceId,label,fileIdentity){
  const bound=['browser','computer','files'].includes(kind),file=kind==='files'&&resourceId;
  const conversationId=file?conversation?.conversation_id:undefined;
  const executionWorkspaceId=file?(fileIdentity?.execution_workspace_id||'project'):undefined;
  const tab={id:resourceId?kind+':'+(file?(conversationId||memberId)+':'+executionWorkspaceId+':':'')+resourceId:bound?kind+':'+memberId:kind,kind,...(resourceId?{resourceId}:{}),...(bound?{dotId:memberId}:{}),...(conversationId?{conversationId,executionWorkspaceId}:{})};
  const matches=t=>t.kind===kind&&(!resourceId||t.resourceId===resourceId)&&(!bound||(t.dotId||dot.dot_id)===memberId)&&(!file||t.conversationId===conversationId&&(t.executionWorkspaceId||'project')===executionWorkspaceId);
  setProfile(p=>{const next=rememberPanel(p,tab);return label&&resourceId?nameSession(next,resourceId,label):next});
  setLayout(s=>{id=id||s.focused;if(resourceId){const open=Object.entries(s.panes).find(([,p])=>p.tabs.some(matches));if(open){const [group,pane]=open,existing=pane.tabs.find(matches);return {...s,focused:group,panes:{...s.panes,[group]:{...pane,active:existing.id}}}}}
   const pane=s.panes[id];if(!pane)return s;const existing=bound?pane.tabs.find(matches):pane.tabs.find(t=>t.id===tab.id),tabId=existing?.id||tab.id;
   return {...s,focused:id,panes:{...s.panes,[id]:{...pane,tabs:existing?pane.tabs:[...pane.tabs,tab],active:tabId}}};});
 }
 function navigateTabs(e,id){if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)||!e.target.closest('[role=tab]'))return;const tabs=layout.panes[id].tabs,index=tabs.findIndex(t=>t.id===layout.panes[id].active);let next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;e.preventDefault();active(id,tabs[next].id);e.currentTarget.querySelectorAll('[role=tab]')[next]?.focus();}
 function split(id,direction){setLayout(s=>{if(groups(s.tree).length>=8)return s;const next=crypto.randomUUID();return {...s,tree:updateTree(s.tree,id,old=>({type:'split',direction,ratio:.5,first:old,second:leaf(next)})),focused:next,panes:{...s.panes,[next]:{tabs:[],active:null}}};});}
 function closeTab(group,tab){setLayout(s=>{const pane=s.panes[group],tabs=pane.tabs.filter(t=>t.id!==tab);return {...s,panes:{...s.panes,[group]:{...pane,tabs,active:pane.active===tab?(tabs.at(-1)?.id||null):pane.active}}};});}
 function closeGroup(group){setLayout(s=>{if(groups(s.tree).length===1)return s;const tree=removeGroup(s.tree,group),panes={...s.panes};delete panes[group];return {...s,tree,panes,focused:groups(tree)[0]};});setMaximized(null);}
 async function mutate(action,fields){
  if(busy||!effects.ready||effects.pending.length)throw Error('Consulte a ação pendente antes de continuar.');
  setBusy(true);errorKind.current='action';setError('');const request={action,...scope,...fields,request_key:crypto.randomUUID()};
  try{const result=await effects.run(request,'canvas');await refresh();if(!result.observation.resolved)setError('Resultado incerto. Consulte o pedido preservado abaixo. Nenhuma ação será reenviada.');else if(result.value.status==='blocked')setError(result.value.reason||'Ação bloqueada pelo SENTRA.');else {errorKind.current='';setError('')}if(result.observation.resolved&&result.value.status!=='blocked'&&result.value.status!=='uncertain')return result.value;}
  catch(e){setError(e.message+' Consulte os pedidos pendentes antes de continuar. Nenhum reenvio automático foi feito.');}
  finally{setBusy(false);}
 }
 function endDrag(){drag.current=null;setDragging(false);setEdgeTarget(null)}
 function drop(e,to,before,edge){e.preventDefault();e.stopPropagation();const payload=drag.current;endDrag();if(!payload)return;setLayout(s=>edge?dropTabAtEdge(s,payload.group,to,payload.tab,edge,crypto.randomUUID()):moveTab(s,payload.group,to,payload.tab,before));}
 function workspaceKeys(e){
  if(e.defaultPrevented||e.isComposing||document.querySelector('[role=dialog]'))return;
  const modifier=e.ctrlKey||e.metaKey,pane=layout.panes[layout.focused];
  if(modifier&&e.key.toLowerCase()==='k'){e.preventDefault();setQuickQuery('');setQuickOpen(true)}
  else if(e.key==='F6'){e.preventDefault();const ids=groups(layout.tree),next=ids[(ids.indexOf(layout.focused)+(e.shiftKey?-1:1)+ids.length)%ids.length];setLayout(s=>({...s,focused:next}));containerFor(next).querySelector('[role=tab][aria-selected=true],button')?.focus()}
  else if(modifier&&['PageUp','PageDown'].includes(e.key)&&pane.tabs.length){e.preventDefault();const at=pane.tabs.findIndex(t=>t.id===pane.active);active(layout.focused,pane.tabs[(at+(e.key==='PageDown'?1:-1)+pane.tabs.length)%pane.tabs.length].id)}
  else if(modifier&&e.shiftKey&&e.key==='Enter'){e.preventDefault();setMaximized(maximized?null:layout.focused)}
  else if(modifier&&e.shiftKey&&e.key==='\\'){e.preventDefault();split(layout.focused,e.altKey?'vertical':'horizontal')}
  else if(modifier&&e.shiftKey&&e.key.toLowerCase()==='w'&&pane.active){e.preventDefault();closeTab(layout.focused,pane.active)}
 }
 function unavailable(tab,groupId,title,detail){return <section className="sw-empty"><h3>{title}</h3><p>{detail}</p><p>A referência foi preservada. Consultar o inventário não cria ou reinicia sessões.</p><div><button onClick={()=>void refresh(true)}>Consultar inventário</button><button onClick={()=>{setQuickQuery('');setQuickOpen(true)}}>Escolher recurso existente</button><button onClick={()=>closeTab(groupId,tab.id)}>Remover esta aba</button></div></section>}

 function content(tab,isActive,groupId){
  const owner=graph?.dots.find(d=>d.dot_id===(tab.dotId||dot.dot_id));
  const boundConversation=conversations.find(c=>c.dot_id===owner?.dot_id&&c.space_id===owner?.space_id&&(!tab.conversationId||c.conversation_id===tab.conversationId));
  if(['browser','computer'].includes(tab.kind)&&!owner)return unavailable(tab,groupId,'Dot indisponível','Esta aba aponta para um Dot que não está mais neste Canvas.');
  if(tab.kind==='browser'&&boundConversation)return <BrowserPane advanced={advanced} onDiagnostics={()=>setDiagnostics(true)} dot={owner} conversation={boundConversation} bridge={bridge} visible={isActive} layoutScope={scopeKey} onConfigure={()=>onComputer(owner)} onDiscuss={draft=>onConversation(owner,{draft})}/>;
  if(tab.kind==='map')return <ShellDotCanvas visible={isActive} dot={dot} roots={roots} bridge={bridge} onSelect={onSelect} onCreate={onCreate} onConversation={onConversation} onComputer={onComputer}/>;
  if(tab.kind==='files'&&tab.resourceId)return owner&&boundConversation&&tab.conversationId&&tab.executionWorkspaceId?<WorkspaceFile bridge={bridge} projectId={dot.project_id} path={tab.resourceId} visible={isActive} onChooseExisting={()=>setExplorerOpen(true)} onRemoveReference={()=>closeTab(groupId,tab.id)} onRequestAccess={()=>onConversation(owner,{draft:'Preciso editar '+tab.resourceId+' neste trabalho. Ajude a preparar o acesso necessário.'})} fileScope={{space_id:owner.space_id,dot_id:owner.dot_id,conversation_id:boundConversation.conversation_id,execution_workspace_id:tab.executionWorkspaceId}}/>:unavailable(tab,groupId,'Trabalho indisponível','A identidade completa do trabalho desta aba não está disponível. Reabra o arquivo pelo explorador do Dot correto.');
  if(tab.kind==='files')return <DocumentProjectFiles bridge={bridge} projectId={dot.project_id} onError={e=>setError(e.message)}/>;
  if(tab.kind==='review')return <WorktreeReview bridge={bridge} scope={scope} conversations={conversations} members={graph?.dots||[dot]} layoutScope={scopeKey} onConversation={(id,options)=>onConversation(graph?.dots.find(d=>d.dot_id===id)||dot,options)} onProjectReview={()=>setReview(true)}/>;
  if(['computer','browser'].includes(tab.kind))return owner&&boundConversation?<ShellDotComputer simple={!advanced} visible={isActive} key={owner.dot_id+tab.kind} dot={owner} conversation={boundConversation} bridge={bridge} onClose={()=>closeTab(groupId,tab.id)} onConfigure={()=>onComputer(owner)} onCanvas={()=>add(layout.focused,'map')} initialTab={tab.kind==='browser'?'remote':'desktop'}/>:<section className="sw-empty"><Monitor size={28}/><h3>Escolha a conversa do Dot</h3><p>O acesso ao computador usa a conversa e suas permissões existentes.</p><button onClick={()=>onConversation(owner||dot)}>Abrir conversa de {owner?.name||dot.name}</button></section>;
  if(tab.kind==='activity')return <section className="sw-activity"><h3>Trabalho deste Canvas</h3>{[...(graph?.tasks||[]),...(graph?.deliveries||[])].map((item,i)=>{const state=taskState(item);return <article key={item.id||item.task_id||item.handoff_id||i}><header><strong>{String(item.objective||item.prompt||item.name||item.tool||'Trabalho do Dot').slice(0,140)}</strong><span className="sw-task-state" data-tone={state.tone}>{state.label}</span></header><details><summary>Detalhes do trabalho</summary><p>{state.detail}</p>{item.verification&&<p>Evidência: integridade de arquivos conferida no instante registrado. {item.verification.files.map(f=>f.path.split(/[\\/]/).at(-1)).join(", ")}</p>}{(item.objective||item.prompt)&&<p>{item.objective||item.prompt}</p>}<p>Responsável: {graph?.dots.find(d=>d.agent_id===item.agent_id||d.dot_id===item.member_dot_id)?.name||dot.name}</p><pre>{JSON.stringify({estado:item.work_item_state||item.status||item.state,operacao:item.operation_id,tarefa:item.work_item_id||item.task_id},null,2)}</pre></details></article>})}{!graph?.tasks?.length&&!graph?.deliveries?.length&&<p>Nenhum trabalho registrado neste escopo.</p>}</section>;
  if(tab.kind==='terminals'&&tab.resourceId){if(!isActive)return null;const terminal=terminals.find(t=>t.id===tab.resourceId);return terminal?<WorkspaceTerminal projectId={dot.project_id} terminal={terminal}/>:unavailable(tab,groupId,'Sessão indisponível','A aba foi restaurada, mas o recurso não foi encontrado.');}
  return <section className="sw-terminals"><h3>Suas sessões</h3><p>Continue de onde parou ou abra uma nova sessão com seu Dot.</p><button className="sw-primary" onClick={()=>openSession()}><Plus size={14}/>Nova sessão</button><div>{terminals.map(t=><article key={t.id}><TerminalSquare size={18}/><span><strong>{sessionTitle(t,profile.sessionNames,graph?.dots.find(d=>d.dot_id===t.dot_id)?.name||dot.name)}</strong><small>{graph?.dots.find(d=>d.dot_id===t.dot_id)?.name||'Dot'} · {t.tool||t.shell} · {t.status==='running'?'Em execução':t.status==='preview'?'Simulação':'Ver sessão'}</small></span><button onClick={()=>add(layout.focused,'terminals',t.id)}>Continuar</button><button aria-label={'Renomear sessão '+t.name} onClick={()=>{setRenaming(t);setRenameText(terminalTitle(t))}}>Renomear</button></article>)}{!terminals.length&&<p>Nenhuma sessão aberta.</p>}</div></section>;
 }
 function pane(id){const group=layout.panes[id],tab=group.tabs.find(t=>t.id===group.active),resource=terminals.find(t=>t.id===tab?.resourceId),owner=graph?.dots.find(d=>d.dot_id===(resource?.dot_id||tab?.dotId||dot.dot_id))||dot;return <section className={'sw-pane '+(layout.focused===id?'focused':'')} key={id} onDragOver={e=>{if(!drag.current)return;e.preventDefault();const edge=dropEdge(e.currentTarget.getBoundingClientRect(),e.clientX,e.clientY);setEdgeTarget(edge?{id,edge}:null)}} onDrop={e=>drop(e,id,undefined,dropEdge(e.currentTarget.getBoundingClientRect(),e.clientX,e.clientY))} onFocusCapture={()=>{if(layout.focused!==id)setLayout(s=>({...s,focused:id}))}}><OrcaTabStrip id={id} group={group} labels={labels} icons={icons} title={tab=>tab.resourceId?(tab.kind==='files'?tab.resourceId.split('/').at(-1):(terminals.find(t=>t.id===tab.resourceId)?terminalTitle(terminals.find(t=>t.id===tab.resourceId)):'Sessão')):labels[tab.kind]} onActivate={active} onClose={closeTab} onSplit={split} onMaximize={()=>setMaximized(maximized?null:id)} maximized={maximized} onCloseGroup={closeGroup} canClose={groups(layout.tree).length>1} onDragStart={(e,group,tab)=>{drag.current={group,tab};setDragging(true);e.dataTransfer.setData('text/plain',tab)}} onDragEnd={endDrag} onDrop={drop} onKeys={navigateTabs} onAdd={()=>openSession(id)} onQuickOpen={()=>{setQuickQuery('');setQuickOpen(true)}} onMove={direction=>{const ids=groups(layout.tree),target=ids[(ids.indexOf(id)+direction+ids.length)%ids.length];if(group.active)setLayout(s=>moveTab(s,id,target,group.active))}} canMove={groups(layout.tree).length>1}/>{dragging&&edgeTarget?.id===id&&<div className={'sw-edge-drop '+edgeTarget.edge} aria-hidden/>}<div className="sw-pane-body">{group.tabs.map(tab=><div key={tab.id} className="sw-tab-surface" role="tabpanel" id={id+'-surface-'+tab.id} aria-labelledby={id+'-tab-'+tab.id} hidden={group.active!==tab.id} inert={group.active!==tab.id}><RetainedTab active={group.active===tab.id}>{content(tab,group.active===tab.id&&(!maximized||maximized===id),id)}</RetainedTab></div>)}{!group.tabs.length&&<section className={'sw-welcome'+(hasPreviousWork?' sw-returning':'')+(hasOpenTerminal?' sw-welcome-compact':'')}><div className="sw-welcome-heading"><DotMascot mascot={member.mascot} name={member.name} size={hasOpenTerminal?'small':'intro'} decorative/><div className="sw-welcome-copy"><h2>{hasOpenTerminal?'Seu próximo passo':hasPreviousWork?'Continue seu trabalho':'O que vamos fazer?'}</h2><p>{hasOpenTerminal?'Continue uma sessão ou converse com '+member.name+'.':hasPreviousWork?'Retome uma sessão ou escolha como trabalhar com '+member.name+'.':'Converse com '+member.name+' ou abra uma sessão para começar.'}</p></div></div><div className="sw-welcome-actions"><button className="sw-primary" onClick={()=>onConversation(member)}><MessageCircle size={16}/>Conversar com {member.name}</button><button onClick={()=>openSession(id)}><Plus size={15}/>Nova sessão</button></div>{terminals.length>0&&<div className="sw-welcome-recent"><h3 className="sw-welcome-recent-title">Sessões disponíveis</h3>{terminals.slice(0,3).map(t=><button key={t.id} onClick={()=>add(id,'terminals',t.id)}><TerminalSquare size={14}/><span>{terminalTitle(t)}</span><ArrowLeft size={12} style={{transform:'rotate(180deg)'}}/></button>)}{terminals.length>3&&<button onClick={()=>openSession(id)}>Ver todas as sessões</button>}</div>}{!hasPreviousWork&&<div className="sw-first-task"><span>Experimente começar com</span><button onClick={()=>onConversation(member,{draft:'Me ajude a conhecer os arquivos deste projeto e propor o primeiro passo. Não altere nada ainda.'})}>Conhecer este projeto</button><button onClick={()=>onConversation(member,{draft:'Quero planejar uma melhoria neste projeto. Primeiro, me ajude a definir o objetivo e os critérios de conclusão.'})}>Planejar uma melhoria</button><small>A sugestão preenche um rascunho. Você decide quando enviar.</small></div>}<button className="sw-quiet" onClick={()=>setExplorerOpen(true)}><Files size={14}/>Consultar arquivos</button></section>}</div>{advanced&&<footer className="sw-pane-footer"><span>{owner.name} · {snapshot?.host?.label||'Máquina local'}</span><select aria-label="Adicionar ferramenta ao painel" value="" onChange={e=>{if(e.target.value)add(id,e.target.value)}}><option value="">+ Ferramenta</option>{Object.entries(labels).map(([kind,label])=><option key={kind} value={kind}>{label}</option>)}</select></footer>}</section>;}
 function selectMember(item){setMemberId(item.dot_id);const terminal=terminals.find(t=>t.dot_id===item.dot_id);add(layout.focused,'terminals',terminal?.id);}
 function terminalTitle(t){return sessionTitle(t,profile.sessionNames,graph?.dots.find(d=>d.dot_id===t.dot_id)?.name||dot.name)}
 const members=graph?.dots||[dot];
 return <section className="sentra-workspace" onKeyDown={workspaceKeys} data-mode={mode} aria-label={'Canvas interno de '+dot.name}>
  <header className="sw-header"><div><button aria-label={membersOpen?'Ocultar subagentes':'Mostrar subagentes'} title="Subagentes e sessões" aria-pressed={membersOpen} onClick={()=>setMembersOpen(v=>!v)}><PanelLeft size={15}/></button><DotMascot mascot={dot.mascot} name={dot.name} size="nav" decorative/><strong>{dot.name}</strong><span className="sw-header-context">Canvas</span>{snapshot?.preview&&<span className="sw-preview-label">Simulação</span>}</div><div className="sw-header-controls"><button className="sw-new-session" onClick={()=>openSession()}><Plus size={14}/>Nova sessão</button><button aria-label={explorerOpen?'Ocultar arquivos':'Mostrar arquivos'} title="Arquivos" aria-pressed={explorerOpen} onClick={()=>setExplorerOpen(v=>!v)}><Files size={15}/></button><button onClick={()=>setMobile(true)} aria-label="Dispositivos · conectar Android ou iPhone por QR Code" title="Dispositivos · QR Code"><Smartphone size={15}/></button><label className="sw-mode"><span className="sr-only">Modo do Canvas</span><select aria-label="Modo do Canvas" value={mode} onChange={e=>changeMode(e.target.value)}><option value="simple">Simples</option><option value="advanced">Avançado</option></select></label><ActionMenu label="Mais opções do Canvas" items={[{label:'Buscar abas e sessões · Ctrl/⌘ K',action:()=>{setQuickQuery('');setQuickOpen(true)}},{label:'Gerenciar sessões',icon:<TerminalSquare size={14}/>,action:()=>add(layout.focused,'terminals')},{label:'Acesso do Dot',icon:<ShieldCheck size={14}/>,action:()=>setAccessOpen(true)},{label:profile.focusPanels?'Desativar painéis contextuais':'Ativar painéis contextuais',action:()=>setProfile(p=>({...p,focusPanels:!p.focusPanels}))},{label:'Diagnóstico',icon:<Activity size={14}/>,action:()=>setDiagnostics(true)},{separator:true},...Object.entries(labels).filter(([kind])=>!['terminals','files'].includes(kind)).map(([kind,label])=>({label,icon:React.createElement(icons[kind],{size:14}),action:()=>add(layout.focused,kind)})),{separator:true},{label:'Consultar estado',icon:<RefreshCw size={14}/>,action:refresh},{label:'Créditos e licenças',action:()=>setCredits(true)},{label:'Canvas anterior',icon:<MapIcon size={14}/>,action:onLegacy}]}/></div></header>
  {layoutConflict&&<div className="sw-attention" role="alert"><span>O layout mudou em outra janela. Seu layout local está preservado.</span><button disabled={resolvingLayout} onClick={()=>void resolveLayout('remote')}>Usar layout salvo</button><button disabled={resolvingLayout} onClick={()=>void resolveLayout('local')}>Manter meu layout</button></div>}
  {error&&<div className="sw-error" role="alert"><span>{advanced?error:"Não foi possível concluir esta ação. Confira os detalhes antes de continuar."}</span><button onClick={()=>setDiagnostics(true)}>Ver diagnóstico</button></div>}
  {advanced?<WorkspacePending effects={effects} onObserved={()=>void refresh()}/>:<>{effects.error&&<div className="sw-error" role="alert">Não foi possível consultar as ações.<button onClick={()=>setDiagnostics(true)}>Ver diagnóstico</button></div>}{effects.pending.length>0&&<div className="sw-attention" role="status"><Activity size={14}/><span>Uma ação precisa de confirmação. Ela não será repetida.</span><button onClick={()=>setDiagnostics(true)}>Conferir</button></div>}</>}
  <div className="sw-workbench">
   {membersOpen&&<aside className="sw-members" aria-label="Subagentes deste Dot"><header><span>WORKSPACE DO DOT</span><button onClick={()=>onCreate(dot)} aria-label="Adicionar subagente"><Plus size={13}/></button></header><button className="sw-member-root" onClick={()=>selectMember(dot)} aria-pressed={member.dot_id===dot.dot_id}><DotMascot mascot={dot.mascot} name={dot.name} size="nav" decorative/><span><strong>{dot.name}</strong><small>Dot principal</small></span></button><div className="sw-members-heading">Subagentes <span>{members.filter(d=>d.dot_id!==dot.dot_id).length}</span></div><div className="sw-member-list">{members.filter(d=>d.dot_id!==dot.dot_id).map(item=><button key={item.dot_id} onClick={()=>selectMember(item)} aria-pressed={member.dot_id===item.dot_id}><span className="sw-status-dot" data-status={item.status}/><span><strong>{item.name}</strong><small>{terminals.filter(t=>t.dot_id===item.dot_id).length} terminal(is)</small></span><Bot size={13}/></button>)}{members.length===1&&<p>Nenhum subagente neste Canvas.</p>}</div><div className="sw-members-heading">SESSÕES <span>{terminals.length}</span></div><div className="sw-member-sessions">{terminals.map(t=><button key={t.id} onClick={()=>add(layout.focused,'terminals',t.id)}><TerminalSquare size={13}/><span>{terminalTitle(t)}<small>{members.find(d=>d.dot_id===t.dot_id)?.name||'Dot'}</small></span><span className="sw-status-dot" data-status={t.status}/></button>)}</div><div className="sw-member-actions"><button onClick={()=>openSession()}><Plus size={13}/>Nova sessão</button><button onClick={()=>onConversation(member)}><MessageCircle size={13}/>Conversa de {member.name}</button><button onClick={()=>add(layout.focused,'activity')}><Activity size={13}/>Tarefas e atividade</button></div><footer><Monitor size={12}/>{snapshot?.host?.label||'Máquina local'}</footer></aside>}
   <div className="sw-editorarea"><OrcaSplit node={explorerOpen?{type:'split',direction:'horizontal',ratio:explorerRatio,first:{type:'leaf',groupId:'workspace'},second:{type:'leaf',groupId:'explorer'}}:{type:'leaf',groupId:'workspace'}} onRatio={(_,ratio)=>setLayout(s=>({...s,chrome:{...s.chrome,explorerRatio:ratio}}))} render={area=>area==='explorer'?<WorkspaceExplorer bridge={bridge} projectId={dot.project_id} fileScope={conversation?{space_id:member.space_id,dot_id:member.dot_id,conversation_id:conversation.conversation_id}:{}} onOpen={(path,identity)=>add(layout.focused,'files',path,undefined,identity)} onReview={()=>add(layout.focused,'review')} onActivity={()=>add(layout.focused,'activity')}/>:<div className="sw-layout" data-split={groups(layout.tree).length>1}>{snapshot?<><div className="sw-layout-tree" hidden={!!maximized}><OrcaSplit node={layout.tree} onRatio={(path,r)=>setLayout(s=>({...s,tree:setRatio(s.tree,path,r)}))} render={id=><PaneMount container={containerFor(id)} enabled={!maximized}/>}/></div>{maximized&&<PaneMount container={containerFor(maximized)}/>} {groups(layout.tree).map(id=>createPortal(pane(id),containerFor(id),id))}</>:<p role="status">Consultando workspace autorizado…</p>}</div>}/></div>
  </div>
  {advanced&&<footer className="sw-statusbar"><span><span className="sw-status-dot" data-status={snapshot?.preview?'preview':'active'}/>{snapshot?.preview?'Prévia isolada · sem processos reais':snapshot?'Inventário conectado':'Consultando inventário'}</span><span>{members.length} Dots · {terminals.length} sessões</span><span>Autoridade SENTRA</span></footer>}
  {sessionGroup&&<NewSession sessionNames={profile.sessionNames} key={member.dot_id} member={member} tools={graph?.tools||[]} terminals={terminals} busy={busy||!effects.ready||effects.pending.length>0} error={error} advanced={advanced} onClose={()=>setSessionGroup(null)} onConversation={()=>{setSessionGroup(null);onConversation(member)}} onPane={kind=>{add(sessionGroup,kind);setSessionGroup(null)}} onOpen={terminal=>{add(sessionGroup,'terminals',terminal.id);setSessionGroup(null)}} onTool={async (tool,label)=>{const group=sessionGroup;const result=await mutate('dot_canvas_terminal',{member_dot_id:member.dot_id,tool});if(result?.terminal_id){add(group,'terminals',result.terminal_id,label);setSessionGroup(null)}}} onAccess={()=>{setSessionGroup(null);setAccessOpen(true)}}/>}
  {quickOpen&&<Modal open onOpenChange={()=>setQuickOpen(false)} title="Buscar abas e sessões" description="Escolha uma aba ou sessão existente. Ctrl/⌘ K abre esta busca."><input autoFocus aria-label="Buscar abas e sessões" value={quickQuery} onChange={e=>setQuickQuery(e.target.value)}/><div className="sw-quick-results">{Object.entries(layout.panes).flatMap(([id,p])=>p.tabs.map(tab=>({id,tab,name:tab.resourceId||labels[tab.kind]}))).filter(item=>item.name.toLocaleLowerCase().includes(quickQuery.toLocaleLowerCase())).slice(0,100).map(item=><button key={item.id+item.tab.id} onClick={()=>{active(item.id,item.tab.id);setMaximized(null);setQuickOpen(false)}}>{item.name}<small>Aba aberta</small></button>)}{terminals.filter(t=>terminalTitle(t).toLocaleLowerCase().includes(quickQuery.toLocaleLowerCase())).map(t=><button key={t.id} onClick={()=>{add(null,'terminals',t.id);setQuickOpen(false)}}>{terminalTitle(t)}<small>Sessão existente · {t.status}</small></button>)}</div></Modal>}
  {accessOpen&&<WorkspaceAccess key={member.dot_id+conversation?.conversation_id} member={member} conversation={conversation} bridge={bridge} scope={scope} advanced={advanced} busy={busy||!effects.ready||effects.pending.length>0} run={mutate} onClose={()=>setAccessOpen(false)} onConversation={()=>{setAccessOpen(false);onConversation(member)}}/>}
  {renaming&&<Modal open onOpenChange={()=>setRenaming(null)} title="Nome da sessão" description="Dê um nome ao trabalho; a ferramenta continua a mesma."><form onSubmit={e=>{e.preventDefault();const name=renameText.trim();if(!name)return;setProfile(p=>nameSession(p,renaming.id,name));setRenaming(null)}}><label>Nome<input autoFocus aria-label="Nome do trabalho" value={renameText} maxLength={80} onChange={e=>setRenameText(e.target.value)}/></label><button disabled={!renameText.trim()}>Salvar nome</button></form></Modal>}
  {diagnostics&&<Modal open onOpenChange={()=>setDiagnostics(false)} title="Diagnóstico do Canvas" description="Detalhes técnicos e consulta de ações, sem repetir envios." className="sw-diagnostics"><WorkspacePending effects={effects} onObserved={()=>void refresh()}/><dl><dt>Dot</dt><dd>{dot.name}</dd><dt>Máquina</dt><dd>{snapshot?.host?.label||'Não informada'}</dd><dt>Projeto</dt><dd>{dot.project_id}</dd><dt>Space</dt><dd>{dot.space_id}</dd><dt>Identidade do Dot</dt><dd>{dot.dot_id}</dd></dl>{error&&<p role="alert">{error}</p>}<button onClick={refresh}>Consultar estado</button></Modal>}
  {credits&&<Modal open onOpenChange={()=>setCredits(false)} title="Licença dos componentes" description="Componentes adaptados para os serviços do SENTRA."><pre style={{whiteSpace:'pre-wrap',fontSize:12,lineHeight:1.7}}>{orcaLicense}</pre></Modal>}{mobile&&<MobileDevices advanced={advanced} dot={dot} onClose={()=>setMobile(false)}/>} {review&&<ProjectReviewDialog ws={dot.project_id} close={()=>setReview(false)}/>}
 </section>;
}
