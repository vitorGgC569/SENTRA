import React,{useEffect,useRef,useState} from 'react';
import {Globe,RefreshCw,Shield} from 'lucide-react';
import {OperationReceipt} from '../shell-receipts';
import {useWorkspaceEffects,WorkspacePending} from './useWorkspaceEffects';

/** Existing Playwright machine contract. No iframe, shared cookie jar or new authority. */
export function BrowserPane({dot,conversation,bridge,visible,layoutScope,onConfigure,advanced=true,onDiagnostics}){
 const scope={project_id:dot.project_id,space_id:dot.space_id,dot_id:dot.dot_id,conversation_id:conversation.conversation_id};
 const effects=useWorkspaceEffects(layoutScope,scope,bridge);
 const storageKey='sentra-browser-view-v1:'+layoutScope+':'+dot.dot_id;
 const [inventory,setInventory]=useState(null),[machineId,setMachineId]=useState(''),[workId,setWorkId]=useState(''),[profile,setProfile]=useState(''),[session,setSession]=useState(()=>{try{return sessionStorage.getItem(storageKey)||''}catch{return ''}}),[sessions,setSessions]=useState([]),[url,setUrl]=useState(''),[observation,setObservation]=useState(null),[receipt,setReceipt]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const alive=useRef(true),intent=useRef(null),callbacks=useRef({bridge,scope});callbacks.current={bridge,scope};
 const machines=(inventory?.machines||[]).filter(m=>m.kind==='browser'&&m.agent_id===dot.agent_id);
 const machine=machines.find(m=>m.machine_id===machineId)||machines[0];
 const jobs=(inventory?.work_items||[]).filter(w=>w.machine_id===machine?.machine_id&&w.capabilities.includes('browser:operate'));
 const work=jobs.find(w=>w.work_item_id===workId)||jobs[0];
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
 useEffect(()=>{if(visible)void refresh()},[visible,dot.dot_id]);
 useEffect(()=>{try{if(session)sessionStorage.setItem(storageKey,session);else sessionStorage.removeItem(storageKey)}catch{}},[session,storageKey]);
 async function refresh(){try{const value=await callbacks.current.bridge({action:'dot_computer_get',...callbacks.current.scope});if(alive.current){setInventory(value);setError('')}}catch(e){if(alive.current)setError(e.message)}}
 function project(value){const result=value.evidence?.payload||value.evidence||{};if(Array.isArray(result.sessions))setSessions(result.sessions);if(result.session_id)setSession(result.session_id);if(result.observation_id)setObservation(result);if(result.url)setUrl(result.url);}
 async function execute(action){
  if(busy||effects.pending.length||!effects.ready||!machine||!work)return;
  const arguments_={action,...(!['open','session.list'].includes(action)?{session_id:session}:{}),...(action==='open'?{profile:profile||machine.profiles?.[0]?.name}:{}),...(action==='navigate'?{url}:{}),...(action==='session.list'?{limit:50}:{})};
  const request={action:'dot_computer_action',...scope,request_key:crypto.randomUUID(),request:{action:'machine_execute',machine_id:machine.machine_id,work_item_id:work.work_item_id,capability_id:'browser:operate',arguments:arguments_}};
  intent.current=request;setBusy(true);setError('');setReceipt(null);
  try{const result=await effects.run(request,'browser:'+dot.dot_id+':'+machine.machine_id);if(!alive.current)return;const value=result.observation.operation||result.value;setReceipt(value);if(!result.observation.resolved){setError('Resultado sem confirmação. Consulte o pedido preservado; ele não será reenviado.');return;}intent.current=null;if(value.state==='SUCCEEDED')project(value);else setError(value.error||'Operação não concluída.');}
  catch(e){if(alive.current)setError(e.message+' Nenhum reenvio automático.');}
  finally{if(alive.current)setBusy(false)}
 }
 const disabled=busy||effects.pending.length>0||!effects.ready||!work;
 return <section className="sw-browser"><header><Globe size={20}/><div><h3>Navegador de {dot.name}</h3><p>{advanced?'Sessões isoladas do serviço de navegador SENTRA.':'Sua navegação ligada ao Dot.'}</p></div><button onClick={refresh} aria-label="Atualizar navegador"><RefreshCw size={14}/></button></header>
  {!machines.length?<div className="sw-empty"><Shield size={26}/><h3>Navegador não configurado</h3><p>{advanced?'Cadastre o serviço e o perfil de rede no SENTRA para este Dot. Abrir esta aba não cria processos.':'Este Dot ainda não tem um navegador disponível. Confira seu ambiente para conectar um.'}</p><button onClick={onConfigure}>{advanced?'Ver ambientes e permissões':'Ver configuração'}</button></div>:<>
   {(advanced||machines.length>1||jobs.length>1)&&<div className="sw-browser-controls"><label>Ambiente<select value={machine?.machine_id||''} disabled={busy||effects.pending.length>0||!effects.ready} onChange={e=>{setMachineId(e.target.value);setSession('');setSessions([]);setObservation(null)}}>{machines.map((m,index)=><option key={m.machine_id} value={m.machine_id}>{advanced?m.machine_id:m.name||'Navegador '+(index+1)}</option>)}</select></label><label>Trabalho<select value={work?.work_item_id||''} disabled={busy||effects.pending.length>0||!effects.ready} onChange={e=>{setWorkId(e.target.value);setSession('');setObservation(null)}}><option value="">Selecione um trabalho autorizado</option>{jobs.map(w=><option key={w.work_item_id} value={w.work_item_id}>{w.objective}</option>)}</select></label></div>}
   {!work&&<p>{advanced?'Um WorkItem com Grant de navegador ativo é necessário para operar esta máquina.':'Este navegador ainda precisa de acesso autorizado. Confira a configuração do Dot.'}</p>}
   <div className="sw-browser-controls"><label>Perfil de rede<select value={profile||machine?.profiles?.[0]?.name||''} disabled={disabled} onChange={e=>setProfile(e.target.value)}>{machine?.profiles?.map(p=><option key={p.name} value={p.name}>{p.name}</option>)}</select></label><button disabled={disabled} onClick={()=>execute('session.list')}>Consultar sessões</button><button disabled={disabled} onClick={()=>execute('open')}>Abrir nova sessão</button></div>
   <label>Sessão existente<select value={session} disabled={disabled} onChange={e=>{setSession(e.target.value);setObservation(null)}}><option value="">Selecione</option>{session&&!sessions.some(s=>(s.session_id||s.id)===session)&&<option value={session}>{advanced?session:'Sessão selecionada'}</option>}{sessions.map((s,index)=><option key={s.session_id||s.id} value={s.session_id||s.id}>{s.title||s.url||(advanced?s.session_id||s.id:'Sessão '+(index+1))}</option>)}</select></label>
   <form onSubmit={e=>{e.preventDefault();void execute('navigate')}}><input aria-label="Endereço no perfil autorizado" placeholder="https://…" value={url} onChange={e=>setUrl(e.target.value)} disabled={disabled||!session}/><button disabled={disabled||!session||!url}>Navegar</button><button type="button" disabled={disabled||!session} onClick={()=>execute('observe')}>Observar página</button></form>
  </>}
  {error&&<p role="alert">{error}</p>}{advanced?<><WorkspacePending effects={effects} onObserved={value=>{const result=value.operation||value.result;if(result){setReceipt(result);if(result.state==='SUCCEEDED')project(result)}if(value.resolved){intent.current=null;setError('')}}}/><OperationReceipt value={receipt}/></>:effects.pending.length>0?<button onClick={onDiagnostics}>Conferir ação pendente</button>:null}
  {observation&&<article className="sw-browser-observation"><h4>{observation.title||'Observação da página'}</h4><small>Revisão {observation.revision} · {observation.url}</small><pre>{observation.semantic_summary||'Nenhum elemento interativo observado.'}</pre></article>}
 </section>;
}
