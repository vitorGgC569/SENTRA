"use strict";
const $ = id => document.getElementById(id);
const esc = x => String(x ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ptoken = new URLSearchParams(location.hash.slice(1)).get("token");
if (ptoken) { sessionStorage.setItem("sentra_canvas_token",ptoken);history.replaceState(null,"",location.pathname); }
const token = sessionStorage.getItem("sentra_canvas_token");
let workspace = "", detail = null, cursors={}, lastPanels="", busy=false;
function notice(msg) { $("notice").textContent=msg;$("notice").style.display="block";setTimeout(()=>$("notice").style.display="none",5000); }
async function api(path,body=null) {
 const headers={"Authorization":"Bearer "+token};
 if(body!==null) headers["Content-Type"]="application/json";
 const res=await fetch(path,{method:body===null?"GET":"POST",headers,body:body===null?undefined:JSON.stringify(body),cache:"no-store"});
 let value;try {value=await res.json();} catch {value={error:"Resposta inválida"};}
 if(!res.ok) throw Error(value.error || "HTTP "+res.status);
 return value;
}
async function action(fn) {
 try {await fn();}catch(err){notice(err.message);}
}
function options(rows,placeholder="Selecione…") {
 return '<option value="">'+esc(placeholder)+'</option>'+rows.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+'</option>').join("");
}
async function loadWorkspaces() {
 let all=await api("/api/workspaces");
 $("ws-count").textContent=all.length;
 $("workspaces").innerHTML=all.map(w=>'<button type="button" data-ws="'+esc(w.id)+'" class="'+(w.id===workspace?"active":"")+'">▤ &nbsp;'+esc(w.name)+'</button>').join("");
 if (!workspace && all.length) workspace=all[0].id;
 if (workspace) await refresh();
}
function termCard(t) {
 const running=t.status==="running";
 return '<article class="terminal" draggable="true" data-terminal="'+esc(t.id)+'">'+
  '<div class="terminal-head"><span class="dot '+(running?"":"off")+'"></span>'+
  '<strong>'+esc(t.name)+'</strong><span class="terminal-meta">'+esc(t.shell)+' · '+esc(t.status)+'</span>'+
  '<button type="button" data-rename="'+esc(t.id)+'" title="Renomear terminal">✎</button>'+
  '<button type="button" data-duplicate="'+esc(t.id)+'" title="Duplicar terminal">⧉</button>'+
  '<button class="danger" type="button" data-close="'+esc(t.id)+'">Fechar</button></div>'+
  '<pre class="screen" id="screen-'+esc(t.id)+'">'+(running?"Conectando ao ConPTY…":"Sessão interrompida. O histórico de eventos continua disponível.")+'</pre>'+
  '<div class="terminal-input"><span>❯</span><input aria-label="Entrada do terminal '+esc(t.name)+'" data-input="'+esc(t.id)+'" '+(running?"":"disabled")+' placeholder="'+(running?"Digite e pressione Enter":"Sessão não ativa")+'" autocomplete="off"></div></article>';
}
async function refresh() {
 if(!workspace){$("dashboard").hidden=true;$("empty").hidden=false;return;}
 detail=await api("/api/workspace?ws="+encodeURIComponent(workspace));
 $("dashboard").hidden=false;$("empty").hidden=true;
 $("ws-title").textContent=detail.workspace.name;
 $("ws-path").textContent=detail.workspace.path;
 $("counts").textContent=detail.terminals.filter(t=>t.status==="running").length+" terminais ativos • "+detail.agents.length+" agentes";
 const signature=detail.terminals.map(t=>t.id+t.status).join("|");
 if(signature!==lastPanels){
  lastPanels=signature;cursors={};
  $("terminals").innerHTML=detail.terminals.length?detail.terminals.map(termCard).join(""):'<p class="muted">Nenhum terminal neste workspace. Crie um para começar.</p>';
 }
 $("agents").innerHTML=detail.agents.map(a=>'<div class="item"><strong>'+esc(a.name)+'</strong><span class="pill">'+esc(a.role)+'</span><small>'+esc(a.model)+' • '+(a.terminal_id?"CLI iniciado, autenticação não comprovada":"configurado")+'</small></div>').join("") || '<p class="muted">Ainda não há agentes.</p>';
 $("teams").innerHTML=detail.teams.map(t=>'<div class="item"><strong>'+esc(t.name)+'</strong><small>Equipe registrada • '+esc(t.id.slice(0,8))+'</small></div>').join("") || '<p class="muted">Crie uma equipe para delegar.</p>';
 $("tasks").innerHTML=detail.tasks.slice().reverse().map(t=>'<div class="item"><strong>'+esc(t.status)+'</strong><span class="pill">'+esc(t.provider)+'</span><small>'+esc(t.prompt.slice(0,120))+'</small><small>'+esc((t.result||"Sem resultado").slice(0,600))+'</small></div>').join("") || '<p class="muted">Nenhuma delegação ainda.</p>';
 const q=$("event-search").value.trim();
 renderEvents(q?await api("/api/events?ws="+encodeURIComponent(workspace)+"&q="+encodeURIComponent(q)):detail.events);
 $("team-coordinator").innerHTML=options(detail.agents);
 $("team-workers").innerHTML=detail.agents.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+'</option>').join("");
 $("task-team").innerHTML=options(detail.teams);
 if(detail.teams.length)await workersForTeam(detail.teams[0].id);
 for(const t of detail.terminals){pollTerminal(t.id);}
}
function renderEvents(events){
 $("events").innerHTML=events.map(e=>'<div class="event"><span>'+new Date(e.created*1000).toLocaleTimeString("pt-BR")+'</span><span>'+esc(e.kind)+'</span><span>'+esc((e.detail||e.subject).slice(0,65))+'</span></div>').join("") || '<p class="muted">Nenhum evento encontrado.</p>';
}
$("event-search").addEventListener("input",()=>action(async()=>{
 if(!workspace)return;
 const ws=workspace,q=$("event-search").value.trim();
 const events=await api("/api/events?ws="+encodeURIComponent(ws)+"&q="+encodeURIComponent(q));
 if(ws===workspace && q===$("event-search").value.trim())renderEvents(events);
}));
async function workersForTeam(id){
 if(!id){$("task-worker").innerHTML="";return;}
 const members=await api("/api/team?ws="+encodeURIComponent(workspace)+"&id="+encodeURIComponent(id));
 $("task-worker").innerHTML=options(members.filter(x=>x.team_role==="worker"));
}

async function pollTerminal(id){
 if(!workspace || !$("screen-"+id)) return;
 try {
  const result=await api("/api/terminal/output?ws="+encodeURIComponent(workspace)+"&id="+encodeURIComponent(id)+"&cursor="+(cursors[id]||0));
  const screen=$("screen-"+id);
  if(!screen) return;
  let text=result.text||"";
  screen.title=result.persisted===false?"Histórico não salvo; mantenha esta sessão aberta."
    :result.recoverable===false?"Histórico recuperado. Abra uma nova sessão para continuar."
    :"Histórico salvo no computador.";
  // Basic VT filtering for text commands. Full ANSI/TUI rendering is pending.
  text=text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,"").replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g,"");
  if(text){if(!(id in cursors)||result.truncated)screen.textContent="";screen.textContent=(screen.textContent+text).slice(-120000);screen.scrollTop=screen.scrollHeight;}
  cursors[id]=result.cursor;
 }catch(err){notice(err.message);}
}
function currentWs(){if(!workspace)throw Error("Selecione um workspace");return workspace;}
$("new-ws").addEventListener("submit",e=>{e.preventDefault();action(async()=>{
 const row=await api("/api/workspaces",{name:$("ws-name").value.trim()});
 workspace=row.id;lastPanels="";$("ws-name").value="";await loadWorkspaces();
});});
$("workspaces").addEventListener("click",e=>{const button=e.target.closest("[data-ws]");if(!button)return;action(async()=>{
 workspace=button.dataset.ws;lastPanels="";await loadWorkspaces();
});});
$("refresh").addEventListener("click",()=>action(async()=>{await loadWorkspaces()}));
$("new-terminal").addEventListener("submit",e=>{e.preventDefault();action(async()=>{
 await api("/api/terminals",{ws:currentWs(),name:$("terminal-name").value.trim(),shell:$("terminal-shell").value});
 $("terminal-name").value="";await refresh();
});});
$("new-agent").addEventListener("submit",e=>{e.preventDefault();action(async()=>{
 await api("/api/agents",{ws:currentWs(),name:$("agent-name").value.trim(),
 model:$("agent-model").value.trim(),role:$("agent-role").value,
 start:$("agent-start").checked});
 $("agent-name").value="";await refresh();
});});
$("new-team").addEventListener("submit",e=>{e.preventDefault();action(async()=>{
 await api("/api/teams",{ws:currentWs(),name:$("team-name").value.trim(),
 coordinator:$("team-coordinator").value,
 workers:Array.from($("team-workers").selectedOptions).map(o=>o.value)});
 $("team-name").value="";await refresh();
});});
$("task-team").addEventListener("change",e=>action(()=>workersForTeam(e.target.value)));
$("new-task").addEventListener("submit",e=>{e.preventDefault();action(async()=>{
 const provider=$("task-provider").value;
 const approved=provider==="sentra-cli" && confirm("Autorizar SENTRA CLI REAL a executar ferramentas e possivelmente modificar arquivos do workspace original? Sem sandbox adicional.");
 if(provider==="sentra-cli" && !approved)return;
 const request_key=crypto.randomUUID();
 await api("/api/tasks",{ws:currentWs(),team:$("task-team").value,
 agent:$("task-worker").value,prompt:$("task-prompt").value,
 provider,approved,request_key});
 $("task-prompt").value="";await refresh();notice("Tarefa registrada. Acompanhe o estado na lista.");
});});
$("terminals").addEventListener("click",e=>{
 const closeId=e.target.dataset.close;
 const renameId=e.target.dataset.rename;
 const duplicateId=e.target.dataset.duplicate;
 if(closeId){
  if(confirm("Encerrar o processo do terminal selecionado?"))
   action(async()=>{await api("/api/terminal/close",{ws:currentWs(),id:closeId,confirm:true});await refresh();});
 }else if(renameId){
  const source=detail?.terminals.find(t=>t.id===renameId);
  const name=prompt("Novo nome do terminal",source?.name||"");
  if(name)action(async()=>{await api("/api/terminal/rename",{ws:currentWs(),id:renameId,name});await refresh();});
 }else if(duplicateId){
  const source=detail?.terminals.find(t=>t.id===duplicateId);
  const name=prompt("Nome do novo terminal independente",(source?.name||"terminal")+"_copia");
  if(name)action(async()=>{await api("/api/terminal/duplicate",{ws:currentWs(),id:duplicateId,name});await refresh();});
 }
});
$("terminals").addEventListener("keydown",e=>{
 const id=e.target.dataset.input;
 if(!id)return;
 let data="";
 if(e.key==="Enter"){data=e.target.value+"\r";e.target.value="";}
 else if(e.key==="c"&&e.ctrlKey){data="\x03";}
 else if(e.key==="ArrowUp"){data="\x1b[A";}
 else if(e.key==="ArrowDown"){data="\x1b[B";}
 else return;
 e.preventDefault();
 action(()=>api("/api/terminal/input",{ws:currentWs(),id,data}));
});
let dragged=null;
$("terminals").addEventListener("dragstart",e=>{
 const card=e.target.closest(".terminal");if(!card)return;
 dragged=card;card.classList.add("dragging");
});
$("terminals").addEventListener("dragend",()=>{
 if(dragged)dragged.classList.remove("dragging");dragged=null;
});
$("terminals").addEventListener("dragover",e=>{
 e.preventDefault();
 const target=e.target.closest(".terminal");
 if(dragged && target && dragged!==target){
  const box=target.getBoundingClientRect();
  $("terminals").insertBefore(dragged,e.clientX<box.left+box.width/2?target:target.nextSibling);
 }
});
setInterval(()=>{
 if(workspace && !busy){
  busy=true;
  Promise.all((detail?.terminals||[]).filter(t=>t.status==="running").map(t=>pollTerminal(t.id)))
    .finally(()=>{busy=false;});
 }
},350);
setInterval(()=>{if(workspace && !document.hidden)action(refresh);},6000);
if(!token){notice("Token local ausente. Abra a janela pela inicialização SENTRA Canvas.");}
else action(loadWorkspaces);
