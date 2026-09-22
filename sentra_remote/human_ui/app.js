
const ui = {
  data: null,
  page: "conversations",
  conversationId: null,
  selectedWorkspace: "",
  search: "",
  activityTab: "events",
  refreshBusy: false,
  typing: false,
};

const $ = (sel) => document.querySelector(sel);
const esc = (value="") => String(value)
  .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
  .replaceAll('"',"&quot;").replaceAll("'","&#039;");

function fmtTime(value){
  if(!value) return "—";
  let d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if(Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const same = d.toDateString() === now.toDateString();
  return same
    ? d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})
    : d.toLocaleDateString("pt-BR",{day:"2-digit",month:"short"})+" · "+d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"});
}
function fmtDuration(seconds){
  if(seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "—";
  seconds = Math.max(0, Number(seconds));
  if(seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const m = Math.floor(seconds/60), s = Math.round(seconds%60);
  return `${m} min ${String(s).padStart(2,"0")} s`;
}
function stateClass(state){
  state = String(state||"").toUpperCase();
  if(["COMPLETED","CANDIDATE_READY","APPLIED","READY","PASSED","OK"].includes(state)) return "ok";
  if(["RUNNING","PENDING","QUEUED","CANCELLING","IN_PROGRESS"].includes(state)) return "active";
  if(["FAILED","CANCELLED","INTERRUPTED","BLOCKED","REJECTED"].includes(state)) return "bad";
  return "";
}
function stateLabel(state){
  const map={
    COMPLETED:"Concluído",CANDIDATE_READY:"Candidato pronto",APPLIED:"Aplicado",
    RUNNING:"Em andamento",PENDING:"Pendente",QUEUED:"Na fila",FAILED:"Falhou",
    CANCELLED:"Cancelado",INTERRUPTED:"Interrompido",BLOCKED:"Bloqueado",
  };
  return map[String(state||"").toUpperCase()] || String(state||"Desconhecido");
}
function shortPath(path){
  const parts=String(path||"").replaceAll("\\","/").split("/").filter(Boolean);
  return parts.slice(-2).join("/") || path || "—";
}
function bytes(n){
  n=Number(n||0); if(n<1024)return `${n} B`;
  if(n<1024*1024)return `${(n/1024).toFixed(1)} KB`;
  return `${(n/1024/1024).toFixed(1)} MB`;
}
function toast(message,bad=false){
  const el=$("#toast"); el.textContent=message; el.className="toast show"+(bad?" bad":"");
  clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.className="toast",2400);
}
function detailSummary(details){
  if(!details || typeof details!=="object") return "";
  const keys=["operation","target","workspace","job_id","run_id","status","network","mode"];
  return keys.filter(k=>details[k]!==undefined && details[k]!==null)
    .slice(0,4).map(k=>`${k}: ${String(details[k])}`).join(" · ");
}
async function api(name,...args){
  if(!window.pywebview?.api?.[name]) throw new Error(`API ${name} indisponível`);
  return await window.pywebview.api[name](...args);
}
async function refresh(force=false){
  if(ui.refreshBusy) return;
  if(ui.typing && !force) return;
  ui.refreshBusy=true;
  try{
    const data=await api("bootstrap",ui.conversationId);
    ui.data=data;
    if(data.conversation) ui.conversationId=data.conversation.id;
    if(!ui.selectedWorkspace){
      ui.selectedWorkspace=data.conversation?.workspace || data.workspaces?.[0]?.path || "";
    }
    updateChrome();
    render();
  }catch(err){ toast(String(err),true); }
  finally{ ui.refreshBusy=false; }
}
function updateChrome(){
  const d=ui.data||{};
  $("#profile-pill").textContent=d.product?.profile||"—";
  const ws=(d.workspaces||[]).find(x=>x.path===ui.selectedWorkspace) || d.workspaces?.[0];
  $("#workspace-pill").textContent=ws?.name||"Nenhum workspace";
  document.querySelectorAll(".nav-item[data-page]").forEach(el=>el.classList.toggle("active",el.dataset.page===ui.page));
}
function render(){
  if(!ui.data) return;
  if(ui.page==="runs") return renderRuns();
  if(ui.page==="workspaces") return renderWorkspaces();
  if(ui.page==="agents") return renderAgents();
  return renderConversations();
}
function filteredConversations(){
  const q=ui.search.trim().toLowerCase();
  return (ui.data.conversations||[]).filter(c=>!q || `${c.title} ${c.workspace} ${c.last_message||""}`.toLowerCase().includes(q));
}
function workspaceOptions(selected){
  return (ui.data.workspaces||[]).map(w=>`<option value="${esc(w.path)}" ${w.path===selected?"selected":""}>${esc(w.name)}</option>`).join("");
}
function resultStrip(meta){
  if(!meta || typeof meta!=="object") return "";
  const metrics=meta.metrics||{};
  const completed=meta.completed_tasks ?? metrics.tasks_completed;
  const total=meta.total_tasks ?? metrics.tasks_total;
  const pass=metrics.validation_pass_rate;
  const repairs=metrics.repair_rounds;
  const items=[];
  if(completed!==undefined && total!==undefined) items.push(["Tarefas",`${completed}/${total}`]);
  if(pass!==undefined && pass!==null) items.push(["Validações",`${Math.round(Number(pass)*100)}% aprovadas`]);
  if(repairs!==undefined && repairs!==null) items.push(["Repair",`${repairs} rodada${Number(repairs)===1?"":"s"}`]);
  if(!items.length) return "";
  return `<div class="result-strip">${items.slice(0,3).map(([a,b])=>`<div class="result-stat"><b>${esc(a)}</b><span>${esc(b)}</span></div>`).join("")}</div>`;
}
function renderMessage(m,workspace){
  const role=m.role||"system";
  if(role==="user"){
    return `<div class="message user"><div class="message-body">${esc(m.body)}</div></div>`;
  }
  if(role==="assistant"){
    const meta=m.metadata||{};
    const runButton=m.run_id ? `<button class="action" data-open-run="oma:${esc(m.run_id)}">Ver execução</button>` : "";
    const diffButton=workspace ? `<button class="action" data-diff="${esc(workspace)}">Ver diff atual</button>` : "";
    return `<div class="message assistant">
      <div class="avatar">S</div>
      <div class="assistant-content">
        <div class="message-label">SENTRA · ${fmtTime(m.created)}</div>
        <div class="message-text">${esc(m.body)}</div>
        ${resultStrip(meta)}
        ${(runButton||diffButton)?`<div class="message-actions">${runButton}${diffButton}</div>`:""}
      </div>
    </div>`;
  }
  const task=(ui.data.runs||[]).find(r=>r.kind==="task" && Number(r.id)===Number(m.task_id));
  const state=task?.state || m.metadata?.state || "QUEUED";
  return `<div class="message system"><div class="execution-line">
    <span class="status-dot ${stateClass(state)}"></span>
    <span>Tarefa #${esc(m.task_id||"")} · ${esc(stateLabel(state))}</span>
    ${task?`<button class="action" data-open-run="task:${esc(task.id)}">Detalhes</button>`:""}
  </div></div>`;
}
function composer(conv){
  const workspace=conv?.workspace || ui.selectedWorkspace || ui.data.workspaces?.[0]?.path || "";
  if(!(ui.data.workspaces||[]).length){
    return `<div class="composer-wrap"><div class="empty-state"><div class="empty-state-inner">
      <h2>Nenhum workspace aprovado</h2>
      <p>Abra o Control Center e autorize ao menos um workspace antes de enviar tarefas.</p>
      <button class="action primary" data-control>Open Control Center</button>
    </div></div></div>`;
  }
  return `<div class="composer-wrap"><div class="composer">
      ${conv?"":`<select id="composer-workspace" class="workspace-select">${workspaceOptions(workspace)}</select>`}
      <textarea id="composer" rows="1" placeholder="Envie uma tarefa para o SENTRA…"></textarea>
      <button id="send-message" class="send-button" aria-label="Enviar">↑</button>
    </div></div>`;
}
function renderConversations(){
  const convs=filteredConversations();
  const conv=ui.data.conversation && (!ui.conversationId || ui.data.conversation.id===ui.conversationId) ? ui.data.conversation : null;
  const view=$("#view");
  view.innerHTML=`<div class="page">
    <section class="library page-column">
      <div class="library-head"><div class="library-title">Conversas</div><button id="new-conversation" class="new-button">＋</button></div>
      <input id="conversation-search" class="mini-search" placeholder="Buscar conversas" value="${esc(ui.search)}">
      <div>${convs.length?convs.map(c=>`<button class="conversation-item ${conv?.id===c.id?"active":""}" data-conv="${esc(c.id)}">
        <strong>${esc(c.title)}</strong><span>${esc(shortPath(c.workspace))} · ${fmtTime(c.updated)}</span>
      </button>`).join(""):`<div class="library-empty">Nenhuma conversa ainda.<br>Comece uma nova tarefa.</div>`}</div>
    </section>
    <section class="chat">
      ${conv?`<header class="chat-head"><div class="chat-head-row"><div>
        <h1 class="chat-title">${esc(conv.title)}</h1><div class="chat-sub">${esc(shortPath(conv.workspace))} · atividade real</div>
        <div class="chat-meta"><span class="meta-chip">${esc(ui.data.product?.profile||"—")}</span><span class="meta-chip">${(conv.messages||[]).length} mensagens</span></div>
      </div><button class="icon-button" id="archive-conversation" title="Arquivar">···</button></div></header>`:
      `<header class="chat-head"><h1 class="chat-title">Nova conversa</h1><div class="chat-sub">A tarefa será executada pela fila OMA real</div></header>`}
      <div class="messages">
        ${conv?(conv.messages||[]).map(m=>renderMessage(m,conv.workspace)).join(""):
          `<div class="empty-state"><div class="empty-state-inner"><h2>O que vamos construir?</h2><p>Envie uma tarefa. O SENTRA mostrará somente estados, logs, validações e resultados produzidos pelo runtime real.</p></div></div>`}
      </div>
      ${composer(conv)}
    </section>
  </div>`;
  bindConversationEvents(conv);
}
function bindConversationEvents(conv){
  $("#conversation-search")?.addEventListener("input",e=>{ui.search=e.target.value;renderConversations();});
  document.querySelectorAll("[data-conv]").forEach(el=>el.addEventListener("click",async()=>{
    ui.conversationId=el.dataset.conv;
    const c=await api("conversation",ui.conversationId);
    ui.data.conversation=c; ui.selectedWorkspace=c.workspace; updateChrome(); renderConversations();
  }));
  $("#new-conversation")?.addEventListener("click",()=>{ui.conversationId=null;ui.data.conversation=null;renderConversations();});
  $("#composer-workspace")?.addEventListener("change",e=>{ui.selectedWorkspace=e.target.value;updateChrome();});
  const textarea=$("#composer");
  if(textarea){
    textarea.addEventListener("focus",()=>ui.typing=true);
    textarea.addEventListener("blur",()=>ui.typing=false);
    textarea.addEventListener("input",()=>{textarea.style.height="auto";textarea.style.height=Math.min(textarea.scrollHeight,150)+"px";});
    textarea.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendCurrentMessage();}});
  }
  $("#send-message")?.addEventListener("click",sendCurrentMessage);
  $("#archive-conversation")?.addEventListener("click",async()=>{
    if(!conv)return; await api("archive_conversation",conv.id);ui.conversationId=null;await refresh(true);
  });
  bindCommonActions();
  const msg=$(".messages"); if(msg) msg.scrollTop=msg.scrollHeight;
}
async function sendCurrentMessage(){
  const textarea=$("#composer"); if(!textarea) return;
  const body=textarea.value.trim(); if(!body)return;
  const conv=ui.data.conversation;
  const workspace=conv?.workspace || $("#composer-workspace")?.value || ui.selectedWorkspace;
  const button=$("#send-message"); button.disabled=true;
  try{
    const result=await api("send_message",conv?.id||null,workspace,body);
    ui.conversationId=result.conversation.id; ui.selectedWorkspace=result.conversation.workspace;
    textarea.value="";ui.typing=false;await refresh(true);
  }catch(err){toast(String(err),true);button.disabled=false;}
}
function filteredRuns(){
  const q=ui.search.trim().toLowerCase();
  return (ui.data.runs||[]).filter(r=>!q || `${r.title||""} ${r.kind||""} ${r.state||""} ${r.workspace||""}`.toLowerCase().includes(q));
}
function renderRuns(){
  const runs=filteredRuns();
  $("#view").innerHTML=`<section class="content-page page-column">
    <div class="page-header"><div><h1>Runs</h1><p>Execuções persistidas pelo SENTRA. Nenhum estado é simulado.</p></div></div>
    ${runs.length?`<div class="run-list">${runs.map(r=>`<button class="run-row" data-open-run="${esc(r.key)}">
      <span class="status-dot ${stateClass(r.state)}"></span>
      <span class="run-main"><b><span class="run-kind">${esc(r.kind)}</span>${esc(r.title||r.id)}</b>
      <span>${esc(stateLabel(r.state))}${r.workspace?` · ${esc(shortPath(r.workspace))}`:""}</span></span>
      <span class="run-time">${fmtTime(r.updated||r.created)}</span>
    </button>`).join("")}</div>`:
    `<div class="empty-state"><div class="empty-state-inner"><h2>Nenhuma run registrada</h2><p>Runs surgirão aqui conforme tarefas, jobs MCP ou pesquisas forem executados.</p></div></div>`}
  </section>`;
  bindCommonActions();
}
function renderWorkspaces(){
  const workspaces=ui.data.workspaces||[];
  $("#view").innerHTML=`<section class="content-page page-column">
    <div class="page-header"><div><h1>Workspaces</h1><p>Permissões aprovadas no Control Center.</p></div>
      <button class="action" data-control>Gerenciar permissões</button></div>
    ${workspaces.length?`<div class="workspace-grid">${workspaces.map(w=>`<article class="workspace-card">
      <h3>${esc(w.name)}</h3><div class="workspace-path">${esc(w.path)}</div>
      <div class="permission-row">${(w.permissions||[]).map(p=>`<span class="permission">${esc(p)}</span>`).join("")}</div>
      <div class="message-actions"><button class="action" data-reveal="${esc(w.path)}">Abrir no Explorer</button><button class="action" data-diff="${esc(w.path)}">Ver diff</button></div>
    </article>`).join("")}</div>`:
    `<div class="empty-state"><div class="empty-state-inner"><h2>Nenhum workspace aprovado</h2><p>Adicione workspaces pelo Control Center.</p><button class="action primary" data-control>Open Control Center</button></div></div>`}
  </section>`;
  bindCommonActions();
}
function renderAgents(){
  const audit=ui.data.activity||[];
  const logs=ui.data.logs||[];
  const oma=(ui.data.runs||[]).filter(r=>r.kind==="oma");
  $("#view").innerHTML=`<section class="content-page page-column">
    <div class="page-header"><div><h1>Agentes & atividade</h1><p>Tráfego e logs emitidos pelo runtime real.</p></div>
      <div class="segmented">
        <button data-activity-tab="events" class="${ui.activityTab==="events"?"active":""}">Tráfego</button>
        <button data-activity-tab="runs" class="${ui.activityTab==="runs"?"active":""}">Agentes</button>
        <button data-activity-tab="logs" class="${ui.activityTab==="logs"?"active":""}">Logs</button>
      </div></div>
    ${ui.activityTab==="events"?renderActivityEvents(audit):ui.activityTab==="runs"?renderAgentRuns(oma):renderLogs(logs)}
  </section>`;
  document.querySelectorAll("[data-activity-tab]").forEach(el=>el.addEventListener("click",()=>{ui.activityTab=el.dataset.activityTab;renderAgents();}));
  bindCommonActions();
}
function renderActivityEvents(items){
  return `<div class="activity-layout"><div class="activity-list">
    ${items.length?items.map(item=>`<div class="activity-row">
      <span class="status-dot ${stateClass(item.outcome)}"></span>
      <div><strong>${esc(item.action||"evento")}</strong><p>${esc(detailSummary(item.details||{}))}</p></div>
      <time>${fmtTime(item.timestamp)}</time>
    </div>`).join(""):`<div class="empty-state"><div class="empty-state-inner"><h2>Sem eventos de auditoria</h2><p>O audit log ainda não contém atividade.</p></div></div>`}
  </div><aside><div class="side-card"><h3>Runtime</h3>${renderRuntimeStatus()}</div></aside></div>`;
}
function renderRuntimeStatus(){
  const s=ui.data.status||{};
  const entries=[["MCP",s.mcp],["Tunnel",s.tunnel],["Edge",s.edge],["Sandbox",s.sandbox],["Git",s.git],["Remote",s.remote_agent]];
  return entries.map(([name,item])=>`<div class="log-item"><span><span class="status-dot ${item?.ok?"ok":""}" style="display:inline-block;margin-right:8px"></span>${name}</span><small>${item?.ok?"ready":"atenção"}</small></div>`).join("");
}
function renderAgentRuns(runs){
  if(!runs.length)return `<div class="empty-state"><div class="empty-state-inner"><h2>Nenhuma run OMA persistida</h2><p>O Inspector de Agentes será montado a partir de events.jsonl e handoff.json reais.</p></div></div>`;
  return `<div class="run-list">${runs.map(r=>`<button class="run-row" data-open-run="${esc(r.key)}">
    <span class="status-dot ${stateClass(r.state)}"></span><span class="run-main"><b>${esc(r.title)}</b>
    <span>${esc(r.completed_tasks??"—")}/${esc(r.total_tasks??"—")} tarefas · ${esc(stateLabel(r.state))}</span></span><span class="run-time">${fmtTime(r.updated)}</span>
  </button>`).join("")}</div>`;
}
function renderLogs(logs){
  if(!logs.length)return `<div class="empty-state"><div class="empty-state-inner"><h2>Nenhum log de processo</h2><p>Arquivos reais em .sentra/logs aparecerão aqui.</p></div></div>`;
  return `<div class="run-list">${logs.map(log=>`<button class="run-row" data-log="${esc(log.name)}">
    <span class="status-dot"></span><span class="run-main"><b>${esc(log.name)}</b><span>${bytes(log.size)}</span></span><span class="run-time">${fmtTime(log.updated)}</span>
  </button>`).join("")}</div>`;
}
function bindCommonActions(){
  document.querySelectorAll("[data-open-run]").forEach(el=>el.addEventListener("click",()=>openRun(el.dataset.openRun)));
  document.querySelectorAll("[data-diff]").forEach(el=>el.addEventListener("click",()=>openDiff(el.dataset.diff)));
  document.querySelectorAll("[data-reveal]").forEach(el=>el.addEventListener("click",async()=>{await api("reveal_workspace",el.dataset.reveal);}));
  document.querySelectorAll("[data-control]").forEach(el=>el.addEventListener("click",async()=>{const r=await api("open_control_center");if(!r.ok)toast(r.error||"Falha ao abrir",true);}));
  document.querySelectorAll("[data-log]").forEach(el=>el.addEventListener("click",()=>openLog(el.dataset.log)));
}
function openDrawer(title,html){
  $("#drawer-title").textContent=title;
  $("#drawer-body").innerHTML=html;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden","false");
}
function closeDrawer(){
  $("#drawer").classList.remove("open");$("#drawer").setAttribute("aria-hidden","true");
}
function detailGrid(entries){
  return `<dl class="detail-grid">${entries.filter(x=>x[1]!==undefined&&x[1]!==null&&x[1]!=="").map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}
function patchHtml(text){
  if(!text)return `<div class="library-empty">Nenhum patch persistido para esta run.</div>`;
  return `<div class="code-scroll"><pre>${String(text).split("\n").map(line=>{
    const cls=line.startsWith("+")&&!line.startsWith("+++")?"add":line.startsWith("-")&&!line.startsWith("---")?"del":"";
    return `<span class="patch-line ${cls}">${esc(line)}\n</span>`;
  }).join("")}</pre></div>`;
}
async function openRun(key){
  try{
    const d=await api("run_detail",key);
    if(d.kind==="oma"){
      const metrics=d.metrics||{}, producers={};
      (d.events||[]).forEach(e=>{if(e.producer){producers[e.producer]=(producers[e.producer]||0)+1;}});
      const producerHtml=Object.entries(producers).map(([p,n])=>`<div class="log-item"><span><span class="status-dot ok" style="display:inline-block;margin-right:8px"></span>${esc(p)}</span><small>${n} eventos</small></div>`).join("");
      const timeline=(d.events||[]).slice(-80).reverse().map(e=>`<div class="timeline-item ${String(e.type||"").includes("FAILED")?"bad":"ok"}">
        <b>${esc(e.type||"evento")} · ${esc(e.producer||"runtime")}</b>
        <span>${e.task_id?`${esc(e.task_id)} · `:""}${esc(e.summary||"")}${e.timestamp?` · ${fmtTime(e.timestamp)}`:""}</span>
      </div>`).join("");
      openDrawer(d.id||"Run",`
        <section class="detail-section"><h3>Estado</h3>${detailGrid([
          ["Status",stateLabel(d.state)],["Workspace",d.workspace],["Tarefas",`${d.completed_tasks??"—"}/${d.total_tasks??"—"}`],
          ["Validações",metrics.validation_pass_rate!==undefined?`${Math.round(Number(metrics.validation_pass_rate)*100)}%`:""],
          ["Repairs",metrics.repair_rounds],["Duração",fmtDuration(metrics.elapsed_seconds)]
        ])}</section>
        <section class="detail-section"><h3>Agentes observados</h3>${producerHtml||'<div class="library-empty">Sem eventos de agentes.</div>'}</section>
        <section class="detail-section"><h3>Timeline real</h3><div class="timeline">${timeline||'<div class="library-empty">Sem eventos.</div>'}</div></section>
        <section class="detail-section"><h3>Patch persistido</h3>${patchHtml(d.patch_text||"")}</section>
      `);
      return;
    }
    if(d.kind==="task"){
      openDrawer(`Tarefa #${d.id}`,`<section class="detail-section"><h3>Estado</h3>${detailGrid([["Status",stateLabel(d.state)],["Workspace",d.workspace],["Código",d.result_code],["Erro",d.error]])}</section>
        <section class="detail-section"><h3>Log real</h3><div class="code-scroll"><pre>${esc(d.log||"Sem log.")}</pre></div></section>`);
      return;
    }
    openDrawer(d.title||d.id||"Run",`<section class="detail-section"><h3>Dados persistidos</h3><div class="code-scroll"><pre>${esc(JSON.stringify(d,null,2))}</pre></div></section>`);
  }catch(err){toast(String(err),true);}
}
async function openDiff(workspace){
  try{
    const d=await api("diff",workspace);
    openDrawer("Diff atual",`<section class="detail-section"><h3>${esc(shortPath(workspace))}</h3>
      ${d.files?.length?d.files.map(f=>`<div class="log-item"><span>${esc(f.path)}</span><small>+${esc(f.added)} −${esc(f.deleted)}</small></div>`).join(""):'<div class="library-empty">Working tree limpo.</div>'}
      </section><section class="detail-section"><h3>Patch</h3>${patchHtml(d.text||"")}</section>`);
  }catch(err){toast(String(err),true);}
}
async function openLog(name){
  try{
    const d=await api("read_log",name);
    openDrawer(d.name,`<section class="detail-section"><h3>Tail do arquivo real</h3><div class="code-scroll"><pre>${esc(d.text||"")}</pre></div></section>`);
  }catch(err){toast(String(err),true);}
}
function installEvents(){
  document.querySelectorAll(".nav-item[data-page]").forEach(el=>el.addEventListener("click",()=>{
    ui.page=el.dataset.page;ui.search="";$("#global-search").value="";updateChrome();render();
  }));
  $("#open-control").addEventListener("click",async()=>{const r=await api("open_control_center");if(!r.ok)toast(r.error||"Falha ao abrir",true);});
  $("#drawer-close").addEventListener("click",closeDrawer);
  $("#drawer-scrim").addEventListener("click",closeDrawer);
  $("#global-search").addEventListener("input",e=>{ui.search=e.target.value;render();});
  document.addEventListener("keydown",e=>{
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();$("#global-search").focus();}
    if(e.key==="Escape")closeDrawer();
  });
}
window.addEventListener("pywebviewready",async()=>{
  installEvents();
  await refresh(true);
  setInterval(()=>refresh(false),1800);
});
