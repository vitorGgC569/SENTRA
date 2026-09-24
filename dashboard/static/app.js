/* SENTRA Console: overview, runs, conversas, falhas, resumos, programa. Só GET. */
"use strict";
const $ = (id) => document.getElementById(id);
let view = "overview", cache = {}, docSel = { kind: "", name: "" };

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error("api " + r.status + " " + path);
  return r.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pill = (s) => `<span class="pill ${esc(s)}">${esc(s)}</span>`;
const link = (u) => u ? `<a href="${esc(u)}" target="_blank" rel="noopener">abrir ↗</a>` : "<span class='dim'>sem URL</span>";

async function tick() {
  $("clock").textContent = new Date().toLocaleTimeString();
  try {
    const ov = await api("/api/overview");
    const r = ov.relay || {};
    const w = (r.workers_online || []).length;
    $("relay").innerHTML = r.reachable
      ? `relay <b style="color:var(--ok)">●</b> ${r.completed || 0} ok / ${r.failed || 0} falha / ${w} workers`
      : `relay <b style="color:var(--bad)">● fora do ar</b>`;
    cache.ov = ov;
    const f = await api("/api/failures");
    cache.fail = f;
    const n = (f.counts?.seats || 0) + (f.counts?.jobs || 0) + (f.counts?.tasks || 0);
    const badge = $("failcnt");
    badge.hidden = n === 0; badge.textContent = n;
    try { cache.program = await api("/api/program"); } catch (e) {}
  } catch (e) { $("relay").textContent = "relay: erro"; }
  render();
}

function rows(list, fn) { return (list || []).map(fn).join(""); }

function render() {
  const m = $("main");
  if (view === "overview") return vOverview(m);
  if (view === "runs") return vRuns(m);
  if (view === "chats") return vChats(m);
  if (view === "webmodels") return vWebModels(m);
  if (view === "failures") return vFailures(m);
  if (view === "docs") return vDocs(m);
  if (view === "program") return vProgram(m);
}

async function vWebModels(m) {
  m.innerHTML = `<h2>Modelos Web</h2><div class="note">Consultando SENTRA Model Gateway…</div>`;
  try {
    const state = await api("/api/web-models");
    if (view !== "webmodels") return;
    const health = state.health || {};
    m.innerHTML = `<h2>Modelos Web</h2>
      <div class="cards">
        <div class="card"><b>${state.online ? "Online" : "Offline"}</b><small>Gateway / sidecar</small></div>
        <div class="card"><b>${esc(health.upstream?.version || "—")}</b><small>versão upstream</small></div>
        <div class="card"><b>${state.models.length}</b><small>modelos Web disponíveis</small></div>
      </div>
      <div class="note">A interface de login, navegador, limites e runtime é o launcher Electron do codex-chatgpt-web. O Gateway responde em ${esc(state.gateway)}.</div>
      <table><tr><th>Modelo SENTRA</th><th>Nome</th></tr>
      ${rows(state.models, (model) => `<tr><td>${esc(model.slug)}</td><td>${esc(model.name || "")}</td></tr>`)}
      </table>`;
  } catch (e) {
    if (view === "webmodels") m.innerHTML = `<h2>Modelos Web</h2><div class="note">Gateway indisponível: ${esc(e.message)}</div>`;
  }
}

function vOverview(m) {
  const ws = cache.ov?.workspaces || [];
  const runs = ws.flatMap((w) => w.runs || []);
  const by = (s) => runs.filter((r) => r.status === s).length;
  const projects = [...new Set(runs.map((r) => r.project || "?"))];
  m.innerHTML = `<h2>Visão geral</h2>
    <div class="cards">
      <div class="card"><b>${runs.length}</b><small>runs</small></div>
      <div class="card"><b>${projects.length}</b><small>projetos</small></div>
      <div class="card"><b>${by("FAILED")}</b><small>failed</small></div>
      <div class="card"><b>${by("CANDIDATE_READY") + by("APPLIED")}</b><small>prontas</small></div>
      <div class="card"><b>${(cache.fail?.counts?.seats || 0)}</b><small>chats quebrados</small></div>
    </div>
    <h3>Projetos</h3>
    <table><tr><th>Projeto</th><th>Runs</th><th>Failed</th><th></th></tr>
    ${rows(projects, (p) => { const pr = runs.filter((r) => r.project === p);
      return `<tr><td><b>${esc(p)}</b></td><td>${pr.length}</td>` +
        `<td>${pr.filter((r) => r.status === "FAILED").length}</td>` +
        `<td><button class="act" data-doc="p:${esc(p)}">resumo</button></td></tr>`; })}
    </table>`;
  m.querySelectorAll("[data-doc]").forEach((b) => b.onclick = () => {
    const [, name] = b.dataset.doc.split(/:(.+)/);
    docSel = { kind: "project", name }; view = "docs"; render(); loadDoc();
  });
}

function vRuns(m) {
  const runs = (cache.ov?.workspaces || []).flatMap((w) => w.runs || []);
  m.innerHTML = `<h2>Runs</h2>
    <table><tr><th>Run</th><th>Projeto</th><th>Status</th><th>Tarefas</th><th></th></tr>
    ${rows(runs, (r) => `<tr><td><b>${esc(r.run_id)}</b></td><td>${esc(r.project || "")}</td>` +
      `<td>${pill(r.status)}</td><td>${r.completed_tasks}/${r.total_tasks}</td>` +
      `<td><button class="act" data-doc="r:${esc(r.run_id)}">resumo</button> ` +
      `<button class="act" data-chats="${esc(r.run_id)}">chats</button></td></tr>`)}
    </table><div id="detail"></div>`;
  m.querySelectorAll("[data-doc]").forEach((b) => b.onclick = () => {
    const [, name] = b.dataset.doc.split(/:(.+)/);
    docSel = { kind: "run", name }; view = "docs"; render(); loadDoc();
  });
  m.querySelectorAll("[data-chats]").forEach((b) => b.onclick = async () => {
    const d = await api("/api/chats?run_id=" + encodeURIComponent(b.dataset.chats));
    $("detail").innerHTML = `<h3>Chats de ${esc(b.dataset.chats)}</h3>
      <table><tr><th>Assento</th><th>Estado</th><th>Chat</th></tr>
      ${rows(d.chats, (c) => `<tr><td>${esc(c.seat)}</td><td>${pill(c.state)}</td><td>${link(c.url)}</td></tr>`)}
      </table>`;
  });
}

async function vChats(m) {
  let list = [];
  try { list = (await api("/api/conversations")).conversations || []; } catch (e) {}
  const states = [...new Set(list.map((c) => c.state || "?"))].sort();
  m.innerHTML = `<h2>Conversas</h2>
    <div class="toolbar"><label>estado <select id="fstate"><option value="">todos</option>
    ${states.map((s) => `<option>${esc(s)}</option>`).join("")}</select></label>
    <small class="dim">${list.length} conversas em ${new Set(list.map((c) => c.run_id)).size} runs</small></div>
    <table id="ct"><tr><th>Run</th><th>Projeto</th><th>Assento</th><th>Estado</th><th>Chat</th></tr></table>`;
  const draw = (f) => { $("ct").innerHTML = `<tr><th>Run</th><th>Projeto</th><th>Assento</th><th>Estado</th><th>Chat</th></tr>` +
    rows(list.filter((c) => !f || (c.state || "") === f),
      (c) => `<tr><td>${esc(c.run_id)}</td><td>${esc(c.project || "")}</td><td>${esc(c.seat)}</td>` +
        `<td>${pill(c.state)}</td><td>${link(c.url)}</td></tr>`); };
  $("fstate").onchange = (e) => draw(e.target.value);
  draw("");
}

function vFailures(m) {
  const f = cache.fail || { seats: [], jobs: [], tasks: [] };
  m.innerHTML = `<h2>Falhas</h2>
    <div class="note">Quebrados = assentos NOT_SENT / UNCERTAIN / BLOCKED, entregas
    FAILED e tarefas FAILED. Diagnóstico local — reconciliar é no
    <span class="pill">main.py --reconcile</span> (sem replay automático).</div>
    <h3>Chats quebrados (${f.seats?.length || 0})</h3>
    <table><tr><th>Run</th><th>Projeto</th><th>Assento</th><th>Estado</th><th>Chat</th></tr>
    ${rows(f.seats, (c) => `<tr><td>${esc(c.run_id)}</td><td>${esc(c.project || "")}</td>` +
      `<td>${esc(c.seat)}</td><td>${pill(c.state)}</td><td>${link(c.url)}</td></tr>`)}
    </table>
    <h3>Entregas FAILED (${f.jobs?.length || 0})</h3>
    <table><tr><th>Job</th><th>Task</th><th>Worker</th><th>Erro</th></tr>
    ${rows((f.jobs || []).slice(0, 30), (j) => `<tr><td><small>${esc((j.job_id || "").slice(-8))}</small></td>` +
      `<td>${esc(j.task_id)}</td><td>${esc(j.worker)}</td><td><small>${esc(j.response_error || j.state)}</small></td></tr>`)}
    </table>
    <h3>Tarefas FAILED (${f.tasks?.length || 0})</h3>
    <table><tr><th>Run</th><th>Task</th><th>Repairs</th><th>Objetivo</th></tr>
    ${rows((f.tasks || []).slice(0, 50), (t) => `<tr><td>${esc(t.run_id)}</td><td>${esc(t.task_id)}</td>` +
      `<td>${t.repairs}</td><td><small>${esc(t.objective)}</small></td></tr>`)}
    </table>`;
}

function vProgram(m) {
  const p = cache.program;
  if (!p) {
    m.innerHTML = `<h2>Programa</h2><div class="note">carregando…</div>`;
    api("/api/program").then((d) => { cache.program = d; if (view === "program") render(); }).catch(() => {});
    return;
  }
  const by = p.by_status || {};
  const tasks = p.tasks || {};
  const fl = p.flakiness || {};
  const vel = p.velocity || [];
  const tax = p.failure_taxonomy || [];
  const pct = ((fl.flaky_fraction || 0) * 100).toFixed(1);
  const velTotal = vel.reduce((a, d) => a + (d.completed || 0), 0);
  m.innerHTML = `<h2>Programa</h2>
    <div class="note">Agregado local sobre todas as runs (somente leitura):
    velocidade por mtime em janelas de 24h nos ultimos 14 dias, taxonomia de
    falhas dos eventos e flakiness por repair rounds.</div>
    <div class="cards">
      <div class="card"><b>${p.runs_total ?? 0}</b><small>runs</small></div>
      <div class="card"><b>${tasks.completed ?? 0}/${tasks.total ?? 0}</b><small>tarefas concluidas</small></div>
      <div class="card"><b>${velTotal}</b><small>concluidas / 14 dias</small></div>
      <div class="card"><b>${pct}%</b><small>flakiness (${fl.repaired_tasks ?? 0}/${fl.total_tasks ?? 0})</small></div>
    </div>
    <h3>Runs por status (${p.runs_total ?? 0})</h3>
    <table><tr><th>Status</th><th>Runs</th></tr>
    ${rows(Object.entries(by), ([s, c]) => `<tr><td>${pill(s)}</td><td>${c}</td></tr>`)}
    </table>
    <h3>Velocidade — concluidas/dia (14 dias)</h3>
    <table><tr><th>Dia (UTC)</th><th>Concluidas</th></tr>
    ${rows(vel, (d) => `<tr><td>${esc(d.date)}</td><td>${d.completed}</td></tr>`)}
    </table>
    <h3>Taxonomia de falhas (top ${(tax || []).length})</h3>
    <table><tr><th>Motivo</th><th>Ocorrencias</th></tr>
    ${rows(tax, (t) => `<tr><td><small>${esc(t.reason)}</small></td><td>${t.count}</td></tr>`)}
    </table>`;
}

async function vDocs(m) {
  const runs = (cache.ov?.workspaces || []).flatMap((w) => w.runs || []);
  const projects = [...new Set(runs.map((r) => r.project || "?"))];
  m.innerHTML = `<h2>Resumos</h2>
    <div class="note">Documento de contexto gerado <b>localmente</b> a partir dos
    registros em disco (handoff, tarefas, chats, validações, eventos). Nada é
    enviado aos chats; é o contexto do operador, por projeto ou por run.</div>
    <div class="toolbar">
      <label>projeto <select id="dproj"><option value="">—</option>
      ${projects.map((p) => `<option${docSel.kind === "project" && docSel.name === p ? " selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
      <label>run <select id="drun"><option value="">—</option>
      ${runs.map((r) => `<option${docSel.kind === "run" && docSel.name === r.run_id ? " selected" : ""}>${esc(r.run_id)}</option>`).join("")}</select></label>
      <button class="act" id="dcopy">copiar</button>
      <button class="act" id="ddl">baixar .md</button>
    </div>
    <pre class="doc" id="doc">carregando…</pre>`;
  $("dproj").onchange = (e) => { docSel = { kind: "project", name: e.target.value }; $("drun").value = ""; loadDoc(); };
  $("drun").onchange = (e) => { docSel = { kind: "run", name: e.target.value }; $("dproj").value = ""; loadDoc(); };
  $("dcopy").onclick = () => navigator.clipboard?.writeText($("doc").textContent || "");
  $("ddl").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([$("doc").textContent || ""], { type: "text/markdown" }));
    a.download = (docSel.name || "resumo") + ".md"; a.click();
  };
  loadDoc();
}

async function loadDoc() {
  const box = $("doc");
  if (!box) return;
  try {
    if (docSel.kind === "project" && docSel.name) {
      const d = await api("/api/summary?project=" + encodeURIComponent(docSel.name));
      box.textContent = d.markdown;
    } else if (docSel.kind === "run" && docSel.name) {
      const d = await api("/api/summary?run_id=" + encodeURIComponent(docSel.name));
      box.textContent = d.markdown;
    } else box.textContent = "escolha um projeto ou uma run acima.";
  } catch (e) { box.textContent = "erro: " + e.message; }
}

document.querySelectorAll("nav button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("nav button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on"); view = b.dataset.v; render();
});
setInterval(tick, 15000);
tick();
