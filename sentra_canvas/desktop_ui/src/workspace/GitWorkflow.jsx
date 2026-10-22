import React,{useState} from 'react';
import {useWorkspaceEffects,WorkspacePending} from './useWorkspaceEffects';

const actions=[['git:commit','Criar commit'],['git:discard','Descartar alterações de arquivos'],['git:merge','Integrar no projeto principal'],['git:publish','Publicar branch no remoto'],['git:cleanup','Remover checkout já integrado']];
export function GitWorkflow({resource,scope,bridge,layoutScope,onRefresh,onConversation}){
 const review=resource.review,workflow=resource.workflow;
 const [files,setFiles]=useState([]),[action,setAction]=useState('git:commit'),[message,setMessage]=useState(''),[remote,setRemote]=useState(''),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const bound={project_id:scope.project_id,space_id:scope.space_id,dot_id:resource.dot_id,conversation_id:resource.conversation_id};
 const effects=useWorkspaceEffects(layoutScope,bound,bridge);
 const selectedFiles=files.filter(path=>review.files.some(f=>f.path===path));
 const ready=effects.ready&&!effects.pending.length&&!busy&&consent&&workflow?.capabilities.includes(action)&&(!['git:commit','git:discard'].includes(action)||selectedFiles.length>0)&&(action!=='git:commit'||message.trim())&&(action!=='git:publish'||remote);
 async function execute(){
  if(!ready)return;setBusy(true);setNotice('');
  try{
   const args={worktree_id:review.worktree_id,expected_snapshot_sha256:review.snapshot_sha256,...(['git:commit','git:discard'].includes(action)?{files:selectedFiles}:{}),...(action==='git:commit'?{message}:{}),...(action==='git:publish'?{remote}:{})};
   const result=await effects.run({action:'dot_computer_action',...bound,request_key:crypto.randomUUID(),request:{action:'machine_execute',machine_id:workflow.machine_id,work_item_id:workflow.work_item_id,capability_id:action,arguments:args}},'git:'+review.worktree_id);
   const operation=result.observation.operation||result.value;
   setNotice(result.observation.resolved&&operation.state==='SUCCEEDED'?'Etapa concluída e conferida. Atualize a revisão antes da próxima etapa.':'A etapa precisa de confirmação. Consulte o pedido preservado antes de continuar.');setConsent(false);onRefresh?.();
  }catch(error){setNotice(error.message+' Consulte o pedido antes de decidir uma nova ação.');setConsent(false)}finally{setBusy(false)}
 }
 return <details className="sw-git-workflow"><summary>{resource.branch} · arquivos novos, binários e etapas Git</summary>
  <p>HEAD {review.head.slice(0,12)} · projeto {review.main_head.slice(0,12)} · {review.main_clean?'projeto limpo':'projeto com alterações'}</p>
  <fieldset disabled={busy}><legend>Arquivos desta revisão</legend>{review.files.length?review.files.map(file=><details key={file.path}><summary><label><input type="checkbox" checked={files.includes(file.path)} disabled={!!file.review_blocked} onChange={e=>{setConsent(false);setFiles(s=>e.target.checked?[...s,file.path]:s.filter(p=>p!==file.path))}}/>{file.path} · {file.new?'novo':file.deleted?'excluído':file.binary?'binário':'alterado'}</label></summary>{file.review_blocked?<p role="alert">{file.review_blocked}</p>:<><p>{file.size_bytes} bytes · SHA-256 {file.sha256||'arquivo ausente'}</p>{file.diff_error&&<p>{file.diff_error}</p>}{file.diff!==undefined?<pre aria-label={'Diff por linhas de '+file.path}>{file.diff||'Sem diferença de linhas.'}</pre>:file.preview!==undefined?<pre>{file.preview}</pre>:file.binary?<p>Arquivo binário: revise o conteúdo no aplicativo apropriado antes de selecionar.</p>:null}</>}</details>):<p>Sem alterações locais.</p>}</fieldset>
  <label>Próxima etapa<select value={action} disabled={busy} onChange={e=>{setAction(e.target.value);setConsent(false)}}>{actions.map(([cap,label])=><option key={cap} value={cap}>{label}</option>)}</select></label>
  {action==='git:commit'&&<label>Mensagem do commit<input value={message} maxLength={2000} disabled={busy} onChange={e=>{setMessage(e.target.value);setConsent(false)}}/></label>}
  {action==='git:discard'&&<p>Substitui apenas arquivos de texto rastreados selecionados pela versão de HEAD. Rascunhos protegidos são preservados e receberão aviso de conflito.</p>}
  {action==='git:merge'&&<p>Avança o projeto principal para esta branch somente se a integração for direta e os dois checkouts estiverem limpos.</p>}
  {action==='git:publish'&&<label>Remoto configurado<select value={remote} onChange={e=>{setRemote(e.target.value);setConsent(false)}}><option value="">Escolher remoto revisado</option>{review.remotes.map(r=><option key={r.name} value={r.name}>{r.name} · {r.destination} · {r.url_sha256.slice(0,12)}</option>)}</select></label>}
  {action==='git:cleanup'&&<p>Remove o checkout limpo depois de conferir que todos os commits estão integrados no projeto principal. Arquivos ignorados também impedem a remoção. A branch e o histórico Git são preservados.</p>}
  <label><input type="checkbox" disabled={busy} checked={consent} onChange={e=>setConsent(e.target.checked)}/>Conferi esta revisão e autorizo solicitar apenas esta etapa ao SENTRA.</label>
  <button disabled={!ready} onClick={()=>void execute()}>{busy?'Consultando execução…':'Solicitar etapa autorizada'}</button>
  {!workflow?.capabilities.includes(action)&&<p>A conversa precisa preparar a capacidade desta etapa. <button onClick={()=>onConversation?.(resource.dot_id,{draft:'Quero revisar e preparar a etapa '+action+' da branch '+resource.branch+'. Confira a revisão e peça a autorização necessária antes de executar.'})}>Abrir conversa do Dot</button></p>}
  {notice&&<p role="status">{notice}</p>}<WorkspacePending effects={effects}/>
 </details>;
}
