import React,{useState} from 'react';
import {TerminalSquare,MessageCircle,Globe,Monitor,ArrowRight,ShieldCheck} from 'lucide-react';
import {Modal} from '../primitives';
import {sessionTools,ACCESS_CHOICES} from './presentation';
import {sessionTitle} from './continuity';

export function NewSession({member,tools,terminals,sessionNames={},busy,error,advanced,onClose,onTool,onOpen,onConversation,onPane,onAccess}){
 const [showTools,setShowTools]=useState(false);
 const [purpose,setPurpose]=useState('');
 const mine=terminals.filter(t=>t.dot_id===member.dot_id);
 return <Modal open onOpenChange={onClose} busy={busy} title="Nova sessão" description={'Escolha como trabalhar com '+member.name+'.'} className="sw-session-dialog sw-session-dialog-refined">
  <div className="sw-session-choices">
   <button onClick={onConversation}><MessageCircle size={18}/><span><strong>Conversa</strong><small>Continuar com {member.name}.</small></span></button>
   <button aria-label="Abrir terminal" onClick={()=>setShowTools(v=>!v)} aria-expanded={showTools}><TerminalSquare size={18}/><span><strong>Terminal</strong><small>Escolher uma ferramenta de linha de comando.</small></span></button>
   <button onClick={()=>onPane('browser')}><Globe size={18}/><span><strong>Navegador</strong><small>Abrir o navegador autorizado deste Dot.</small></span></button>
   <button onClick={()=>onPane('computer')}><Monitor size={18}/><span><strong>Computador</strong><small>Abrir o ambiente conectado ao Dot.</small></span></button>
  </div>
  {!!mine.length&&<section className="sw-session-existing"><h3>Sessões deste Dot</h3>{mine.slice(0,6).map(t=><button key={t.id} onClick={()=>onOpen(t)}><TerminalSquare size={14}/><span>{sessionTitle(t,sessionNames,member.name)}</span><small>{t.tool||t.shell} · {t.status==='running'?'Em execução':t.status==='preview'?'Simulação':'Ver sessão'}</small></button>)}{mine.length>6&&<button onClick={()=>onPane('terminals')}>Ver todas as sessões</button>}</section>}
  {showTools&&<section className="sw-session-tools"><h3>Ferramenta do terminal</h3><label className="sw-session-purpose">Nome da sessão <span className="sw-session-optional">(opcional)</span><input aria-label="Nome do trabalho da sessão" value={purpose} onChange={e=>setPurpose(e.target.value)} maxLength={80} placeholder="Ex.: Revisão de login"/></label><p>O SENTRA verifica o ambiente antes de abrir a ferramenta.</p>{sessionTools(tools).map(t=><button key={t.id} disabled={busy||!t.installed} onClick={()=>onTool(t.id,purpose.trim())}><TerminalSquare size={15}/><span><strong>{t.title||t.name||t.id}</strong><small>{t.installed?'Abrir no ambiente do Dot':'Disponível após instalação'}</small></span>{t.installed&&<ArrowRight size={14}/>}</button>)}{!sessionTools(tools).length&&<p>Nenhuma ferramenta informada pelo ambiente.</p>}</section>}
  <button className="sw-session-access" aria-label="Configurar acesso do Dot" onClick={onAccess}><ShieldCheck size={15}/><span>Acesso de {member.name}</span><small>Revisar permissões</small></button>
  {error&&<p role="alert">{error}</p>}
  {advanced&&<p className="sw-dialog-note">Uma sessão aberta não confirma login nem conclusão. Fechar a aba mantém o processo.</p>}
 </Modal>;
}

export function WorkspaceAccess({member,conversation,bridge,scope,advanced,busy,run,onClose,onConversation}){
 const [choice,setChoice]=useState('read'),[stage,setStage]=useState('choose'),[message,setMessage]=useState(''),[current,setCurrent]=useState(null);
 React.useEffect(()=>{let alive=true;if(conversation)bridge({action:'access_status',project_id:scope.project_id,space_id:scope.space_id,conversation_id:conversation.conversation_id}).then(v=>{if(alive)setCurrent(v)}).catch(e=>{if(alive)setMessage(e.message)});return()=>{alive=false}},[conversation?.conversation_id,member.dot_id]);
 async function allow(){try{setMessage('');const result=await run('dot_canvas_access',{member_dot_id:member.dot_id,conversation_id:conversation.conversation_id,profile:choice,approved:true});if(result){setStage('done');setMessage(choice==='none'?'Este acesso foi desativado.':'Acesso configurado. Você pode começar a trabalhar.')}else setMessage('O acesso não foi confirmado. Feche este painel e confira o diagnóstico antes de tentar outra ação.')}catch(e){setMessage(e.message)}}
 return <Modal open onOpenChange={onClose} busy={busy} title={'Acesso de '+member.name} description="Defina o acesso aos arquivos e comandos desta conversa." className="sw-session-dialog sw-session-dialog-refined">
  {!conversation?<div className="sw-access-choice"><p>Abra a conversa deste Dot para configurar um acesso vinculado a ela.</p><button onClick={onConversation}>Abrir conversa</button></div>:stage==='done'?<div className="sw-access-done"><ShieldCheck size={30}/><h3>{message}</h3><p>As ações continuam sendo verificadas pelo SENTRA.</p><button onClick={onClose}>Concluir</button></div>:<>
   {stage==='choose'?<><fieldset className="sw-access-choice"><legend>Como este Dot pode ajudar?</legend>{Object.entries(ACCESS_CHOICES).map(([id,item])=><label key={id}><input type="radio" name="workspace-access" value={id} checked={choice===id} onChange={()=>setChoice(id)}/><span><strong>{item.title}</strong><small>{item.description}</small></span></label>)}</fieldset><p className="sw-dialog-note">Esta escolha substitui o acesso local a arquivos e comandos desta conversa. Não libera outros Dots nem acesso a todo o computador.</p><button className="sw-primary" onClick={()=>setStage('confirm')}>Revisar acesso<ArrowRight size={14}/></button></>:<div className="sw-access-confirm"><ShieldCheck size={24}/><h3>{ACCESS_CHOICES[choice].title}</h3><p>{ACCESS_CHOICES[choice].description}</p><p>Dot: <strong>{member.name}</strong><br/>Escopo: <strong>projeto desta conversa</strong></p><div><button disabled={busy} onClick={()=>setStage('choose')}>Voltar</button><button className="sw-primary" disabled={busy} onClick={()=>void allow()}>{busy?'Configurando…':choice==='none'?'Confirmar desativação':'Permitir este acesso'}</button></div></div>}
   {advanced&&<details className="sw-access-technical"><summary>Detalhes técnicos</summary><pre>{JSON.stringify(current,null,2)}</pre></details>}{message&&<p role="alert">{message}</p>}
  </>}
 </Modal>;
}
