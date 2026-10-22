import React,{useEffect,useRef,useState} from 'react';
import {Globe,TerminalSquare,PanelRightOpen} from 'lucide-react';
import {ActionMenu} from './primitives';
import {conversationResources,newlyObservedTerminal} from './workspace/conversation-resources';
import {sessionTitle} from './workspace/continuity';

export function ConversationTools({scope,dot,bridge,onResource}){
 const [resources,setResources]=useState({terminals:[],browser:false}),[names,setNames]=useState({});
 const callback=useRef(onResource);callback.current=onResource;
 useEffect(()=>{
  if(!dot)return;
  let alive=true,reading=false,seen=null;
  const load=async()=>{
   if(reading||document.hidden)return;reading=true;
   try{
    const inventory=await bridge({action:'dot_computer_get',...scope,dot_id:dot.dot_id});
    if(!alive)return;
    const current=conversationResources(inventory,dot),added=newlyObservedTerminal(seen,current.terminals);
    seen=new Set(current.terminals.map(t=>t.id));setResources(current);
    if(added&&!document.querySelector('[role=dialog]')&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName))callback.current?.({...scope,kind:'terminals',resourceId:added.id,automatic:true});
   }catch{/* A missing inventory never creates a substitute session. */}finally{reading=false}
  };
  void load();const timer=setInterval(load,4000);
  bridge({action:'workspace_presentation_get',project_id:scope.project_id,space_id:scope.space_id,dot_id:dot.canvas_root_dot_id||dot.dot_id}).then(v=>{if(alive)setNames(v.profile?.sessionNames||{})}).catch(()=>{});
  return()=>{alive=false;clearInterval(timer)};
 },[scope.project_id,scope.space_id,scope.conversation_id,dot?.dot_id]);
 const items=[...resources.terminals.map(t=>({label:sessionTitle(t,names,dot.name),icon:<TerminalSquare size={14}/>,action:()=>onResource?.({...scope,kind:'terminals',resourceId:t.id})})),...(resources.browser?[{label:'Navegador deste Dot',icon:<Globe size={14}/>,action:()=>onResource?.({...scope,kind:'browser'})}]:[])];
 return items.length?<ActionMenu label="Ferramentas deste trabalho" trigger={<button type="button" className="icon-button" aria-label="Ferramentas deste trabalho" title="Ferramentas deste trabalho"><PanelRightOpen size={15}/></button>} items={items}/>:null;
}
