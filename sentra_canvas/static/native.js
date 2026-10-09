"use strict";
/* SENTRA native graph UI: authored independently for the SENTRA application. */
const $ = s=>document.getElementById(s);
const safe = v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const qp=new URLSearchParams(location.hash.slice(1));
if(qp.get("token")){sessionStorage.setItem("sentra_native_token",qp.get("token"));history.replaceState(null,"",location.pathname);}
const token=sessionStorage.getItem("sentra_native_token");
if(location.pathname==="/canvas"){
 document.documentElement.classList.add("canvas-web");
 const label=document.querySelector(".logo .version");if(label)label.textContent="WEB";
}
const state={
  ws:null,all:[],detail:null, nodes:[],links:[], selected:null, tool:"select",linkFrom:null,
  x:55,y:55,scale:1,move:null,space:false,cursors:{},polling:false,loading:false,
  integrations:[],models:[],fullscreen:null
};
let toastTimer=null, modalKind=null, modalAfter=null, modalRequest=null,modalSending=false;
let graphFrame=null;
const overlayFocus=new WeakMap();
function activeOverlay(){return [$("modal-shade"),$("command-overlay")].find(n=>n&&!n.hidden);}
function overlayControls(container){return [...container.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')]
 .filter(n=>!n.disabled&&n.tabIndex>=0&&n.getClientRects().length&&!n.closest('[hidden],[inert]'));}
function beginOverlayFocus(container){
 if(!overlayFocus.has(container))overlayFocus.set(container,{previous:document.activeElement,inert:$("app").inert});
 $("app").inert=true;
}
function endOverlayFocus(container){
 const saved=overlayFocus.get(container);overlayFocus.delete(container);if(!saved)return;
 $("app").inert=saved.inert;
 const previous=saved.previous;
 if(previous?.isConnected&&!previous.closest('[hidden],[inert]'))previous.focus();
 else $("viewport")?.focus();
}
document.addEventListener("keydown",e=>{
 const overlay=activeOverlay();if(!overlay||e.key!=="Tab")return;
 const controls=overlayControls(overlay),first=controls[0],last=controls.at(-1);
 if(!first){e.preventDefault();const dialog=overlay.querySelector('[role="dialog"]');if(dialog){dialog.tabIndex=-1;dialog.focus();}return;}
 if(e.shiftKey&&(document.activeElement===first||!overlay.contains(document.activeElement))){e.preventDefault();last.focus();}
 else if(!e.shiftKey&&(document.activeElement===last||!overlay.contains(document.activeElement))){e.preventDefault();first.focus();}
},true);
document.addEventListener("focusin",e=>{
 const overlay=activeOverlay();if(overlay&&!overlay.contains(e.target))overlayControls(overlay)[0]?.focus();
},true);
const terminalViews=new Map();
const collaboration=window.SentraCollaborationPanel?.create({api,state,toast,drawEdges,refreshResources});
$("show-collaboration")?.addEventListener("click",guarded(()=>collaboration?.toggle()));
$("collab-undo")?.addEventListener("click",guarded(()=>collaboration?.undo()));
$("collab-redo")?.addEventListener("click",guarded(()=>collaboration?.redo()));
$("show-machines")?.addEventListener("click",guarded(() =>
 window.SentraMachinePanel.open({api,state,toast,requireWS})));
$("show-center")?.addEventListener("click",guarded(() =>
 window.SentraCenterPanel.open({api,state,toast,requireWS,
   machines:()=>window.SentraMachinePanel.open({api,state,toast,requireWS})})));
function toast(message,tone="info"){
 const stack=$("toast");if(!stack)return;
 const card=document.createElement("div");card.className="halo-toast";
 card.dataset.tone=["error","success"].includes(tone)?tone:"info";
 const body=document.createElement("span");body.className="toast-message";body.textContent=String(message);
 const close=document.createElement("button");close.type="button";close.textContent="×";
 close.setAttribute("aria-label","Dispensar notificação");
 close.addEventListener("click",()=>card.remove());
 card.append(body,close);stack.prepend(card);
 while(stack.children.length>4)stack.lastElementChild.remove();
 setTimeout(()=>card.remove(),tone==="error"?8500:4700);
}
async function api(path,data){
  const headers={"Authorization":"Bearer "+token};
  if(data!==undefined)headers["Content-Type"]="application/json";
  const response=await fetch(path,{
    method:data===undefined?"GET":"POST",headers,cache:"no-store",
    body:data===undefined?undefined:JSON.stringify(data)
  });
  let payload;try{payload=await response.json();}catch{payload={error:"Resposta inválida do servidor"};}
  if(!response.ok)throw new Error(payload.error||"HTTP "+response.status);
  return payload;
}
function guarded(handler){return (...args)=>Promise.resolve().then(()=>handler(...args)).catch(err=>toast(err.message||String(err),"error"));}
function requireWS(){if(!state.ws)throw Error("Crie ou selecione um workspace primeiro.");return state.ws;}
function worldAt(sx,sy){return{x:(sx-state.x)/state.scale,y:(sy-state.y)/state.scale};}
function centerWorld(){
 const v=$("viewport"),r=v.getBoundingClientRect();
 return worldAt(r.width/2,r.height/2);
}
function setView(){
 $("world").style.transform="translate("+state.x+"px,"+state.y+"px) scale("+state.scale+")";
 $("grid-layer").style.backgroundPosition=
   state.x+"px "+state.y+"px";
 $("grid-layer").style.backgroundSize=
   (80*state.scale)+"px "+(80*state.scale)+","+(80*state.scale)+"px "+(80*state.scale)+","+
   (16*state.scale)+"px "+(16*state.scale)+","+(16*state.scale)+"px "+(16*state.scale);
 $("zoom-label").textContent=Math.round(state.scale*100)+"%";
 window.SentraFractalGrid?.setCamera(state.x,state.y,state.scale);
 scheduleVisibleNodes();
}
function scheduleVisibleNodes(){
 if(graphFrame!==null)return;
 graphFrame=requestAnimationFrame(()=>{graphFrame=null;renderVisibleNodes();});
}
function renderVisibleNodes(){
 const layer=$("node-layer");if(!layer||!window.SentraGraphView)return;
 const rect=$("viewport").getBoundingClientRect();
 const visible=window.SentraGraphView.visibleIDs(state.nodes,{x:state.x,y:state.y,scale:state.scale,width:rect.width,height:rect.height});
 const known=new Set(state.nodes.map(n=>n.id));
 for(const element of layer.querySelectorAll("[data-node]"))if(!known.has(element.dataset.node))element.remove();
 for(const node of state.nodes){
  const active=node.id===state.selected||node.id===state.move?.n?.id||node.id===state.fullscreen;
  let element=document.querySelector('[data-node="'+node.id+'"]');
  const item=resource(node.kind,node.resource_id);
  const terminal=node.kind==="terminal"?item:node.kind==="agent"?resource("terminal",item?.terminal_id):null;
  const retain=!!terminal;
  const show=visible.has(node.id)||active;
  const owner=node.kind==="terminal"?(state.detail?.agents||[]).find(agent=>agent.terminal_id===terminal?.id):null;
  const shape=node.kind+":"+(terminal?.id||"")+":"+(owner?.id||"");
  if(!show&&!retain){
   if(element&&!element.contains(document.activeElement))element.remove();
   continue;
  }
  if(element&&element.dataset.renderShape!==shape){element.remove();element=null;}
  if(!element){
   const template=document.createElement("template");template.innerHTML=nodeHtml(node);
   element=template.content.firstElementChild;element.dataset.renderShape=shape;layer.append(element);
  }
  element.style.left=node.x+"px";element.style.top=node.y+"px";
  element.style.width=node.width+"px";element.style.height=node.height+"px";
  element.style.visibility=show?"visible":"hidden";element.style.contentVisibility=show?"visible":"hidden";
  element.inert=!show;element.classList.toggle("selected",node.id===state.selected);
  element.tabIndex=show?0:-1;element.setAttribute("role","group");element.setAttribute("aria-label",node.title);
  if(terminal&&$("term-"+terminal.id))mountTerminal(terminal.id);
 }
 layer.dataset.visibleNodes=String(visible.size);layer.dataset.totalNodes=String(state.nodes.length);
}
function zoomTo(value,sx,sy){
 const v=$("viewport").getBoundingClientRect();
 sx??=v.width/2;sy??=v.height/2;
 const before=worldAt(sx,sy);
 state.scale=Math.max(.28,Math.min(2.25,value));
 state.x=sx-before.x*state.scale;
 state.y=sy-before.y*state.scale;
 setView();
}
function fitNodes(){
 if(!state.nodes.length){resetView();return;}
 let minx=Infinity,miny=Infinity,maxx=-Infinity,maxy=-Infinity;
 for(const n of state.nodes){
   minx=Math.min(minx,n.x);miny=Math.min(miny,n.y);
   maxx=Math.max(maxx,n.x+n.width);maxy=Math.max(maxy,n.y+n.height);
 }
 const bounds=$("viewport").getBoundingClientRect(),pad=110;
 const scale=Math.min(1.25,Math.max(.28,Math.min(
   (bounds.width-pad*2)/Math.max(250,maxx-minx),
   (bounds.height-pad*2)/Math.max(200,maxy-miny))));
 state.scale=scale;
 state.x=(bounds.width-(maxx+minx)*scale)/2;
 state.y=(bounds.height-(maxy+miny)*scale)/2;
 setView();
}
function resetView(){state.scale=1;state.x=55;state.y=65;setView();}
function nodeBy(id){return state.nodes.find(x=>x.id===id);}
function resource(kind,ident){const dict={terminal:"terminals",agent:"agents",team:"teams"};return state.detail?.[dict[kind]]?.find(r=>r.id===ident);}
async function loadWorkspaces(){
 state.all=await api("/api/workspaces");
 const filter=$("workspace-filter").value.toLowerCase().trim();
 $("ws-total").textContent=state.all.length;
 $("workspace-list").innerHTML=state.all.filter(w=>w.name.toLowerCase().includes(filter))
 .map(w=>'<button class="ws-item '+(w.id===state.ws?"selected":"")+'" data-ws="'+safe(w.id)+'"><span class="ws-icon">▣</span><span class="name">'+safe(w.name)+'</span><span class="ws-count">'+
   (w.id===state.ws&&state.detail?state.nodes.length:"")+'</span></button>').join("") ||
   '<p style="padding:6px 12px;color:#a7a7ae">Nenhum workspace encontrado</p>';
 if(!state.ws&&state.all.length)await openWorkspace(state.all[0].id);
 else if(!state.all.length)emptyView(true);
}
function emptyView(noWorkspaces=false){
 disposeTerminals();
 state.detail=null;state.nodes=[];state.links=[];
 $("node-layer").replaceChildren();window.SentraCablePhysics?.clear();$("edge-paths").replaceChildren();
 $("onboarding").hidden=false;
 $("onboarding-title").textContent=noWorkspaces?"Seu espaço de trabalho, do seu jeito":"Canvas pronto para começar";
 $("onboarding-description").textContent=noWorkspaces
 ?"Crie seu primeiro workspace. Depois abra terminais, inicie agentes e conecte suas tarefas."
 :"Adicione um terminal, agente, equipe ou nota na barra de ferramentas.";
 $("onboarding-action").textContent=noWorkspaces?"Criar workspace":"+ Adicionar terminal";
 $("current-project").textContent=noWorkspaces?"Seu espaço":state.detail?.workspace.name||"Canvas";
 $("canvas-count").textContent="0 nós";
}
async function openWorkspace(ws){
 if(state.loading)return;
 state.loading=true;
 try{
  if(state.ws!==ws)await collaboration?.stop();
  state.ws=ws;state.selected=null;state.linkFrom=null;state.cursors={};
  window.SentraCablePhysics?.clear();
  disposeTerminals();
  $("inspector").hidden=true;
  const info=await api("/api/graph?ws="+encodeURIComponent(ws));
  state.detail=info;state.nodes=info.nodes;state.links=info.links;
  $("current-project").textContent=info.workspace.name;
  $("project-state").textContent="LOCAL";
  $("runtime-status").textContent="SENTRA · ConPTY";
  $("canvas-count").textContent=state.nodes.length+" nós";
  $("onboarding").hidden=state.nodes.length>0;
   if(!state.nodes.length){
    $("onboarding-title").textContent="Um canvas para construir";
    $("onboarding-description").textContent="Abra seu primeiro terminal e adicione agentes para conectar o trabalho.";
    $("onboarding-action").textContent="+ Criar terminal";
  }
  renderNodes();
   fitNodes();
   // Keep terminals readable on entry; the fit button still shows the whole graph.
   if(state.scale<.8)zoomTo(.8);
  await loadWorkspacesNoRecursion();
 }finally{state.loading=false;}
}
async function loadWorkspacesNoRecursion(){
 state.all=await api("/api/workspaces");
 $("ws-total").textContent=state.all.length;
 const f=$("workspace-filter").value.trim().toLowerCase();
 $("workspace-list").innerHTML=state.all.filter(w=>w.name.toLowerCase().includes(f))
 .map(w=>'<button class="ws-item '+(w.id===state.ws?"selected":"")+'" data-ws="'+safe(w.id)+'"><span class="ws-icon">▣</span><span class="name">'+safe(w.name)+'</span><span class="ws-count">'+
 (w.id===state.ws?state.nodes.length:"")+'</span></button>').join("");
}
function nodeHtml(n){
 const item=resource(n.kind,n.resource_id);
  const agent=n.kind==="agent"?item:null;
  const owner=n.kind==="terminal"?(state.detail?.agents||[]).find(a=>a.terminal_id===n.resource_id):null;
  const terminal=n.kind==="agent"?resource("terminal",item?.terminal_id):n.kind==="terminal"?item:null;
  const running=terminal?.status==="running";
 let content="";
  if(terminal&&!owner){
    const id=terminal.id;
    content=(agent?'<div class="agent-session"><span title="'+safe(agent.model)+'">'+safe(agent.model)+'</span><span>'+safe(agent.role)+'</span></div>':"")+
    '<div class="term-output" id="term-'+safe(id)+'" aria-label="Terminal '+safe(n.title)+'">Carregando saída da sessão…</div>'+
    '<form class="term-form" data-terminal-form="'+safe(id)+'"><span class="term-prompt">❯</span>'+
    '<input data-terminal-input="'+safe(id)+'" '+(running?"":"disabled")+
    ' aria-label="Enviar para '+safe(n.title)+'" placeholder="'+(running?(terminal.shell==="sentra-cli"?"Digite uma instrução ou /model · /effort":"Digite um comando"):"Histórico da sessão · entrada indisponível")+'" autocomplete="off"></form>'+
   '<div class="node-foot"><span class="node-status"><i class="mini-dot '+(running?"":"off")+'"></i>'+
    '<span data-terminal-status="'+safe(id)+'">'+safe(terminal.status||"offline")+'</span></span>'+
    (terminal.shell==="sentra-cli"?'<span class="cli-controls"><button type="button" data-cli-command="/model" data-cli-terminal="'+safe(id)+'" title="Consultar modelo atual no SENTRA CLI">/model</button><button type="button" data-cli-command="/effort" data-cli-terminal="'+safe(id)+'" title="Consultar esforço atual do Codex">/effort</button></span>':'<span data-terminal-history="'+safe(id)+'">ConPTY</span>')+
    '<span>PID '+safe(terminal.pid||"—")+'</span></div>';
  }else if(owner){
    // One xterm per PTY: agent and terminal graph identities share a process.
    // Keep the terminal identity/ports available without a second resize writer.
    content='<div class="session-reference"><span class="agent-badge">SESSÃO COMPARTILHADA</span><strong>'+safe(owner.name)+'</strong><p>O terminal desta sessão está no nó do agente.</p><button class="node-cta" data-node-action="open-session">Abrir terminal ↗</button></div>'+
      '<div class="node-foot"><span>'+safe(terminal.status)+'</span><span>PID '+safe(terminal.pid||"—")+'</span></div>';
 }else if(n.kind==="agent"){
   content='<div class="agent-badge">AGENTE SENTRA</div>'+
   '<div class="agent-model">'+safe(item?.model||"Modelo não definido")+'</div>'+
   '<div class="agent-row"><span>Função</span><span>'+safe(item?.role||"worker")+'</span></div>'+
   '<div class="agent-row"><span>Estado</span><span>'+safe(item?.status||"configurado")+'</span></div>'+
    '<p class="session-empty">Sessão CLI não iniciada. Abra a conversa para usar o terminal real.</p>'+
    '<button class="node-cta" data-node-action="restart-agent">Abrir conversa</button>';
 }else if(n.kind==="team"){
   const members=state.detail?.agents||[];
   content='<div class="agent-badge">EQUIPE / ORQUESTRAÇÃO</div>'+
    '<div class="team-description">Coordenação, delegação e resultados em um só espaço.</div>'+
   '<div class="agent-row"><span>Agentes no workspace</span><span>'+members.length+'</span></div>'+
   '<button class="node-cta" data-node-action="delegate">Delegar tarefa →</button>';
 }else{
   content='<textarea class="note-text" data-note="'+safe(n.id)+'" placeholder="Escreva sua nota…">'+safe(n.body)+'</textarea>'+
   '<div class="node-foot">Nota do canvas · salva automaticamente</div>';
 }
 const status=n.kind==="terminal"?(item?.shell||"shell"):n.kind==="agent"?"agente":n.kind==="team"?"equipe":"nota";
  return '<article class="node '+safe(n.kind)+(terminal&&!owner?" has-terminal":"")+(state.selected===n.id?" selected":"")+'" data-node="'+safe(n.id)+'" '+
   '>'+
   '<div class="node-header" data-drag-header="'+safe(n.id)+'">'+
   '<span class="node-icon">'+({terminal:"▣",agent:"◇",team:"◎",note:"▤"}[n.kind])+'</span>'+
   '<span class="node-title">'+safe(n.title)+'</span><span class="node-type">'+safe(status)+'</span>'+
    (terminal&&!owner?'<button class="node-button" data-node-action="expand" title="Ampliar terminal (duplo clique)" aria-label="Ampliar terminal" aria-expanded="false">⛶</button>':"")+
    '<button class="node-button" data-node-action="inspect" title="Inspecionar" aria-label="Detalhes do nó">⋯</button></div>'+
   '<div class="node-body">'+content+'</div>'+
   '<span class="node-port input" data-port="input" title="Conectar entrada"></span>'+
   '<span class="node-port output" data-port="output" title="Conectar saída"></span>'+
   '<div class="node-resize" data-resize="'+safe(n.id)+'"></div></article>';
}
function renderSessionRail(){
 const host=$("workspace-sessions"),list=$("session-list");
 if(!host||!list)return;
 const groups=[
  {title:"AGENTES",kind:"agent",symbol:"◇"},
  {title:"TERMINAIS",kind:"terminal",symbol:"▣"}
 ];
 const entries=state.nodes.filter(n=>n.kind==="agent"||n.kind==="terminal");
 host.hidden=!state.ws||entries.length===0;
 $("session-total").textContent=entries.length;
 list.innerHTML=groups.map(group=>{
  const members=entries.filter(n=>n.kind===group.kind);
  if(!members.length)return "";
  return '<div class="session-group"><div class="session-group-heading">'+
    safe(group.title)+' <span>'+members.length+'</span></div>'+
    members.map(n=>{
     const resourceItem=resource(n.kind,n.resource_id);
     const terminal=n.kind==="terminal"?resourceItem:
       resource("terminal",resourceItem?.terminal_id);
     const live=terminal?.status==="running";
     const detail=n.kind==="agent"?resourceItem?.model:terminal?.shell;
     const provider=detail?.startsWith("sentra/codex/")?"CODEX":detail==="sentra-cli"?"SENTRA":detail?.startsWith("sentra/chatgpt-web/")?"WEB":String(detail||"");
     return '<button type="button" class="session-nav-item" data-session-node="'+safe(n.id)+'" title="'+safe(n.title)+'">'+
      '<span class="session-nav-symbol">'+safe(group.symbol)+'</span>'+
      '<span class="session-nav-name">'+safe(n.title)+'</span>'+
      '<span class="session-nav-provider">'+safe(provider)+'</span>'+
      '<i class="session-presence'+(live?" online":"")+'"></i></button>';
    }).join("")+'</div>';
 }).join("");
}
$("session-list").addEventListener("click",e=>{
 const button=e.target.closest("[data-session-node]");if(!button)return;
 const n=nodeBy(button.dataset.sessionNode);if(!n)return;
 const view=$("viewport").getBoundingClientRect();
 state.x=view.width/2-(n.x+n.width/2)*state.scale;
 state.y=view.height/2-(n.y+n.height/2)*state.scale;
 setView();showInspector(n);
 document.querySelectorAll(".node").forEach(node=>node.classList.toggle("selected",node.dataset.node===n.id));
});
function renderNodes(){
  const expanded=state.fullscreen;
  restoreTerminal(false);
 renderVisibleNodes();
 // CSP forbids HTML style attributes. Set layout only via safe CSSOM properties.
 for(const n of state.nodes){
   const element=document.querySelector('[data-node="'+n.id+'"]');
   if(!element)continue;
   element.style.left=n.x+"px";element.style.top=n.y+"px";
   element.style.width=n.width+"px";element.style.height=n.height+"px";
 }
 $("onboarding").hidden=state.nodes.length>0;
 renderSessionRail();
 $("canvas-count").textContent=state.nodes.length+" nós · "+state.links.length+" conexões";
 drawEdges();setView();
  const present=new Set((state.detail?.terminals||[]).filter(t=>$("term-"+t.id)).map(t=>t.id));
 for(const [id,view] of terminalViews)if(!present.has(id)){
   view.observer.disconnect();clearTimeout(view.resizeTimer);view.term.dispose();
   terminalViews.delete(id);delete state.cursors[id];
 }
 for(const id of present){mountTerminal(id);pollTerminal(id);}
  if(expanded)expandTerminal(expanded);
}

function terminalNode(id){
 const agent=(state.detail?.agents||[]).find(a=>a.terminal_id===id);
 return state.nodes.find(n=>agent?n.kind==="agent"&&n.resource_id===agent.id:n.kind==="terminal"&&n.resource_id===id);
}
function restoreTerminal(focus=true){
 const stage=$("terminal-stage"),element=stage.querySelector(".node");
 if(element){
  element.classList.remove("expanded");$("node-layer").append(element);
  const button=element.querySelector('[data-node-action="expand"]');
  if(button){button.setAttribute("aria-expanded","false");button.setAttribute("aria-label","Ampliar terminal");button.title="Ampliar terminal (duplo clique)";}
 }
 stage.hidden=true;state.fullscreen=null;$("app").classList.remove("terminal-expanded");
 if(focus&&element){const id=element.querySelector("[data-terminal-form]")?.dataset.terminalForm;terminalViews.get(id)?.term.focus();}
}
function expandTerminal(nodeId){
 if(state.fullscreen===nodeId){restoreTerminal();return;}
 restoreTerminal(false);
 const element=document.querySelector('[data-node="'+nodeId+'"]');
 if(!element?.classList.contains("has-terminal"))return;
 state.fullscreen=nodeId;state.selected=nodeId;
 element.classList.add("expanded");$("terminal-stage").append(element);$("app").classList.add("terminal-expanded");$("terminal-stage").hidden=false;
 const button=element.querySelector('[data-node-action="expand"]');
 button.setAttribute("aria-expanded","true");button.setAttribute("aria-label","Restaurar terminal");button.title="Restaurar terminal (Esc ou duplo clique)";
 const id=element.querySelector("[data-terminal-form]")?.dataset.terminalForm;
 terminalViews.get(id)?.term.focus();
}

function disposeTerminals(){
  restoreTerminal(false);
 for(const view of terminalViews.values()){
   view.observer.disconnect();clearTimeout(view.resizeTimer);view.term.dispose();
 }
 terminalViews.clear();state.cursors={};
}
function queueTerminalInput(view,data){
 // Preserve keyboard, IME, bracketed paste and terminal replies in wire order.
 if(view.term.options.disableStdin)return;
 for(let offset=0;offset<data.length;offset+=2048){
   const chunk=data.slice(offset,offset+2048);
   view.input=view.input.then(()=>api("/api/terminal/input",{
     ws:view.ws,id:view.id,data:chunk,
   })).catch(error=>toast(error.message));
 }
}
function mountTerminal(id){
 const screen=$("term-"+id);if(!screen)return null;
 let view=terminalViews.get(id);
 if(view){screen.replaceChildren(view.host);return view;}
 const host=document.createElement("div");host.className="terminal-emulator";
 screen.replaceChildren(host);
 const running=resource("terminal",id)?.status==="running";
 const term=new Terminal({fontFamily:'"Cascadia Mono", Consolas, monospace',fontSize:13,
   scrollback:4000,disableStdin:!running,cursorBlink:running,screenReaderMode:true,
   theme:{background:"#13181e",foreground:"#d8e2e6",cursor:"#9bd0c6",
          selectionBackground:"#43616c88"},allowProposedApi:false});
 const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open(host);
 view={id,ws:state.ws,host,term,fit,input:Promise.resolve(),pending:false,resizeTimer:null};
 const resize=()=>{
   if(!host.isConnected)return;
   if(host.closest(".node")?.style.visibility==="hidden")return;
   const dims=fit.proposeDimensions();if(!dims)return;
   const cols=Math.max(20,Math.min(500,dims.cols)),rows=Math.max(5,Math.min(200,dims.rows));
   if(term.cols===cols&&term.rows===rows&&!view.needsResize)return;
   term.resize(cols,rows);
   view.needsResize=false;
   if(!term.options.disableStdin)guarded(()=>api("/api/terminal/resize",{
     ws:view.ws,id,cols,rows,
   }))();
 };
 view.observer=new ResizeObserver(()=>{
   clearTimeout(view.resizeTimer);view.resizeTimer=setTimeout(resize,120);
 });
 view.observer.observe(host);
 term.onData(data=>queueTerminalInput(view,data));
 terminalViews.set(id,view);requestAnimationFrame(resize);
 return view;
}
function drawEdges(){
 // Existing running brokers may not yet serve the new module. Retain a safe
 // static visualization until a new Canvas broker loads rope-physics.js.
 if(window.SentraCablePhysics){
   window.SentraCablePhysics.sync($("edge-paths"),state.links,state.nodes);
   return;
 }
 $("edge-paths").innerHTML=state.links.map(link=>{
   const a=nodeBy(link.source),b=nodeBy(link.target);
   if(!a||!b)return "";
   const ax=a.x+a.width,ay=a.y+a.height/2,bx=b.x,by=b.y+b.height/2;
   const offset=Math.max(75,Math.abs(bx-ax)*.45);
   return '<path class="edge-line" data-edge="'+safe(link.id)+'" d="M '+ax+' '+ay+
     ' C '+(ax+offset)+' '+ay+' '+(bx-offset)+' '+by+' '+bx+' '+by+'"/>';
 }).join("");
}

function chooseTool(tool){
 state.tool=tool;
 document.querySelectorAll(".tool").forEach(b=>b.classList.toggle("active",b.dataset.tool===tool));
 $("viewport").classList.toggle("linking",tool==="link");
 if(tool!=="link"){state.linkFrom=null;$("connection-hint").hidden=true;}
 if(["terminal","agent","team","note"].includes(tool)){openModal(tool);chooseTool("select");}
}
function field(name,label,body,hint=""){
 return '<label class="field"><span>'+safe(label)+'</span>'+body+(hint?'<small>'+safe(hint)+'</small>':"")+'</label>';
}
function input(name,value="",type="text",required=true,placeholder=""){
 return '<input type="'+type+'" name="'+name+'" value="'+safe(value)+'" placeholder="'+safe(placeholder)+'" '+(required?"required":"")+' maxlength="128">';
}
function dropdown(name,items,multiple=false){
 return '<select name="'+name+'" '+(multiple?'multiple size="5"':"required")+'>'+
  items.map(e=>'<option value="'+safe(e.value)+'">'+safe(e.label)+'</option>').join("")+'</select>';
}
function terminalOptions(){
 const rows=state.integrations.length?state.integrations:[
  {id:"powershell",name:"Windows PowerShell",installed:true},
  {id:"cmd",name:"Prompt de comando · CMD",installed:true},
  {id:"pwsh",name:"PowerShell 7",installed:false},
  {id:"sentra-cli",name:"SENTRA CLI",installed:false},
  {id:"codex",name:"OpenAI Codex CLI",installed:false},
  {id:"antigravity-app",name:"Antigravity · aplicativo externo",installed:false}];
 const preferred=rows.some(r=>r.id==="sentra-cli"&&r.installed)?"sentra-cli":"powershell";
 return '<select name="shell" required>'+rows.map(r=>
   '<option value="'+safe(r.id)+'" '+(r.installed?"":"disabled")+
   (r.id===preferred?" selected":"")+'>'+
   safe(r.name+(r.installed?"":" · indisponível"))+'</option>').join("")+'</select>';
}
function canvasModelChoices(){
 const known=state.models.length?state.models:["sentra/codex/current","sentra/chatgpt-web/auto","sentra/chatgpt-web/gpt-6-instant","sentra/chatgpt-web/gpt-6"];
 return '<datalist id="canvas-model-choices">'+
   [...new Set(known)].map(id=>'<option value="'+safe(id)+'"></option>').join("")+'</datalist>';
}
function agentOptions(){
 return (state.detail?.agents||[]).map(a=>({value:a.id,label:a.name+" · "+a.role}));
}
function teamOptions(){
 return (state.detail?.teams||[]).map(a=>({value:a.id,label:a.name}));
}
function openModal(kind){
 if(modalSending)return;
 modalKind=kind;modalAfter=null;
 modalRequest={key:crypto.randomUUID(),payload:null,path:null};
 let title="",hint="",body="",button="Criar";
 const point=centerWorld();state.spawn={x:Math.round(point.x-140),y:Math.round(point.y-110)};
 if(kind==="workspace"){
  title="Novo workspace";hint="PROJETOS";body=field("name","Nome",input("name","","text",true,"novo_projeto"),"Um espaço independente para terminais e agentes.");
 }else if(kind==="terminal"){
  requireWS();title="Novo terminal";hint="EXECUÇÃO NATIVA";
  const codexReady=state.integrations.some(x=>x.id==="codex"&&x.native_model_authenticated===true);
  body=field("name","Nome",input("name","terminal_"+((state.detail?.terminals.length||0)+1)))+
    field("shell","Ambiente",terminalOptions(),
    "SENTRA e Codex utilizam ConPTY. Ferramentas externas têm autenticação independente.")+
    '<div id="terminal-model-wrap">'+field("model","Modelo do SENTRA CLI",
      input("model",codexReady?"sentra/codex/current":"sentra/chatgpt-web/auto").replace('<input ','<input list="canvas-model-choices" ')+canvasModelChoices(),
      "Selecione um modelo do catálogo; o acesso real será verificado no turno, não na lista.")+
    field("effort","Esforço de raciocínio · Codex",dropdown("effort",[
      {value:"low",label:"Low · Rápido"},{value:"medium",label:"Medium · Equilibrado"},
      {value:"high",label:"High · Profundo"},{value:"xhigh",label:"Extra High · Intensivo"}
    ]),"Pode ser alterado depois pelo comando /effort. Modelos Web não usam essa configuração.")+'</div>';
 }else if(kind==="agent"){
  requireWS();title="Novo agente";hint="SENTRA CLI";
  const nativeReady=state.integrations.some(item=>item.id==="codex"&&item.native_model_authenticated===true);
  const defaultModel=nativeReady?"sentra/codex/current":"sentra/chatgpt-web/auto";
  body=field("name","Identificador",input("name","agente_"+((state.detail?.agents.length||0)+1)))+
    field("role","Função",dropdown("role",[{value:"worker",label:"Trabalhador"},{value:"coordinator",label:"Coordenador"},{value:"reviewer",label:"Revisor"}]))+
    field("model","Modelo",input("model",defaultModel).replace('<input ','<input list="canvas-model-choices" ')+
      canvasModelChoices(),
      "O catálogo não concede acesso: o SENTRA verificará modelo e esforço na execução.")+
    '<label class="field row"><input type="checkbox" name="start" checked> Iniciar sessão SENTRA CLI real (ConPTY)</label>';
 }else if(kind==="team"){
  requireWS();title="Nova equipe";hint="COLABORAÇÃO";
  if((state.detail?.agents||[]).length<2){toast("Crie primeiro um coordenador e pelo menos um trabalhador.");return;}
  body=field("name","Nome",input("name","equipe_"+((state.detail?.teams.length||0)+1)))+
  field("coordinator","Coordenador",dropdown("coordinator",agentOptions()))+
  field("workers","Trabalhadores (Ctrl + clique)",dropdown("workers",agentOptions(),true));
 }else if(kind==="note"){
  requireWS();title="Nova nota";hint="CONTEXTO COMPARTILHADO";
  if(state.nodes.length){
    state.spawn.x=Math.min(...state.nodes.map(n=>n.x))+70;
    state.spawn.y=Math.max(...state.nodes.map(n=>n.y+n.height))+90;
  }
  body=field("title","Título",input("title","Anotações"))+
  field("body","Conteúdo",'<textarea name="body" placeholder="Anote decisões, contexto ou próximos passos…"></textarea>');
 }else if(kind==="handoff"){
  requireWS();title="Enviar para CLI conectado";hint="HANDOFF CONTROLADO";button="Enviar mensagem";
  const source=nodeBy(state.selected);
  const connected=state.links.filter(l=>l.source===source?.id)
     .map(l=>nodeBy(l.target)).filter(Boolean).filter(n=>{
       const terminal=n.kind==="terminal"?resource("terminal",n.resource_id):
         n.kind==="agent"?resource("terminal",resource("agent",n.resource_id)?.terminal_id):null;
       return terminal?.status==="running"&&["sentra-cli","codex"].includes(terminal.shell);
     });
  if(!connected.length){toast("Conecte este nó à entrada de um terminal SENTRA CLI ou Codex ativo.");return;}
  body=field("destination","Destino conectado",dropdown("destination",connected.map(n=>({value:n.id,label:n.title}))))+
       field("message","Instrução",'<div class="prompt-composer-shell">'+
         '<textarea name="message" maxlength="4000" required rows="4" placeholder="Descreva a instrução para o agente conectado…"></textarea>'+
         '<div class="prompt-composer-foot"><span class="composer-indicator">● Terminal conectado · Ctrl+Enter para enviar</span><span id="composer-count">0 / 4000</span></div></div>',
       "As quebras de linha são unificadas no envio. ConPTY confirma transporte, não conclusão do modelo.");
 }else if(kind==="task"){
  requireWS();title="Delegar tarefa";hint="EXECUÇÃO ASSÍNCRONA";button="Delegar";
  if(!(state.detail?.teams||[]).length){toast("Crie uma equipe antes de delegar tarefas.");return;}
  body=field("team","Equipe",dropdown("team",teamOptions()))+
  field("agent","Agente trabalhador",'<select name="agent" required></select>')+
  field("provider","Provedor",dropdown("provider",[{value:"sentra-cli",label:"SENTRA CLI · modelo real"},{value:"test",label:"Teste local · sem IA"}]))+
  field("prompt","Tarefa",'<textarea name="prompt" maxlength="4000" required placeholder="Descreva a tarefa para a equipe…"></textarea>',"Usa as permissões definidas na instalação.")+
  field("check_path","Arquivo a verificar (opcional)",'<input name="check_path" maxlength="1024" placeholder="resultado.txt">')+
  field("check_text","Conteúdo esperado",'<textarea name="check_text" maxlength="4000" placeholder="O conteúdo que confirma o resultado…"></textarea>',"Quando informado, o arquivo será verificado antes de concluir a tarefa.");
 }else return;
 $("modal-kicker").textContent=hint;
 $("modal-title").textContent=title;
 $("modal-fields").innerHTML=body;
 $("modal-submit").textContent=button;
 beginOverlayFocus($("modal-shade"));
 $("modal-shade").hidden=false;
 const first=$("modal-form").querySelector("input:not([type=checkbox]),textarea,select");
 if(first)first.focus();
 if(kind==="terminal"){
  const shell=$("modal-form").elements.namedItem("shell");
  const selectedModel=$("modal-form").elements.namedItem("model");
  const updateModel=()=>{
   const enabled=shell.value==="sentra-cli";
   $("terminal-model-wrap").hidden=!enabled;
   selectedModel.disabled=!enabled;
  };
  shell.addEventListener("change",updateModel);
  updateModel();
 }
 if(kind==="task"){
  const team=$("modal-form").elements.namedItem("team");
  const update=guarded(async()=>{
    const ids=await api("/api/team?ws="+encodeURIComponent(state.ws)+"&id="+encodeURIComponent(team.value));
    $("modal-form").elements.namedItem("agent").innerHTML=ids.filter(a=>a.team_role==="worker").map(a=>
      '<option value="'+safe(a.id)+'">'+safe(a.name)+'</option>').join("");
  });
  team.addEventListener("change",update);update();
 }
}
function closeModal(force=false){if(modalSending&&force!==true)return;$("modal-shade").hidden=true;modalKind=null;modalRequest=null;endOverlayFocus($("modal-shade"));}
async function submitModal(e){
 e.preventDefault();
 if(modalSending||!modalKind)return;
 const kind=modalKind;
 const form=$("modal-form");
 const data=new FormData(form);
 const name=String(data.get("name")||"").trim();
 const attempt=modalRequest;
 const button=$("modal-submit"),label=button.textContent;
 modalSending=true;button.disabled=true;button.textContent="Enviando…";
 $("modal-form").setAttribute("aria-busy","true");
 $("modal-close").disabled=true;$("modal-cancel").disabled=true;
 try{
 let result;
 if(kind==="workspace"){
  result=await api("/api/workspaces",{name});closeModal(true);await loadWorkspacesNoRecursion();
  await openWorkspace(result.id);toast("Workspace criado.");
 }else if(kind==="terminal"){
  const shell=String(data.get("shell"));
  if(shell==="antigravity-app"){
    const result=await api("/api/external/antigravity",{ws:requireWS(),approved:true});
    closeModal(true);toast("Antigravity aberto como editor externo (PID "+result.pid+").");
  }else{
    result=await api("/api/terminals",{ws:requireWS(),name,shell,
      ...(shell==="sentra-cli"?{model:String(data.get("model")||"").trim(),
        effort:String(data.get("effort")||"low")}: {})});
    closeModal(true);await openWorkspace(state.ws);
    toast((shell==="sentra-cli"||shell==="codex")?"Sessão CLI iniciada; verifique modelo e autenticação no terminal.":"Terminal ConPTY ativo.");
  }
 }else if(kind==="agent"){
  result=await api("/api/agents",{ws:requireWS(),name,role:data.get("role"),
          model:String(data.get("model")||""),start:data.get("start")==="on"});
  closeModal(true);await openWorkspace(state.ws);toast("Agente registrado. Modelo ainda não validado.");
 }else if(kind==="team"){
  const coordinator=String(data.get("coordinator"));
  const workers=data.getAll("workers").filter(x=>x!==coordinator);
  if(!workers.length)throw Error("Selecione pelo menos um trabalhador distinto.");
  result=await api("/api/teams",{ws:requireWS(),name,coordinator,workers});
  closeModal(true);await openWorkspace(state.ws);toast("Equipe criada.");
 }else if(kind==="note"){
  result=await api("/api/graph/note",{ws:requireWS(),title:String(data.get("title")),body:String(data.get("body")||""),
    x:state.spawn.x,y:state.spawn.y});
  closeModal(true);await openWorkspace(state.ws);toast("Nota adicionada ao canvas.");
 }else if(kind==="handoff"){
  const source=state.selected;
  const target=String(data.get("destination"));
  // The handoff contract accepts a single text line, never control characters.
  const message=String(data.get("message")||"").replace(/[\x00-\x1f\x7f]/g," ").trim();
  attempt.payload??={ws:requireWS(),source,target,message,approved:true,request_key:attempt.key};
  attempt.path="/api/graph/handoff";
  const outcome=await api(attempt.path,attempt.payload);
  closeModal(true);
  const cable=state.links.find(l=>l.source===source&&l.target===target);
  if(cable && outcome.status==="sent"){
   const line=Array.from($("edge-paths").children).find(el=>el.dataset.edge===cable.id);
   if(line){line.classList.remove("transmitting");void line.getBoundingClientRect();line.classList.add("transmitting");
     setTimeout(()=>line.classList.remove("transmitting"),1400);}
  }
  toast("Mensagem enviada ao terminal ("+outcome.status+"). A resposta do modelo aparece em Atividade.");
 }else if(kind==="task"){
  const provider=String(data.get("provider"));
  const approved=provider==="sentra-cli";
  const checkPath=String(data.get("check_path")||"").trim();
  const checks=checkPath?[{path:checkPath,text:String(data.get("check_text")||"")}]:[];
  attempt.payload??={ws:requireWS(),team:String(data.get("team")),agent:String(data.get("agent")),
      provider,approved,prompt:String(data.get("prompt")),checks,request_key:attempt.key};
  attempt.path="/api/tasks";
  await api(attempt.path,attempt.payload);
  closeModal(true);await openWorkspace(state.ws);toast("Tarefa registrada com chave idempotente.");
 }
 }catch(error){
  if(attempt.payload){
   // A lost response may have executed. Retry the exact same delivery, never infer a new one.
   $("modal-fields").querySelectorAll("input,textarea,select").forEach(field=>field.disabled=true);
   $("modal-kicker").textContent="ENVIO NÃO CONFIRMADO · RETRY DA MESMA SOLICITAÇÃO";
   button.textContent="Tentar novamente";
  }
  throw error;
 }finally{
  modalSending=false;button.disabled=false;
  if(button.textContent==="Enviando…")button.textContent=label;
  $("modal-form").removeAttribute("aria-busy");
  $("modal-close").disabled=false;$("modal-cancel").disabled=false;
 }
}
function showInspector(n){
 if(!n)return;
 state.selected=n.id;
 document.querySelectorAll(".node").forEach(el=>el.classList.toggle("selected",el.dataset.node===n.id));
 $("inspector").hidden=false;
 $("inspector-label").textContent=n.kind.toUpperCase()+" · IDENTIDADE DO RECURSO";
 $("inspector-title").textContent=n.title;
 const item=resource(n.kind,n.resource_id);
 const details=[
  ["Namespace",item?.namespace||"workspace/"+state.ws+"/note/"+n.id],
  ["Tipo",n.kind],["ID",n.resource_id||n.id],
  ["Dimensões",n.width+" × "+n.height],["Posição",Math.round(n.x)+", "+Math.round(n.y)]
 ];
 if(item){
  details.push(["Estado",item.status||"configurado"]);
  if(item.model)details.push(["Modelo solicitado",item.model]);
  if(item.role)details.push(["Função",item.role]);
  if(item.shell)details.push(["Shell",item.shell]);
  if(item.pid)details.push(["PID",String(item.pid)]);
  if(item.conversation_id)details.push(["Conversa salva",item.conversation_id]);
 }
 let content=details.map(([name,value])=>'<div class="inspect-field"><label>'+safe(name)+'</label><div>'+safe(value)+'</div></div>').join("");
 if(n.kind==="terminal"){
  content+='<div class="inspect-actions"><button data-inspect-action="rename">Renomear</button><button data-inspect-action="duplicate">Duplicar</button><button data-inspect-action="close">Encerrar terminal</button></div>';
 }else if(n.kind==="team"){
  content+='<div class="inspect-actions"><button data-inspect-action="delegate">Delegar tarefa</button><button data-inspect-action="members">Ver membros</button></div>';
 }else if(n.kind==="agent"){
  content+='<div class="inspect-field"><label>Disponibilidade do modelo</label><div>Não verificada. Processo iniciado não significa modelo autenticado.</div></div>';
  content+='<div class="inspect-actions"><button data-inspect-action="restart-agent">Abrir conversa salva</button></div>';
 }else if(n.kind==="note"){
  content+='<div class="inspect-actions"><button data-inspect-action="remove-note">Excluir nota</button></div>';
 }
 const targets=state.links.filter(l=>l.source===n.id).map(l=>nodeBy(l.target))
   .filter(Boolean).filter(target=>{
     const t=target.kind==="terminal"?resource("terminal",target.resource_id):
       target.kind==="agent"?resource("terminal",resource("agent",target.resource_id)?.terminal_id):null;
     return t?.status==="running"&&["sentra-cli","codex"].includes(t.shell);
   });
 if(targets.length)content+='<div class="inspect-actions"><button data-inspect-action="handoff">Enviar para CLI conectado ↗</button></div>'+
    '<div class="inspect-field"><label>Destinos ativos</label><div>'+targets.map(t=>safe(t.title)).join(', ')+'</div></div>';
 renderInspectorTabs(n,content,targets);
}
let inspectorPanels=null;
function selectInspectorTab(tab){
 if(!inspectorPanels)return;
 const panel=inspectorPanels[tab];
 if(panel===undefined)return;
 $("inspector-content").innerHTML=panel;
 $("inspector-tabs").querySelectorAll("[data-inspector-tab]").forEach(btn=>{
  const current=btn.dataset.inspectorTab===tab;
  btn.setAttribute("aria-selected",String(current));
  btn.tabIndex=current?0:-1;
 });
}
function renderInspectorTabs(n,details,targets){
 const outbound=state.links.filter(l=>l.source===n.id)
  .map(l=>({node:nodeBy(l.target),direction:"Envia para"}));
 const inbound=state.links.filter(l=>l.target===n.id)
  .map(l=>({node:nodeBy(l.source),direction:"Recebe de"}));
 const connections=[...outbound,...inbound].filter(x=>x.node);
 const links=connections.length?connections.map(({node,direction})=>
   '<div class="connection-row"><span class="connection-direction">'+safe(direction)+'</span>'+
   '<span class="connection-name">'+safe(node.title)+'</span></div>').join(""):
   '<p class="inspect-empty">Sem conexões. Use a ferramenta de ligação para conectar nós.</p>';
 const deliveries=(state.detail?.events||[]).filter(event=>
   [n.id,n.resource_id].includes(event.subject)).slice(0,30);
 const activity=deliveries.length?deliveries.map(event=>
   '<div class="inspect-block"><span class="tiny">'+safe(new Date(event.created*1000).toLocaleString("pt-BR"))+
   '</span> · '+safe(event.kind)+'<div class="tiny">'+safe(event.detail||"Evento registrado")+
   '</div></div>').join(""):
   '<p class="inspect-empty">Nenhum evento específico deste nó até agora.</p>';
 inspectorPanels={
   details,
   connections:'<div class="inspector-connections">'+links+'</div>'+
     (targets.length?'<div class="inspect-actions"><button data-inspect-action="handoff">Enviar instrução ↗</button></div>':""),
   activity
 };
 const tabs=$("inspector-tabs");tabs.hidden=false;
 tabs.innerHTML=[
   ["details","Detalhes"],["connections","Conexões"],["activity","Atividade"]
 ].map(([id,label])=>
   '<button type="button" class="halo-tab" role="tab" id="inspector-tab-'+id+
   '" data-inspector-tab="'+id+'" aria-controls="inspector-content" aria-selected="false">'+label+'</button>').join("");
 $("inspector-content").setAttribute("role","tabpanel");
 $("inspector-content").setAttribute("aria-labelledby","inspector-tab-details");
 selectInspectorTab("details");
}
$("inspector-tabs").addEventListener("click",e=>{
 const button=e.target.closest("[data-inspector-tab]");if(!button)return;
 selectInspectorTab(button.dataset.inspectorTab);
 $("inspector-content").setAttribute("aria-labelledby",button.id);
});
$("inspector-tabs").addEventListener("keydown",e=>{
 if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;
 const buttons=[...$("inspector-tabs").querySelectorAll("[data-inspector-tab]")];
 let index=buttons.indexOf(document.activeElement);
 if(index<0)return;
 e.preventDefault();
 index=e.key==="Home"?0:e.key==="End"?buttons.length-1:
   (index+(e.key==="ArrowRight"?1:-1)+buttons.length)%buttons.length;
 buttons[index].focus();buttons[index].click();
});
async function inspectAction(action){
 const n=nodeBy(state.selected);if(!n)return;
 if(action==="handoff"){
   openModal("handoff");
 }else if(action==="rename"){
   const name=prompt("Nome do terminal:",n.title);if(!name)return;
   await api("/api/terminal/rename",{ws:requireWS(),id:n.resource_id,name});
   await openWorkspace(state.ws);
 }else if(action==="duplicate"){
   const name=prompt("Nome do terminal independente:",n.title+"_copia");if(!name)return;
   await api("/api/terminal/duplicate",{ws:requireWS(),id:n.resource_id,name});
   await openWorkspace(state.ws);
 }else if(action==="restart-agent"){
   await api("/api/agent/restart",{ws:requireWS(),id:n.resource_id});
   await openWorkspace(state.ws);
   toast("Conversa aberta. Nenhuma instrução foi reenviada automaticamente.");
 }else if(action==="close"){
   if(!confirm("Encerrar este processo de terminal?"))return;
   await api("/api/terminal/close",{ws:requireWS(),id:n.resource_id,confirm:true});
   await openWorkspace(state.ws);
 }else if(action==="remove-note"){
   if(!confirm("Remover esta nota e suas conexões?"))return;
   await api("/api/graph/note/delete",{ws:requireWS(),id:n.id,confirm:true});
   $("inspector").hidden=true;await openWorkspace(state.ws);
 }else if(action==="delegate"){openModal("task");}
 else if(action==="members"){
   const members=await api("/api/team?ws="+encodeURIComponent(state.ws)+"&id="+encodeURIComponent(n.resource_id));
   $("inspector-content").innerHTML+='<div class="inspect-field"><label>Membros</label>'+
     members.map(x=>'<div class="inspect-block">'+safe(x.name)+' <span class="tiny">'+safe(x.team_role)+'</span></div>').join("")+'</div>';
 }
}

async function pollTerminal(id){
 if(!state.ws)return;
 const view=terminalViews.get(id);if(!view||view.pending)return;
 view.pending=true;
 const ws=state.ws;
 try{
  const value=await api("/api/terminal/output?ws="+encodeURIComponent(ws)+"&id="+
      encodeURIComponent(id)+"&cursor="+(state.cursors[id]||0));
  if(ws!==state.ws||terminalViews.get(id)!==view)return;
  const screen=$("term-"+id);if(!screen)return;
  screen.title=value.persisted===false?"Histórico não salvo; mantenha esta sessão aberta."
     :value.recoverable===false?"Histórico recuperado. Abra uma nova sessão para continuar."
     :"Histórico salvo no computador.";
  if(value.persisted===false){
   state.persistenceWarnings??={};
   if(!state.persistenceWarnings[id]){
    state.persistenceWarnings[id]=true;
    toast("O histórico deste terminal não está sendo salvo. Verifique o armazenamento antes de fechar a sessão.");
   }
  }
  if(value.text){
   if(value.truncated)view.term.reset();
   await new Promise(resolve=>view.term.write(value.text,resolve));
  }
  if(value.cursor!==undefined)state.cursors[id]=value.cursor;
  const running=value.status==="running"&&value.recoverable!==false;
  view.term.options.disableStdin=!running;view.term.options.cursorBlink=running;
  const form=document.querySelector('[data-terminal-form="'+id+'"]');
  if(form)form.querySelector("input").disabled=!running;
  const status=document.querySelector('[data-terminal-status="'+id+'"]');
  if(status){status.textContent=running?"Em execução":value.recoverable===false?"Histórico recuperado":value.status||"offline";status.previousElementSibling?.classList.toggle("off",!running);}
  const history=document.querySelector('[data-terminal-history="'+id+'"]');
  if(history){history.textContent=value.persisted===false?"Não salvo":"Histórico salvo";history.title=screen.title;}
 }catch(err){ /* A sessão pode encerrar entre refreshes. */ }
 finally{view.pending=false;}
}
async function pollAll(){
 if(!state.ws||state.polling)return;
 state.polling=true;
 try{
  const ids=(state.detail?.terminals||[]).filter(t=>t.status==="running")
       .map(t=>t.id);
  await Promise.all(ids.map(pollTerminal));
 }finally{state.polling=false;}
}
function onPort(n,which){
 if(state.linkFrom){
  const source=state.linkFrom;
  if(source!==n.id)guarded(async()=>{
    const link=await api("/api/graph/link",{ws:requireWS(),source,target:n.id});
    if(!state.links.some(x=>x.id===link.id))state.links.push(link);
    drawEdges();toast("Nós conectados.");$("canvas-count").textContent=state.nodes.length+" nós · "+state.links.length+" conexões";
  })();
  state.linkFrom=null;chooseTool("select");return;
 }
 state.linkFrom=n.id;chooseTool("link");state.linkFrom=n.id;
 $("connection-hint").hidden=false;
}
function nodePointerDown(e){
 if(e.button!==0)return;
 const nodeElement=e.target.closest(".node");
 if(!nodeElement)return;
 const n=nodeBy(nodeElement.dataset.node);if(!n)return;
 if(e.target.closest("[data-port]")){
   e.stopPropagation();onPort(n,e.target.dataset.port);return;
 }
 if(state.tool==="link"){
   e.stopPropagation();onPort(n,"input");return;
 }
 if(e.target.closest("button,input,textarea,select,form,.term-output"))return;
 if(nodeElement.classList.contains("expanded"))return;
 if(e.target.closest("[data-resize]")){
  state.move={type:"resize",pointer:e.pointerId,n,startX:e.clientX,startY:e.clientY,w:n.width,h:n.height};
 }else if(e.target.closest(".node-header")){
  state.move={type:"node",pointer:e.pointerId,n,startX:e.clientX,startY:e.clientY,x:n.x,y:n.y};
 }else{
  state.selected=n.id;return;
 }
 e.preventDefault();e.stopPropagation();
 state.selected=n.id;
 document.querySelectorAll(".node").forEach(el=>el.classList.toggle("selected",el.dataset.node===n.id));
}
function pointerDown(e){
 if(state.fullscreen||e.target.closest(".node,.onboarding,#connection-hint"))return;
 if(e.target.closest("button,input,textarea,select,.toolbar,.glass"))return;
 if(e.button!==0 && e.button!==1)return;
 e.preventDefault();$("viewport").focus({preventScroll:true});
 state.move={type:"pan",pointer:e.pointerId,startX:e.clientX,startY:e.clientY,
             x:state.x,y:state.y};
 $("viewport").classList.add("panning");
 $("viewport").setPointerCapture(e.pointerId);
}
function pointerMove(e){
 const m=state.move;if(!m||m.pointer!==e.pointerId)return;
 const dx=e.clientX-m.startX,dy=e.clientY-m.startY;
 if(m.type!=="pan"&&!m.dragging){
  if(Math.abs(dx)+Math.abs(dy)<4)return;
  m.dragging=true;$("viewport").setPointerCapture(e.pointerId);
 }
 if(m.type==="pan"){
  state.x=m.x+dx;state.y=m.y+dy;setView();
 }else if(m.type==="node"){
  m.n.x=Math.round(m.x+dx/state.scale);m.n.y=Math.round(m.y+dy/state.scale);
  const element=document.querySelector('[data-node="'+m.n.id+'"]');
  if(element){element.style.left=m.n.x+"px";element.style.top=m.n.y+"px";}
  drawEdges();
 }else if(m.type==="resize"){
  m.n.width=Math.max(250,Math.min(1100,Math.round(m.w+dx/state.scale)));
  m.n.height=Math.max(150,Math.min(850,Math.round(m.h+dy/state.scale)));
  const element=document.querySelector('[data-node="'+m.n.id+'"]');
  if(element){element.style.width=m.n.width+"px";element.style.height=m.n.height+"px";}
  drawEdges();
 }
}
function pointerUp(e){
 const m=state.move;if(!m||m.pointer!==e.pointerId)return;
 state.move=null;$("viewport").classList.remove("panning");
 if($("viewport").hasPointerCapture(e.pointerId))$("viewport").releasePointerCapture(e.pointerId);
 if(m.type!=="pan"&&!m.dragging)return;
 if(m.type==="node"){
  guarded(()=>collaboration?.node(m.n)||api("/api/graph/move",{ws:requireWS(),id:m.n.id,x:m.n.x,y:m.n.y}))();
 }else if(m.type==="resize"){
  guarded(()=>collaboration?.node(m.n)||api("/api/graph/resize",{ws:requireWS(),id:m.n.id,width:m.n.width,height:m.n.height}))();
 }
}
async function refreshResources(){
 if(!state.ws||state.move||state.loading||document.hidden||modalKind)return;
 const ws=state.ws;
 const info=await api("/api/graph?ws="+encodeURIComponent(ws));
 if(ws!==state.ws)return;
 state.detail=info;
 const old=state.nodes.map(n=>n.id).join(",");
 const next=info.nodes.map(n=>n.id).join(",");
 state.links=info.links;
 if(old!==next){state.nodes=info.nodes;renderNodes();}
 else{
  const byid=new Map(info.nodes.map(n=>[n.id,n]));
  for(const n of state.nodes){
   const latest=byid.get(n.id);
   if(latest && state.move?.n?.id!==n.id){
     const element=document.querySelector('[data-node="'+n.id+'"]');
     for(const [key,style] of [["x","left"],["y","top"],["width","width"],["height","height"]]){
       if(n[key]!==latest[key]){n[key]=latest[key];if(element)element.style[style]=n[key]+"px";}
     }
   }
   if(latest && latest.title!==n.title){n.title=latest.title;const el=document.querySelector('[data-node="'+n.id+'"] .node-title');if(el)el.textContent=n.title;}
  }
  drawEdges();
 }
 $("canvas-count").textContent=state.nodes.length+" nós · "+state.links.length+" conexões";
 renderSessionRail();
}
const canvasSurface=document.querySelector(".main");
canvasSurface.addEventListener("click",e=>{
 const button=e.target.closest("[data-cli-command][data-cli-terminal]");
 if(!button)return;
 const command=button.dataset.cliCommand;
 if(!["/model","/effort"].includes(command))return;
 const terminal=resource("terminal",button.dataset.cliTerminal);
 if(!terminal||terminal.shell!=="sentra-cli"||terminal.status!=="running"){
  toast("SENTRA CLI precisa estar em execução para consultar esta configuração.","error");return;
 }
 guarded(async()=>{
  await api("/api/terminal/input",{ws:requireWS(),id:terminal.id,data:command+"\r"});
  toast(command+" enviado ao terminal. A resposta aparecerá na sessão ConPTY.");
 })();
});
$("terminal-stage").addEventListener("keydown",e=>{
 if(e.key==="Escape"&&state.fullscreen){e.preventDefault();e.stopPropagation();restoreTerminal();}
},true);
canvasSurface.addEventListener("pointerdown",e=>{
 if(e.target.closest(".node"))nodePointerDown(e);else pointerDown(e);
});
$("viewport").addEventListener("pointermove",pointerMove);
const graphAnnouncement=document.createElement("div");graphAnnouncement.className="graph-announcement";
graphAnnouncement.setAttribute("aria-live","polite");graphAnnouncement.setAttribute("aria-atomic","true");
$("viewport").append(graphAnnouncement);
$("viewport").addEventListener("keydown",event=>{
 if(event.target.closest("input,textarea,select,button,.term-output,[contenteditable]")||!state.nodes.length)return;
 if(event.key==="Enter"&&state.selected){event.preventDefault();showInspector(nodeBy(state.selected));return;}
 const directions={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1};
 if(!Object.hasOwn(directions,event.key)&&!["Home","End"].includes(event.key))return;
 event.preventDefault();
 let candidates=state.nodes;
 if(event.shiftKey&&state.selected){
  const adjacent=new Set(window.SentraGraphView.neighbors(state.nodes,state.links,state.selected));
  if(adjacent.size)candidates=state.nodes.filter(node=>adjacent.has(node.id));
 }
 const index=candidates.findIndex(node=>node.id===state.selected);
 const next=event.key==="Home"?candidates[0]:event.key==="End"?candidates.at(-1):
   candidates[(index+directions[event.key]+candidates.length)%candidates.length];
 state.selected=next.id;const view=$("viewport").getBoundingClientRect();
 state.x=view.width/2-(next.x+next.width/2)*state.scale;
 state.y=view.height/2-(next.y+next.height/2)*state.scale;
 setView();renderVisibleNodes();document.querySelector('[data-node="'+next.id+'"]')?.focus();
 graphAnnouncement.textContent=next.title+" · nó "+(state.nodes.indexOf(next)+1)+" de "+state.nodes.length;
});
$("viewport").addEventListener("pointermove",event=>{
 const rect=$("viewport").getBoundingClientRect();
 collaboration?.presence(worldAt(event.clientX-rect.left,event.clientY-rect.top));
});
$("viewport").addEventListener("pointerup",pointerUp);
$("viewport").addEventListener("pointercancel",pointerUp);
$("viewport").addEventListener("wheel",e=>{
 if(e.target.closest(".term-output,.note-text")&&!e.ctrlKey)return;
 e.preventDefault();
 const bounds=$("viewport").getBoundingClientRect();
 zoomTo(state.scale*(e.deltaY<0?1.12:1/1.12),e.clientX-bounds.left,e.clientY-bounds.top);
},{passive:false});
canvasSurface.addEventListener("click",e=>{
 const target=e.target.closest("[data-node-action]");
 if(target){
  const n=nodeBy(target.closest(".node").dataset.node);
  if(!n)return;
  const action=target.dataset.nodeAction;
  if(action==="expand"){expandTerminal(n.id);return;}
  if(action==="open-session"){const owner=terminalNode(n.resource_id);if(owner)expandTerminal(owner.id);return;}
  showInspector(n);
  if(action==="delegate")openModal("task");
  if(action==="restart-agent")guarded(()=>inspectAction("restart-agent"))();
  return;
 }
 if(e.target.closest(".node") && !e.target.closest("[data-port]")){
  const n=nodeBy(e.target.closest(".node").dataset.node);
  if(n){state.selected=n.id;document.querySelectorAll(".node").forEach(el=>el.classList.toggle("selected",el.dataset.node===n.id));}
 }
});
canvasSurface.addEventListener("submit",e=>{
 const form=e.target.closest("[data-terminal-form]");if(!form)return;
 e.preventDefault();
 const id=form.dataset.terminalForm,entry=form.querySelector("input");
 const command=entry.value;entry.value="";
 const view=terminalViews.get(id);if(view)queueTerminalInput(view,command+"\r");
});
canvasSurface.addEventListener("keydown",e=>{
 const entry=e.target.closest("[data-terminal-input]");
 if(!entry)return;
 if(e.key==="Enter"){e.preventDefault();entry.closest("form").requestSubmit();}
 else if(e.key==="c"&&e.ctrlKey){e.preventDefault();guarded(()=>api("/api/terminal/input",
  {ws:requireWS(),id:entry.dataset.terminalInput,data:"\u0003"}))();}
 else if(e.key==="ArrowUp"||e.key==="ArrowDown"){
  e.preventDefault();guarded(()=>api("/api/terminal/input",{ws:requireWS(),
     id:entry.dataset.terminalInput,data:e.key==="ArrowUp"?"\u001b[A":"\u001b[B"}))();
 }
});
canvasSurface.addEventListener("change",e=>{
 if(!e.target.matches("[data-note]"))return;
 const id=e.target.dataset.note,body=e.target.value;
 guarded(()=>collaboration?.note(id,body)||api("/api/graph/note/update",{ws:requireWS(),id,body}))();
 const note=nodeBy(id);if(note)note.body=body;
});
function unlinkCable(link){
 if(!link || !confirm("Remover esta conexão entre nós?"))return;
 guarded(async()=>{
   await api("/api/graph/unlink",{ws:requireWS(),id:link.dataset.edge});
   state.links=state.links.filter(x=>x.id!==link.dataset.edge);
   drawEdges();toast("Conexão removida.");
 })();
}
$("edge-paths").addEventListener("click",e=>unlinkCable(e.target.closest("[data-edge]")));
$("edge-paths").addEventListener("keydown",e=>{
 if(e.key!=="Enter"&&e.key!==" ")return;
 const link=e.target.closest("[data-edge]");if(!link)return;
 e.preventDefault();unlinkCable(link);
});
document.querySelectorAll("[data-tool]").forEach(b=>b.addEventListener("click",()=>guarded(()=>chooseTool(b.dataset.tool))()));
$("zoom-out").addEventListener("click",()=>zoomTo(state.scale/1.2));
$("zoom-in").addEventListener("click",()=>zoomTo(state.scale*1.2));
$("zoom-label").addEventListener("click",()=>zoomTo(1));
$("fit-nodes").addEventListener("click",fitNodes);
$("reset-view").addEventListener("click",resetView);
$("toggle-sidebar").addEventListener("click",()=>$("app").classList.toggle("sidebar-collapsed"));
$("new-workspace").addEventListener("click",()=>openModal("workspace"));
$("onboarding-action").addEventListener("click",()=>openModal(state.ws?"terminal":"workspace"));
$("workspace-filter").addEventListener("input",()=>guarded(loadWorkspacesNoRecursion)());
$("workspace-list").addEventListener("click",e=>{
 const button=e.target.closest("[data-ws]");
 if(button)guarded(()=>openWorkspace(button.dataset.ws))();
});
$("close-inspector").addEventListener("click",()=>{
 $("inspector").hidden=true;$("inspector-tabs").hidden=true;inspectorPanels=null;state.selected=null;document.querySelectorAll(".node.selected").forEach(n=>n.classList.remove("selected"));
});
$("inspector-content").addEventListener("click",e=>{
 const b=e.target.closest("[data-inspect-action]");
 if(b)guarded(()=>inspectAction(b.dataset.inspectAction))();
});
$("modal-close").addEventListener("click",closeModal);
$("modal-cancel").addEventListener("click",closeModal);
$("modal-shade").addEventListener("pointerdown",e=>{if(e.target===$("modal-shade"))closeModal();});
$("modal-form").addEventListener("submit",e=>{e.preventDefault();guarded(()=>submitModal(e))();});
$("cancel-link").addEventListener("click",()=>chooseTool("select"));

$("events-button").addEventListener("click",guarded(async()=>{
 if(!state.ws){toast("Selecione um workspace.");return;}
 state.selected=null;
 $("inspector").hidden=false;
 $("inspector-tabs").hidden=true;inspectorPanels=null;
 $("inspector-label").textContent="OBSERVABILIDADE";
 $("inspector-title").textContent="Atividade e auditoria";
 const events=state.detail?.events||[];
 const tasks=(state.detail?.tasks||[]).slice().reverse().slice(0,8);
 const handoffs=await api("/api/graph/handoffs?ws="+encodeURIComponent(state.ws));
 const receipts={pending:"Aguardando processamento",running:"CLI processando",
  answered:"Modelo respondeu",tool_completed:"Comando CLI executado",
  failed:"Modelo falhou",uncertain:"Execução incerta"};
 const governed=await Promise.all(tasks.map(t=>api("/api/task/governance?ws="+
  encodeURIComponent(state.ws)+"&id="+encodeURIComponent(t.id))));
 const workflow={QUEUED:"Na fila",RUNNING:"Em execução",VALIDATING:"Resultado aguarda validação",REPAIRING:"Resultado precisa de correção",
  IN_REVIEW:"Aguardando revisão",APPROVAL_REQUIRED:"Aguardando aprovação",BLOCKED:"Bloqueada",FAILED:"Falhou",CANCELLED:"Cancelada",COMPLETED:"Critérios verificados"};
 const waiting={authorization_required:"autorização da tarefa",dependency_incomplete:"tarefa dependente",
  work_item_blockers:"impedimento registrado",work_item_blocked:"liberação da tarefa"};
 function usageLabel(usage){
  if(!usage?.reported_calls)return "Consumo ainda não informado pelo provedor";
  return "Tokens informados: "+Number(usage.total_tokens).toLocaleString("pt-BR")+
   " (entrada "+Number(usage.input_tokens).toLocaleString("pt-BR")+", saída "+Number(usage.output_tokens).toLocaleString("pt-BR")+
   ")"+(usage.unreported_calls?" · Consumo parcial":"")+(usage.projection_pending?" · Atualização de orçamento pendente":"");
 }
 $("inspector-content").innerHTML=
  '<div class="inspect-field"><label>Tarefas recentes</label>'+
  (tasks.length?tasks.map((t,i)=>'<div class="inspect-block"><div>'+
     safe((governed[i].execution_status||t.status).toUpperCase())+' · '+safe(t.provider)+'</div><div>'+
     safe(t.prompt.slice(0,170))+'</div><div class="tiny">'+safe((t.result||"Sem resultado").slice(0,200))+'</div>'+
     '<div class="tiny">Fluxo: '+safe(workflow[governed[i].work_item.state]||"Requer conferência")+
     (governed[i].admission?.allowed===false?' · Aguardando: '+safe(waiting[governed[i].admission.reason]||"limite de orçamento"):'')+'</div>'+
     '<div class="tiny">'+safe(usageLabel(governed[i].provider_usage))+'</div>'+
     (governed[i].work_item.metadata.current_file_check_status==="changed_after_validation"?'<div class="tiny">Arquivo alterado após a validação</div>':'')+
     (governed[i].execution_status==="succeeded"&&governed[i].check_count?'<button data-task-verify="'+safe(t.id)+'">Reverificar arquivos</button>':'')+
     ((governed[i].execution_status||t.status)==="queued"?'<button data-task-control="'+(governed[i].work_item.state==="BLOCKED"?"unblock":"block")+
      '" data-task-id="'+safe(t.id)+'">'+(governed[i].work_item.state==="BLOCKED"?"Liberar tarefa":"Bloquear tarefa")+'</button>':'')+
     '</div>').join("")
   :'<div>Nenhuma tarefa registrada.</div>')+'</div>'+
  '<div class="inspect-field"><label>Mensagens entre agentes</label>'+
  (handoffs.length?handoffs.slice(0,20).map(h=>'<div class="inspect-block">'+
   '<div>'+safe(receipts[h.receipt_status]||"Aguardando")+
   ' · '+safe(h.status==="sent"?"Entregue ao terminal":h.status)+'</div>'+
   '<div class="tiny">'+safe((h.content||"").slice(0,160))+'</div>'+
   '<div class="tiny">Recibo '+safe(h.id.slice(0,12))+'</div></div>').join("")
   :'<div>Nenhuma mensagem encaminhada.</div>')+'</div>'+
  '<div class="inspect-field"><label>Eventos de auditoria</label>'+
   events.slice(0,60).map(x=>'<div class="inspect-block"><span class="tiny">'+
   new Date(x.created*1000).toLocaleTimeString("pt-BR")+'</span> · '+
   safe(x.kind)+'<div class="tiny">'+safe(x.detail||x.subject.slice(0,12))+'</div></div>').join("")+'</div>';
}));
$("inspector-content").addEventListener("click",guarded(async e=>{
 const verify=e.target.closest("[data-task-verify]");
 if(verify){
  const result=await api("/api/task/verify",{ws:requireWS(),id:verify.dataset.taskVerify});
  toast(result.status==="passed"?"Critérios verificados.":"O resultado precisa de conferência: "+result.status);
  $("events-button").click();return;
 }
 const button=e.target.closest("[data-task-control]");
 if(!button)return;
 await api("/api/task/control",{ws:requireWS(),id:button.dataset.taskId,action:button.dataset.taskControl});
 await refreshResources();$("events-button").click();
}));
$("show-overview").addEventListener("click",()=>$("events-button").click());
$("show-settings").addEventListener("click",()=>{
 state.selected=null;$("inspector").hidden=false;
 $("inspector-tabs").hidden=true;inspectorPanels=null;
 $("inspector-label").textContent="CONFIGURAÇÕES";
 $("inspector-title").textContent=location.pathname==="/canvas"?"SENTRA Canvas Web":"SENTRA Desktop";
 $("inspector-content").innerHTML=
 '<div class="inspect-field"><label>Ambiente</label><div>Aplicativo desktop nativo para Windows, usando WebView2. Servidor de controle somente em 127.0.0.1, autenticado.</div></div>'+
 '<div class="inspect-field"><label>Runtime</label><div>ConPTY: processos interativos reais. Gateway do modelo depende de autenticação externa.</div></div>'+
 '<div class="inspect-field"><label>Segurança</label><div>Terminais executam com o usuário Windows. O isolamento de workspaces na API não é sandbox de processos.</div></div>'+
 '<div class="inspect-actions"><button id="refresh-settings">Recarregar workspace</button></div>';
 $("refresh-settings").addEventListener("click",()=>guarded(()=>openWorkspace(state.ws))());
});
$("help-button").addEventListener("click",()=>{
 state.selected=null;$("inspector").hidden=false;
 $("inspector-tabs").hidden=true;inspectorPanels=null;
 $("inspector-label").textContent="AJUDA";
 $("inspector-title").textContent="Atalhos e controle";
 $("inspector-content").innerHTML=[
 ["V","Selecionar"],["T","Criar terminal"],["A","Criar agente"],["E","Criar equipe"],
 ["N","Criar nota"],["L","Ligar dois nós"],["Arrastar o fundo","Mover canvas"],
 ["Roda do mouse","Zoom"],["Esc","Cancelar ação"],["Ctrl + 0","Enquadrar nós"],
 ["Enter em terminal","Enviar comando"],["Arrastar cabeçalho","Mover nó e persistir posição"],
 ["Arrastar canto inferior","Redimensionar nó"],["Clique em porta","Conectar nós"],
 ["Duplo clique no cabeçalho","Ampliar/restaurar terminal"],["Esc","Restaurar terminal ampliado"]
 ].map(([key,value])=>'<div class="inspect-block" style="display:flex;justify-content:space-between;gap:12px"><span>'+safe(value)+'</span><span style="color:#e0ded9">'+safe(key)+'</span></div>').join("");
});
document.addEventListener("keydown",e=>{
 if(e.key==="Escape"){
  if(!$("modal-shade").hidden){if(!modalSending)closeModal();return;}
  if(state.fullscreen){e.preventDefault();restoreTerminal();return;}
  if(e.target.closest(".term-output"))return;
  chooseTool("select");return;
 }
 if(e.target.closest(".term-output"))return;
 if(e.ctrlKey&&e.key==="0"){e.preventDefault();fitNodes();return;}
 if(! $("modal-shade").hidden)return;
 if(e.target.closest("input,textarea,select,[contenteditable]"))return;
 const key=e.key.toLowerCase();
 const tool={v:"select",t:"terminal",a:"agent",e:"team",n:"note",l:"link"}[key];
 if(tool){e.preventDefault();guarded(()=>chooseTool(tool))();}
 if(e.code==="Space"){e.preventDefault();state.space=true;chooseTool("pan");}
});
document.addEventListener("keyup",e=>{
 if(e.code==="Space"&&state.space){state.space=false;chooseTool("select");}
});
window.addEventListener("blur",()=>{state.space=false;state.move=null;$("viewport").classList.remove("panning");});
canvasSurface.addEventListener("dblclick",e=>{
 const node=e.target.closest(".node");
 if(node){if(node.classList.contains("has-terminal")&&e.target.closest(".node-header")&&!e.target.closest("button")){e.preventDefault();expandTerminal(node.dataset.node);}return;}
 if(e.target.closest("button,input,.glass"))return;
 if(state.ws)openModal("terminal");
});
window.addEventListener("resize",setView);
setView();
if(!token){
 toast("Sessão local não autenticada. Abra o SENTRA pela janela do aplicativo.");
 emptyView(true);
}else{
 guarded(async()=>{
  state.integrations=await api("/api/integrations");
  api("/api/models").then(catalog=>{state.models=Array.isArray(catalog.models)?catalog.models:[];})
    .catch(()=>{state.models=[];});
  await loadWorkspaces();
  setInterval(pollAll,400);
  setInterval(()=>guarded(refreshResources)(),5500);
 })();
}

/* Native HWND actions are exposed by pywebview, not by the loopback HTTP API. */
function windowAction(name){
 const bridge=window.pywebview&&window.pywebview.api;
 if(bridge&&typeof bridge[name]==="function")return bridge[name]();
 return Promise.resolve(false);
}
$("window-minimize").addEventListener("click",()=>guarded(()=>windowAction("minimize"))());
$("window-maximize").addEventListener("click",()=>guarded(()=>windowAction("toggle_maximize"))());
$("window-close").addEventListener("click",()=>guarded(()=>windowAction("close"))());

/* Keyboard-first quick actions. Cult UI Halo Search/Dock interaction patterns,
 * implemented locally to preserve the Canvas WebView2/CSP dependency boundary. */
const commandOverlay=$("command-overlay"),commandInput=$("command-query"),commandResults=$("command-results");
function commands(){
 const actions=[
   {id:"terminal",symbol:"▣",label:"Novo terminal",kind:"Execução"},
   {id:"agent",symbol:"◇",label:"Novo agente SENTRA CLI",kind:"Orquestração"},
   {id:"team",symbol:"◎",label:"Criar equipe",kind:"Orquestração"},
   {id:"note",symbol:"▤",label:"Nova nota",kind:"Canvas"},
   {id:"fit",symbol:"⛶",label:"Enquadrar todos os nós",kind:"Visualização"},
   {id:"overview",symbol:"◷",label:"Atividade e auditoria",kind:"Observabilidade"},
   {id:"workspace",symbol:"＋",label:"Novo workspace",kind:"Projetos"}
 ];
 const nodes=state.nodes.map(n=>({
   id:"node:"+n.id,symbol:{terminal:"▣",agent:"◇",team:"◎",note:"▤"}[n.kind]||"⌁",
   label:n.title,kind:"Ir para "+{terminal:"terminal",agent:"agente",team:"equipe",note:"nota"}[n.kind]
 }));
 return state.ws?[...actions,...nodes]:[actions[6]];
}
function renderCommands(){
 const query=commandInput.value.trim().toLocaleLowerCase("pt-BR");
 $("command-clear").hidden=!commandInput.value;
 const items=commands().filter(item=>(item.label+" "+item.kind).toLocaleLowerCase("pt-BR").includes(query)).slice(0,24);
 commandResults.innerHTML=items.length?items.map(item=>
 '<button type="button" class="command-result" data-command="'+safe(item.id)+'">'+
 '<span class="command-symbol" aria-hidden="true">'+safe(item.symbol)+'</span>'+
 '<span class="command-label">'+safe(item.label)+'</span>'+
 '<span class="command-kind">'+safe(item.kind)+'</span></button>').join("")
 :'<div class="command-empty">Nenhum comando ou nó encontrado.</div>';
}
function closeCommands(){
 commandOverlay.hidden=true;commandInput.value="";commandResults.replaceChildren();
 endOverlayFocus(commandOverlay);
}
function showCommands(){
 if(!$("modal-shade").hidden || state.fullscreen)return;
 beginOverlayFocus(commandOverlay);
 commandOverlay.hidden=false;commandInput.value="";renderCommands();commandInput.focus();
}
function executeCommand(id){
 closeCommands();
 if(id.startsWith("node:")){
  const node=nodeBy(id.slice(5));
  if(!node)return;
  const bounds=$("viewport").getBoundingClientRect();
  state.x=bounds.width/2-(node.x+node.width/2)*state.scale;
  state.y=bounds.height/2-(node.y+node.height/2)*state.scale;
  setView();showInspector(node);return;
 }
 if(id==="fit"){fitNodes();return;}
 if(id==="overview"){$("events-button").click();return;}
 if(["terminal","agent","team","note","workspace"].includes(id))openModal(id);
}
document.addEventListener("keydown",e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"&&!e.target.closest(".term-output")){
  e.preventDefault();e.stopPropagation();
  if(commandOverlay.hidden)showCommands();else closeCommands();
  return;
 }
 if(commandOverlay.hidden)return;
 if(e.key==="Escape"){e.preventDefault();e.stopPropagation();closeCommands();return;}
 if(e.key==="ArrowDown"||e.key==="ArrowUp"){
  e.preventDefault();e.stopPropagation();
  const controls=[commandInput,...commandResults.querySelectorAll("button")];
  const current=controls.indexOf(document.activeElement);
  const delta=e.key==="ArrowDown"?1:-1;
  controls[(current+delta+controls.length)%controls.length]?.focus();
 }else if(e.key==="Enter"&&document.activeElement===commandInput){
  e.preventDefault();e.stopPropagation();
  commandResults.querySelector("button")?.click();
 }
},true);
$("command-launch").addEventListener("click",showCommands);
commandInput.addEventListener("input",renderCommands);
commandResults.addEventListener("click",e=>{
 const button=e.target.closest("[data-command]");
 if(button)guarded(()=>executeCommand(button.dataset.command))();
});
commandOverlay.addEventListener("pointerdown",e=>{if(e.target===commandOverlay)closeCommands();});

/* Magnetic Dock: spring-like restrained magnification, no React runtime. */
const sentraDock=document.querySelector(".toolbar");
const dockTools=[...sentraDock.querySelectorAll(".tool")];
const noDockMotion=window.matchMedia("(prefers-reduced-motion: reduce)");
function resetDock(){dockTools.forEach(item=>item.style.removeProperty("--dock-zoom"));}
sentraDock.addEventListener("pointermove",e=>{
 if(noDockMotion.matches||e.pointerType==="touch")return;
 for(const item of dockTools){
  const rect=item.getBoundingClientRect(),distance=Math.abs(e.clientX-(rect.left+rect.width/2));
  const value=1+.18*Math.exp(-(distance*distance)/(2*55*55));
  item.style.setProperty("--dock-zoom",value.toFixed(3));
 }
},{passive:true});
sentraDock.addEventListener("pointerleave",resetDock,{passive:true});
noDockMotion.addEventListener?.("change",resetDock);
$("command-clear").addEventListener("click",()=>{
 commandInput.value="";renderCommands();commandInput.focus();
});
/* Composer preserves textarea drafting, but dispatch uses the backend's safe
 * single-line contract. No implicit shell commands or attachment uploads. */
$("modal-form").addEventListener("input",e=>{
 if(e.target.name!=="message")return;
 const counter=$("composer-count");if(counter)counter.textContent=e.target.value.length+" / 4000";
});
$("modal-form").addEventListener("keydown",e=>{
 if(e.target.tagName==="TEXTAREA"&&(e.ctrlKey||e.metaKey)&&e.key==="Enter"){
  e.preventDefault();e.stopPropagation();
  if(!modalSending)$("modal-form").requestSubmit();
 }
});
