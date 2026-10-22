import React,{useEffect,useRef,useState} from 'react';
import {FileText,Pencil,Save,RefreshCw} from 'lucide-react';
import {DocumentCodeEditor} from '../document-code-editor';
import {useWorkspaceEffects} from './useWorkspaceEffects';
import {FileDraftWriter,draftFor,editorConflict,savedDraftMatches,fileSaveRequest} from './file-editor-state';
import {watchWorkspaceFile} from './file-observer';

/** File presentation only; all physical saves go through central machine admission. */
export function WorkspaceEditor({bridge,projectId,path,fileScope={},visible=true,onRequestAccess,onChooseExisting,onRemoveReference}){
 const [file,setFile]=useState(null),[draft,setDraft]=useState(null),[busy,setBusy]=useState(false);
 const [error,setError]=useState(''),[message,setMessage]=useState(''),[draftStatus,setDraftStatus]=useState('');
 const [draftError,setDraftError]=useState(''),[epoch,setEpoch]=useState(0),[compared,setCompared]=useState(false);
 const alive=useRef(true),writer=useRef(null),draftRef=useRef(null),pin=useRef(fileScope.execution_workspace_id),inAction=useRef(false);
 const callbacks=useRef({bridge,onRequestAccess});callbacks.current={bridge,onRequestAccess};
 const scope={project_id:projectId,space_id:fileScope.space_id,dot_id:fileScope.dot_id,conversation_id:fileScope.conversation_id};
 const effects=useWorkspaceEffects(file?.layout_scope,scope,bridge);
 const slot=file?'file:'+file.scope:'';
 const pending=effects.pending.filter(row=>row.slot===slot);
 const conflict=file&&editorConflict(file,draft);
 const canSave=!!draft&&file?.editable&&file.editor&&!conflict&&!busy&&!draftError&&effects.ready&&!effects.pending.length&&draft.content!==file.content;
 function fields(){return {...scope,path,...(pin.current?{execution_workspace_id:pin.current}:{})}}
 function remember(value){draftRef.current=value;setDraft(value);writer.current?.schedule(value)}
 async function load(){
  setError('');
  try{
   const value=await callbacks.current.bridge({action:'workspace_file_get',...fields()});
   if(!alive.current)return;
   writer.current?.close();pin.current=value.execution_workspace_id;
   const selected=fields();
   writer.current=new FileDraftWriter((body,revision)=>callbacks.current.bridge({action:'workspace_file_draft_save',...selected,draft:body,expected_revision:revision}),value.revision,
    (state,issue)=>{if(alive.current){setDraftStatus(state);if(issue)setDraftError(issue.message)}},value.draft);
   setFile(value);draftRef.current=value.draft;setDraft(value.draft);setDraftError('');setCompared(false);setEpoch(n=>n+1);
   setDraftStatus(value.draft?'saved':'');
  }catch(issue){if(alive.current)setError(issue.message)}
 }
 useEffect(()=>{
  alive.current=true;void load();
  const flush=()=>void writer.current?.flush().catch(()=>{});
  const leave=event=>{if(writer.current&&(writer.current.pending!==undefined||writer.current.running||writer.current.error)){event.preventDefault();event.returnValue='';}};
  window.addEventListener('blur',flush);document.addEventListener('visibilitychange',flush);window.addEventListener('beforeunload',leave);
  return()=>{alive.current=false;writer.current?.close();window.removeEventListener('blur',flush);document.removeEventListener('visibilitychange',flush);window.removeEventListener('beforeunload',leave)};
 },[]);
 useEffect(()=>{
  if(!file||!visible)return;
  return watchWorkspaceFile(bridge,fields(),current=>{
   if(!alive.current||inAction.current)return;
   const changed=writer.current?.observe(current,draftRef.current);
   setFile(current);
   if(changed){draftRef.current=changed.draft;setDraft(changed.draft);setEpoch(n=>n+1);setMessage('Rascunho atualizado por outra aba ou janela.');setDraftStatus(changed.draft?'saved':'')}
  },issue=>{if(alive.current)setFile(old=>({...old,file_error:issue.message}))});
 },[file?.scope,visible,bridge]);
 useEffect(()=>setCompared(false),[file?.sha256,file?.file_error]);
 async function refresh(){try{const current=await callbacks.current.bridge({action:'workspace_file_get',...fields()});if(alive.current)setFile(current)}catch(issue){if(alive.current)setError(issue.message)}}
 async function finish(operation){
  const current=await callbacks.current.bridge({action:'workspace_file_get',...fields()});
  if(!alive.current)return;
  setFile(current);
  if(operation?.state!=='SUCCEEDED'){setMessage('O salvamento não foi concluído. Seu rascunho foi preservado.');return}
  const value=draftRef.current;
  if(await savedDraftMatches(operation,current,value)){
   await writer.current.commit(null);
   if(alive.current){draftRef.current=null;setDraft(null);setDraftStatus('');setMessage('Arquivo salvo e conferido.');setEpoch(n=>n+1)}
  }else setMessage('O pedido foi concluído. O arquivo ou seu rascunho mudou depois; compare antes de continuar.');
 }
 async function save(){
  if(!canSave||inAction.current)return;inAction.current=true;setBusy(true);setError('');setMessage('');
  try{
   // Persist the exact draft before the first physical request, then freeze edits.
   await writer.current.commit(draftRef.current);
   const current=draftRef.current;
   const request=fileSaveRequest(scope,{...file,execution_workspace_id:pin.current},current,path,crypto.randomUUID());
   const result=await effects.run(request,slot);
   if(!alive.current)return;
   if(result.observation.resolved)await finish(result.observation.operation||result.value);
   else setMessage('Salvamento aguardando confirmação. Consulte o pedido; ele não será repetido.');
  }catch(issue){if(alive.current)setError(issue.message+' Seu rascunho foi preservado. Consulte a confirmação antes de salvar novamente.')}
  finally{inAction.current=false;if(alive.current)setBusy(false)}
 }
 async function inspect(row){
  if(inAction.current)return;inAction.current=true;setBusy(true);setError('');
  try{const result=await effects.inspect(row);if(result.resolved)await finish(result.operation||result.result);else setMessage('O resultado permanece incerto. Nenhuma ação foi reenviada.')}
  catch(issue){if(alive.current)setError(issue.message)}finally{inAction.current=false;if(alive.current)setBusy(false)}
 }
 async function discard(){
  if(inAction.current||pending.length)return;inAction.current=true;setBusy(true);setError('');
  try{await writer.current.commit(null);if(alive.current){draftRef.current=null;setDraft(null);setDraftStatus('');setMessage('Rascunho descartado. O arquivo não foi alterado.');await refresh()}}
  catch(issue){if(alive.current)setError(issue.message)}finally{inAction.current=false;if(alive.current)setBusy(false)}
 }
 async function rebase(){
  if(!compared||busy||pending.length)return;
  remember({...draftRef.current,base_content:file.content,base_sha256:file.sha256});setCompared(false);
  setMessage('Seu texto foi mantido sobre a versão conferida. Revise antes de salvar.');
 }
 async function copyDraft(){try{await navigator.clipboard.writeText(draftRef.current.content);setMessage('Rascunho copiado.')}catch{setError('Não foi possível copiar. Selecione e copie o texto no editor.')}}
 return <section className="sw-file-preview sw-file-editor">
  <header><FileText size={13}/><span title={path}>{path}</span><small>{file?.branch||'Projeto'}</small><div>
   <button aria-label="Conferir versão do arquivo" disabled={busy} onClick={refresh}><RefreshCw size={13}/></button>
   {!draft?<button disabled={!file?.editable||busy} onClick={()=>remember(draftFor(file))}><Pencil size={13}/>Editar</button>:<><button disabled={busy||!!pending.length} onClick={discard}>Descartar rascunho</button><button className="sw-primary" disabled={!canSave} onClick={save}><Save size={13}/>Salvar</button></>}
  </div></header>
  {error&&<div role="alert" className="sw-file-notice"><p>{error}</p>{!file&&<><p>A referência e os rascunhos protegidos foram preservados. Consultar novamente não recria o trabalho.</p><button disabled={busy} onClick={()=>void load()}>Consultar recurso existente</button>{onChooseExisting&&<button onClick={onChooseExisting}>Escolher outro arquivo</button>}{onRemoveReference&&<button onClick={onRemoveReference}>Remover esta aba</button>}</>}</div>}
  {effects.error&&<p role="alert" className="sw-file-notice">Não foi possível consultar o diário de salvamento. {effects.error}</p>}
  {draftError&&<div className="sw-file-notice" role="alert"><p>{draftError} Seu texto continua no editor.</p><button onClick={copyDraft}>Copiar meu texto</button><button disabled={busy} onClick={()=>void load()}>Carregar rascunho guardado</button></div>}
  {pending.map(row=><div className="sw-file-notice" role="status" key={row.request_key}>Salvamento aguardando confirmação.<button disabled={busy||!!effects.inspecting} onClick={()=>inspect(row)}>Consultar sem reenviar</button></div>)}
  {effects.pending.length>pending.length&&draft&&<p className="sw-file-notice">Há outra ação sem confirmação neste Canvas. Confira o diagnóstico antes de salvar.</p>}
  {message&&<p role="status" className="sw-file-notice">{message}</p>}
  {conflict&&<details className="sw-file-conflict" open><summary>O arquivo mudou. Seu rascunho foi preservado.</summary>{file.file_error?<p>O arquivo não está disponível neste trabalho. {file.file_error}</p>:<><p>Versão atual no disco:</p><pre>{file.content}</pre><label><input type="checkbox" checked={compared} onChange={e=>setCompared(e.target.checked)}/>Conferi as alterações atuais</label><button disabled={!compared||busy||!!pending.length||!file.editable} onClick={rebase}>Manter meu texto sobre esta versão</button></>}</details>}
  {!file?<p role="status">Abrindo arquivo…</p>:draft?<div className="sw-file-editor-code"><DocumentCodeEditor key={epoch} content={draft.content} language={path.split('.').at(-1)} readOnly={busy} initialSelection={{anchor:draft.anchor,head:draft.head}} onSave={()=>void save()}
   onChange={content=>{if(draftRef.current)remember({...draftRef.current,content,anchor:Math.min(draftRef.current.anchor,content.length),head:Math.min(draftRef.current.head,content.length)})}}
   onCursor={(anchor,head)=>{if(draftRef.current)remember({...draftRef.current,anchor,head})}}/></div>:file.file_error?<p role="alert" className="sw-file-notice">Não foi possível abrir o arquivo. {file.file_error}</p>:<div className="sw-code-lines">{String(file.content??'').split('\n').map((line,i)=><div key={i}><span aria-hidden>{i+1}</span><code>{line||' '}</code></div>)}</div>}
  {draft&&<footer><span role="status">{draftStatus==='saved'?'Rascunho protegido no host':draftStatus==='error'?'Rascunho ainda não guardado':'Guardando rascunho…'}</span>{!file?.editor&&<span>Autorize a edição pela conversa do Dot. {onRequestAccess&&<button onClick={onRequestAccess}>Abrir conversa</button>}</span>}<small>Ctrl/⌘ S para salvar</small></footer>}
 </section>;
}
