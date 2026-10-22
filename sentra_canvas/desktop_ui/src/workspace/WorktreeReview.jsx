import React,{useEffect,useRef,useState} from 'react';
import {GitCompare,RefreshCw} from 'lucide-react';

const states={compatible:'Alterações compatíveis',conflict:'Conflito entre trabalhos',stale:'Os arquivos mudaram durante a consulta',needs_review:'Revisão manual necessária'};
export function WorktreeReview({bridge,scope,conversations,members,onProjectReview}){
 const [selected,setSelected]=useState([]),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const generation=useRef(0),key=JSON.stringify(scope);
 const choices=conversations.filter(c=>members.some(d=>d.dot_id===c.dot_id&&d.space_id===c.space_id));
 useEffect(()=>{generation.current++;setSelected([]);setResult(null);setBusy(false);setError('');return()=>{generation.current++}},[key]);
 async function inspect(){const ticket=++generation.current;setBusy(true);setError('');setResult(null);try{
  const value=await bridge({action:'dot_worktree_review',...scope,conversation_ids:selected});
  if(ticket===generation.current)setResult(value);
 }catch(e){if(ticket===generation.current)setError(e.message)}finally{if(ticket===generation.current)setBusy(false)}}
 return <section className="sw-review"><GitCompare size={28}/><h3>Revisão dos trabalhos</h3>
  <p>Confira se as alterações dos Dots podem ser combinadas. Esta consulta não publica nem modifica o projeto.</p>
  <fieldset disabled={busy}><legend>Conversas dos trabalhos · até 8</legend>{choices.length?choices.map(c=><label key={c.conversation_id}>
   <input type="checkbox" checked={selected.includes(c.conversation_id)} disabled={!selected.includes(c.conversation_id)&&selected.length>=8} onChange={e=>{setResult(null);setSelected(s=>e.target.checked?[...s,c.conversation_id]:s.filter(id=>id!==c.conversation_id))}}/>
   {members.find(d=>d.dot_id===c.dot_id)?.name} · {c.title||'Conversa'}
  </label>):<p>Nenhuma conversa de trabalho neste Canvas.</p>}</fieldset>
  <button disabled={busy||!selected.length} onClick={()=>void inspect()}><RefreshCw size={13}/>{busy?'Conferindo…':'Conferir alterações dos Dots'}</button>
  {error&&<p role="alert">{error}</p>}
  {result&&<div className="sw-review-result" role="status"><strong>{states[result.state]||'Resultado não confirmado'}</strong>
   {result.reason&&<p>{result.reason}</p>}{result.base_diverged&&<p>A base do projeto mudou. A integração exige uma decisão sobre a nova base.</p>}
   {result.worktrees?.map(item=><details key={item.worktree_id}><summary>{members.find(d=>d.dot_id===item.dot_id)?.name||'Dot'} · {item.state==='conflict'?'Conflito':item.changed?'Compatível nesta ordem':'Sem alterações'}</summary>{item.reason&&<pre>{item.reason}</pre>}<pre>{result.resources?.find(r=>r.dot_id===item.dot_id)?.diff_stat||'Sem diff de arquivos rastreados.'}</pre></details>)}
   {result.unchecked_worktrees>0&&<p>{result.unchecked_worktrees} trabalho(s) ainda não conferido(s) após o conflito.</p>}
   {result.skipped_conversations?.length>0&&<p>{result.skipped_conversations.length} conversa(s) sem trabalho Git isolado.</p>}
   <small>Prévia de alterações de texto rastreadas; confira também o comportamento do resultado.</small></div>}
  <button onClick={onProjectReview}>Abrir revisão do projeto principal</button>
 </section>;
}
