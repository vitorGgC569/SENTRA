import React,{useEffect,useState} from 'react';
import {X} from 'lucide-react';
import {WorkspaceFile} from './WorkspaceExplorer';
import {WorkspaceTerminal} from './WorkspaceTerminal';
import {BrowserPane} from './BrowserPane';
export function ConversationResource({resource,conversation,dot,bridge,onClose,visible=true,onConfigure,onDiagnostics}){
 const [inventory,setInventory]=useState(null),[error,setError]=useState('');
 useEffect(()=>{let alive=true;bridge({action:'workspace_inventory',project_id:dot.project_id,space_id:dot.space_id,dot_id:dot.canvas_root_dot_id||dot.dot_id}).then(v=>{if(alive)setInventory(v)}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[dot.dot_id]);
 const terminal=inventory?.resources?.terminals?.find(t=>t.id===resource.resourceId&&t.dot_id===dot.dot_id);
 return <aside className="shell-conversation-resource sentra-workspace" aria-label="Ferramenta deste trabalho"><header><strong>{resource.kind==='files'?resource.resourceId:resource.kind==='browser'?'Navegador':'Terminal'}</strong><button aria-label="Fechar ferramenta e manter a conversa" onClick={onClose}><X size={15}/></button></header>{error?<p role="alert">{error}</p>:resource.kind==='files'?<WorkspaceFile bridge={bridge} projectId={dot.project_id} path={resource.resourceId} visible={visible} fileScope={{space_id:dot.space_id,dot_id:dot.dot_id,conversation_id:conversation.conversation_id}}/>:resource.kind==='terminals'?terminal?<WorkspaceTerminal terminal={terminal} projectId={dot.project_id}/>:<p>Sessão indisponível. Nenhum processo foi criado.</p>:resource.kind==='browser'&&inventory?<BrowserPane advanced={false} dot={dot} conversation={conversation} bridge={bridge} visible={visible} onConfigure={onConfigure} onDiagnostics={onDiagnostics} layoutScope={inventory.layout_scope}/>:null}</aside>;
}
