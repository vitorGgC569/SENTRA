/* Owner-enabled collaboration. Only presentation maps cross the socket. */
(function(root){
 "use strict";
 function create({api,state,toast,drawEdges,refreshResources}){
  let session=null,task=null,workspace=null,generation=0,lastPresence=0;
  const notePositions=new Map();
  const principal=sessionStorage.getItem("sentra_collab_principal")||"user-"+crypto.randomUUID().replaceAll("-","");
  sessionStorage.setItem("sentra_collab_principal",principal);
  const peers=document.createElement("div");peers.className="collab-presence";
  peers.setAttribute("aria-label","Participantes do Canvas");document.getElementById("viewport").append(peers);
  const button=document.getElementById("show-collaboration");
  function writable(){
   if(session&&!session.status().writable)throw Error("Aguarde a conexão colaborativa ou desative a colaboração.");
   return !!session;
  }
  function present(values){
   peers.replaceChildren();
   for(const peer of values){
    if(!peer?.cursor||typeof peer.user?.id!=="string"||peer.user.id===principal)continue;
    const marker=document.createElement("span");marker.className="collab-cursor";
    marker.textContent=peer.user.id.slice(0,14);
    marker.style.left=(state.x+peer.cursor.x*state.scale)+"px";
    marker.style.top=(state.y+peer.cursor.y*state.scale)+"px";peers.append(marker);
   }
  }
  function apply(value){
   if(!value||workspace!==state.ws)return;
   for(const node of state.nodes){
    const p=value.nodes[node.id];
    if(p&&state.move?.n?.id!==node.id){
     const element=document.querySelector('[data-node="'+node.id+'"]');
     for(const [key,style] of [["x","left"],["y","top"],["width","width"],["height","height"]]){
      node[key]=p[key];if(element)element.style[style]=p[key]+"px";
     }
    }
    if(node.kind==="note"&&typeof value.notes[node.id]==="string"){
     node.body=value.notes[node.id];
     const editor=document.querySelector('[data-note="'+node.id+'"]');
     if(editor&&editor.value!==node.body){
      const bookmark=notePositions.get(node.id);editor.value=node.body;
      if(document.activeElement===editor&&bookmark&&session?.status().synced){
       const start=session.resolveNotePosition(node.id,bookmark.start);
       const end=session.resolveNotePosition(node.id,bookmark.end);
       if(start!==null&&end!==null)editor.setSelectionRange(start,end);
      }
     }
    }
   }
   drawEdges();
  }
  async function stop(){
   generation++;
   const oldTask=task,oldWorkspace=workspace;
   session?.disconnect();session=null;task=null;workspace=null;peers.replaceChildren();notePositions.clear();
   if(button){button.classList.remove("active");button.setAttribute("aria-pressed","false");}
   if(oldTask)await api("/api/collab/disable",{ws:oldWorkspace,work_item_id:oldTask,principal_id:principal});
  }
  async function start(){
   if(!state.ws)throw Error("Selecione um workspace primeiro.");
   if(session){await stop();toast("Colaboração desativada.");return;}
   const runtime=root.SentraCollabRuntime;
   if(!runtime||!root.SentraCollab)throw Error("Runtime de colaboração indisponível.");
   const myGeneration=++generation,selectedWorkspace=state.ws;workspace=selectedWorkspace;
   const prepared=await api("/api/collab/prepare",{ws:selectedWorkspace,principal_id:principal});
   if(myGeneration!==generation||selectedWorkspace!==state.ws){
    await api("/api/collab/disable",{ws:selectedWorkspace,work_item_id:prepared.work_item_id,principal_id:principal});return;
   }
   task=prepared.work_item_id;
   let seeded=false;
   session=root.SentraCollab.connect({workspaceId:selectedWorkspace,url:prepared.url,...runtime,
    getToken:async()=>{
     const value=await api("/api/collab/session",{ws:selectedWorkspace,work_item_id:prepared.work_item_id,principal_id:principal,permission:"write"});
     if(myGeneration!==generation)throw Error("workspace changed");return value.token;
    },
    onChange:value=>{
     if(myGeneration!==generation)return;
     apply(value);
     if(!seeded&&session?.status().synced&&session.status().writable){
      seeded=true;let noteCount=Object.keys(value.notes).length;
      for(const node of state.nodes.slice(0,512)){
       if(!Object.hasOwn(value.nodes,node.id))session.setNode(node.id,{x:node.x,y:node.y,width:node.width,height:node.height});
       if(node.kind==="note"&&!Object.hasOwn(value.notes,node.id)&&noteCount++<128)session.setNote(node.id,node.body);
      }
      session.clearHistory();
     }
    },
    onPresence:values=>{if(myGeneration===generation)present(values);},
    onDisconnected:()=>{peers.replaceChildren();if(myGeneration===generation)toast("Colaboração desconectada. Reconectando…");},
    onError:()=>{
     if(myGeneration!==generation)return;
     stop().catch(()=>{}).finally(()=>refreshResources().catch(()=>{}));
     toast("A sessão colaborativa foi encerrada. Recuperando o último estado confirmado.","error");
    }
   });
   button?.classList.add("active");button?.setAttribute("aria-pressed","true");
   toast("Conectando colaboração neste workspace.");
  }
  const viewport=document.getElementById("viewport");
  const remember=event=>{
   const editor=event.target;
   if(!editor.matches?.("[data-note]")||!session?.status().synced)return;
   const id=editor.dataset.note;
   const start=session.notePosition(id,editor.selectionStart),end=session.notePosition(id,editor.selectionEnd);
   if(start&&end)notePositions.set(id,{start,end});
  };
  viewport.addEventListener("keyup",remember);viewport.addEventListener("click",remember);
  viewport.addEventListener("input",event=>{
   const editor=event.target;if(!editor.matches?.("[data-note]")||!session)return;
   try{if(writable()){session.setNote(editor.dataset.note,editor.value);remember(event);}}
   catch(error){toast(error.message,"error");}
  });
  return Object.freeze({toggle:start,stop,active:()=>!!session,status:()=>session?.status()||{authenticated:false,synced:false,writable:false,closed:true},
   node(node){if(!writable())return false;session.setNode(node.id,{x:node.x,y:node.y,width:node.width,height:node.height});return true;},
   note(id,text){if(!writable())return false;session.setNote(id,text);return true;},
   presence(point){if(!session?.status().synced||Date.now()-lastPresence<80)return;lastPresence=Date.now();session.setPresence({cursor:point});},
   undo(){if(writable())session.undo();},redo(){if(writable())session.redo();}
  });
 }
 root.SentraCollaborationPanel=Object.freeze({create});
})(globalThis);
