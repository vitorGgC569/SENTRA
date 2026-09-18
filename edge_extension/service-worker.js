/* service-worker.js (MV3) — coordena o pool de tabs REAIS próprias da extensão.
 * A fila principal vive no OMA (fonte de verdade); aqui há apenas atuadores.
 * Tabs do usuário NUNCA são adotadas: o pool cria tabs próprias (segundo plano)
 * e só opera nelas. Estados: IDLE -> BUSY(task) -> WAITING_RESPONSE -> IDLE. */
"use strict";

const OMA_RELAY = "http://127.0.0.1:8765";
const OMA_POOL = { minTabs: 2, maxTabs: 4 };
const OMA_POLL_MS = 2000;
const OMA_SW_VERSION = "1.6.1";
// Budgets MV3 (somente-leitura; a verdade está no servidor/Chrome):
// - native_bridge/job_store.py concede lease de 120s: renovar < 120s ou o relay
//   marca expirado e nenhum post tardio é aceito. Janela folgada de propósito
//   (suspensão MV3 ~30-60s); heartbeat 10s + fatias 25s + pings renovam sempre.
// - Chrome suspende o SW após ~30s sem eventos; setInterval NÃO impede e o
//   contexto (heartbeat, promises pendentes, mapa em memória) morre junto.
// Estratégia anti-morte-silenciosa, sem permissão nova:
//  a) WAIT fatiado em 25s (nenhuma pendência atravessa a janela de kill);
//  b) a tab (viva) pinga o SW a cada ~10s e cada ping renova o lease;
//  c) job ativo persistido em storage: restart do SW retoma sem reenviar;
//  d) alarme de 30s como backstop (pode ser clampado p/ 60s — não é o plano A).
const OMA_LEASE_MS = 30000;
const OMA_HB_MS = 10000;
const OMA_WAIT_SLICE_MS = 25000;
const OMA_HB_ALARM = "oma-hb";
const OMA_ACTIVE_PREFIX = "oma_active_";
const OMA_UPDATE_CHECK_MS = 30000;
let omaLastUpdateCheck = 0;
let omaTickBusy = false;

async function omaRelay(path, options = {}) {
  const { oma_relay_token } = await chrome.storage.local.get("oma_relay_token");
  if (!oma_relay_token) throw new Error("PAIRING_REQUIRED");
  const response = await fetch(OMA_RELAY + path, {
    ...options, headers: { "Content-Type": "application/json", ...options.headers,
      Authorization: `Bearer ${oma_relay_token}` },
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error(`RELAY_HTTP_${response.status}`);
  return response.json();
}

async function omaFlushOutbox() {
  const stored = await chrome.storage.local.get(null);
  for (const [id, payload] of Object.entries(stored).filter(([key]) => key.startsWith("oma_result_"))) {
    try {
      await omaRelay("/jobs/result", { method: "POST", body: JSON.stringify(payload) });
    } catch (error) {
      if (!String(error).includes("RELAY_HTTP_400")) continue;
      await omaNoteError("expired_result");
    }
    await chrome.storage.local.remove(id);
  }
}

async function omaCheckForUpdates() {
  // Auto-update sem ↻ manual: se o relay anuncia versão maior e nenhum worker
  // está ocupado, recarrega a extensão. Jobs na fila do relay sobrevivem
  // (relay é processo separado); tabs próprias são re-adotadas via storage.
  const now = Date.now();
  if (now - omaLastUpdateCheck < OMA_UPDATE_CHECK_MS) return;
  omaLastUpdateCheck = now;
  try {
    const busy = [...omaWorkers.values()].some((w) => w.state !== "IDLE");
    if (busy) return;
    const resp = await fetch(`${OMA_RELAY}/extension/version`);
    const data = await resp.json();
    if (data && data.version && data.version !== OMA_SW_VERSION) {
      console.log(`[OMA Bridge] auto-update ${OMA_SW_VERSION} -> ${data.version}`);
      chrome.runtime.reload();
    }
  } catch (_) {}
}

// tabId -> { state, job_id, task_id } — SOMENTE tabs criadas por este worker.
const omaWorkers = new Map();

// Tabs que falham submit repetidamente degradam (composer travado, overlay
// persistente): após 2 SUBMIT_FAILED seguidas a tab é fechada e o pool recria.
const omaSubmitFails = new Map();

async function omaRecycleTab(tabId) {
  try { await chrome.tabs.remove(tabId); } catch (_) {}
  omaWorkers.delete(tabId);
  omaSubmitFails.delete(tabId);
  await omaForgetOwned(tabId);
}

// Contador persistente de erros por local (catches nunca mais são invisíveis).
async function omaNoteError(where) {
  try {
    const stored = await chrome.storage.local.get({ oma_error_counts: {} });
    const counts = stored.oma_error_counts || {};
    counts[where] = (counts[where] || 0) + 1;
    await chrome.storage.local.set({ oma_error_counts: counts });
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    omaSwErrors = total;
  } catch (_) {}
}

let omaSwErrors = 0;
let omaLastCsVersion = "unknown";

async function omaOwnedTabIds() {
  const stored = await chrome.storage.local.get({ oma_owned_tabs: [] });
  return new Set(stored.oma_owned_tabs);
}

async function omaRememberOwned(tabId) {
  const ids = await omaOwnedTabIds();
  ids.add(tabId);
  await chrome.storage.local.set({ oma_owned_tabs: [...ids] });
}

async function omaForgetOwned(tabId) {
  const ids = await omaOwnedTabIds();
  ids.delete(tabId);
  await chrome.storage.local.set({ oma_owned_tabs: [...ids] });
  omaWorkers.delete(tabId);
}

function omaActiveKey(tabId) { return `${OMA_ACTIVE_PREFIX}${tabId}`; }

async function omaSaveActive(tabId, patch) {
  // Job em voo TEM que sobreviver a restart do SW (só memória = amnésia =
  // resultado órfão). NUNCA persiste prompt/imagens (quota do storage; o
  // resume jamais reenvia — só renova, espera e posta).
  try {
    const key = omaActiveKey(tabId);
    const stored = await chrome.storage.local.get({ [key]: null });
    const prev = stored[key] || {};
    await chrome.storage.local.set({ [key]: { ...prev, ...patch, tabId, updated: Date.now() } });
  } catch (_) {}
}

async function omaLoadActive(tabId) {
  try {
    const stored = await chrome.storage.local.get({ [omaActiveKey(tabId)]: null });
    return stored[omaActiveKey(tabId)];
  } catch (_) { return null; }
}

async function omaLoadAllActive() {
  try {
    const stored = await chrome.storage.local.get(null);
    return Object.entries(stored).filter(([k]) => k.startsWith(OMA_ACTIVE_PREFIX))
      .map(([k, v]) => [k.slice(OMA_ACTIVE_PREFIX.length), v]);
  } catch (_) { return []; }
}

async function omaClearActive(tabId) {
  try { await chrome.storage.local.remove(omaActiveKey(tabId)); } catch (_) {}
}

async function omaRenewIdentity(identity) {
  await omaRelay("/jobs/lease", { method: "POST", body: JSON.stringify(identity) });
}

// Fases de progresso (contrato native_bridge/job_store.py: ready, sending,
// sent, waiting, reading). Best-effort de propósito: relay antigo devolve 404
// e rede pode soluçar — telemetria nunca pode quebrar a entrega. O latch
// may_have_sent do servidor só é confiável com relay novo; sem ele, o
// comportamento volta ao anterior (sem requeue, expira honesto).
async function omaProgressPhase(tabId, identity, phase) {
  try {
    await omaRelay("/jobs/progress", { method: "POST", body: JSON.stringify({
      job_id: identity.job_id, worker: identity.worker,
      lease_token: identity.lease_token, phase,
    }) });
    return true;
  } catch (_) {
    return false;
  }
}

// Renova o lease de um job persistido. Quem chama é sempre um EVENTO Chrome
// (alarme, ping da tab, fatia de espera) — eventos acordam SW suspenso, que é
// exatamente o que o setInterval morto não fazia.
async function omaRenewActive(tabId) {
  const active = await omaLoadActive(tabId);
  if (!active || !active.job_id || !active.lease_token) return false;
  await omaRenewIdentity({ job_id: active.job_id, worker: active.worker, lease_token: active.lease_token });
  active.hb_sw = (active.hb_sw || 0) + 1;
  active.updated = Date.now();
  try { await chrome.storage.local.set({ [omaActiveKey(tabId)]: active }); } catch (_) {}
  return true;
}

// Backstop do alarme: renova tudo em voo. NÃO substitui os pings da tab
// (alarme pode ser clampado para 60s > lease de 30s); só encurta a janela.
async function omaRenewAllActive() {
  const all = await omaLoadAllActive();
  for (const [suffix, active] of all) {
    const tabId = Number(suffix);
    if (!Number.isFinite(tabId) || !active) continue;
    try {
      await omaRenewActive(tabId);
    } catch (e) {
      await omaNoteError("renew_active");
      if (String((e && e.message) || e).includes("RELAY_HTTP_400")) {
        // Servidor declarou o lease morto: geração órfã nunca postará.
        // Para (economiza quota/compute) e para de rastrear.
        try { await omaSendToTab(tabId, { operation: "STOP_GENERATION" }); } catch (_) {}
        await omaClearActive(tabId);
      }
      // Erro de rede/transiente: mantém o active; a próxima tentativa cura.
    }
  }
}

// Post durável: resultado primeiro no storage (outbox), depois flush. Se o SW
// morrer entre os dois, o próximo tick re-flusha — nunca perde post pronto.
// Preserva a identidade do worker que obteve o lease (TAB-xxx) para garantir
// que o job_store valide o post com sucesso.
async function omaPostResult(identity, jobRef, payload) {
  const workerIdentity = identity.worker || payload.worker;
  const merged = { ...payload, ...identity, worker: workerIdentity };
  await chrome.storage.local.set({ [`oma_result_${jobRef.job_id}`]: merged });
  await omaFlushOutbox();
}

chrome.tabs.onRemoved.addListener((tabId) => { omaForgetOwned(tabId); });

async function omaEnsureTabs() {
  const owned = await omaOwnedTabIds();
  // Revalida: tabs fechadas fora do onRemoved saem do mapa.
  for (const tabId of [...omaWorkers.keys()]) {
    try { await chrome.tabs.get(tabId); }
    catch (_) { omaWorkers.delete(tabId); await omaForgetOwned(tabId); }
  }
  let count = 0;
  for (const tabId of owned) {
    try { await chrome.tabs.get(tabId); count++; }
    catch (_) { await omaForgetOwned(tabId); }
  }
  while (omaWorkers.size < OMA_POOL.minTabs && count < OMA_POOL.maxTabs) {
    const t = await chrome.tabs.create({ url: "https://chatgpt.com/", active: false });
    await omaRememberOwned(t.id);
    omaWorkers.set(t.id, { state: "IDLE" });
    count++;
  }
  // Registra owned que ainda não estão no mapa em memória (reinício do worker).
  for (const tabId of await omaOwnedTabIds()) {
    if (!omaWorkers.has(tabId)) {
      try { await chrome.tabs.get(tabId); omaWorkers.set(tabId, { state: "IDLE" }); }
      catch (_) { await omaForgetOwned(tabId); }
    }
  }
}

async function omaSendToTab(tabId, message) {
  try {
    const reply = await chrome.tabs.sendMessage(tabId, message);
    if (!reply || reply.ok !== true) {
      throw new Error((reply && reply.error) || "content-script returned no result");
    }
    return reply;
  } catch (e) {
    throw new Error(`TAB_ERROR tab=${tabId}: ${e.message}`);
  }
}

async function omaWaitTabComplete(tabId, timeoutMs = 60000) {
  // Estado via API (não sleep): só fala com o content-script após carga completa,
  // eliminando a race onde a página antiga responde e o unload mata o canal.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === "complete" && tab.url && tab.url.startsWith("https://chatgpt.com/")) {
        return;
      }
    } catch (e) {
      throw new Error(`TAB_ERROR tab=${tabId}: tab sumiu durante navegação`);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`TAB_ERROR tab=${tabId}: navegação não completou`);
}

async function omaWaitSettled(tabId, timeoutMs = 60000) {
  // Espera geração anterior terminar + 2s de acomodação antes de enviar.
  const start = Date.now();
  let calmSince = 0;
  while (Date.now() - start < timeoutMs) {
    try {
      const ans = await chrome.tabs.sendMessage(tabId, { operation: "GET_STATUS" });
      const fin = ans && ans.result ? ans.result.finished !== false : true;
      if (fin) {
        if (!calmSince) calmSince = Date.now();
        if (Date.now() - calmSince > 2000) return;
      } else {
        calmSince = 0;
      }
    } catch (_) { calmSince = 0; }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`TAB_ERROR tab=${tabId}: conversa não estabilizou (geração presa?)`);
}

async function omaWaitTabDeparted(tabId, timeoutMs = 15000) {
  // Após update/reload, o status ainda mostra o estado PRÉ-navegação por um
  // instante; ler "complete" aí valida a página velha. Espera sair primeiro.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status !== "complete") return;
    } catch (e) {
      throw new Error(`TAB_ERROR tab=${tabId}: tab sumiu durante navegação`);
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  // SPA pode trocar de rota sem reload (status nunca sai de complete):
  // não é erro, o caller valida frescura pelo script em seguida.
}

async function omaEnsureFreshScript(tabId) {
  // Soft-navigations SPA preservam content-scripts obsoletos indefinidamente.
  // Arquivos íntegros têm cs_version == manifest.version (teste trava isso);
  // divergência = script obsoleto -> reload real (reinjeção garantida).
  const manifestVersion = chrome.runtime.getManifest().version;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const ans = await chrome.tabs.sendMessage(tabId, { operation: "GET_STATUS" });
      const csv = ans && ans.result ? ans.result.cs_version : null;
      if (csv && csv === manifestVersion) return;
    } catch (_) {}
    await chrome.tabs.reload(tabId);
    await omaWaitTabDeparted(tabId);
    await omaWaitTabComplete(tabId);
    await omaWaitTabReady(tabId);
  }
  throw new Error(`TAB_STALE: content-script obsoleto persistente na tab ${tabId}`);
}

async function omaWaitTabReady(tabId, timeoutMs = 45000) {
  // Aguarda o content-script responder (pós-navegação) em vez de sleep fixo.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const ans = await chrome.tabs.sendMessage(tabId, { operation: "GET_STATUS" });
      const inner = (ans && ans.result) || ans || {};
      omaLastCsVersion = inner.cs_version || "unknown";
      return;
    } catch (_) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  throw new Error(`TAB_ERROR tab=${tabId}: content-script não respondeu (login exigido? DOM alterado?)`);
}

async function omaProcessJob(tabId, job) {
  const worker = omaWorkers.get(tabId);
  if (!worker) return;
  worker.state = "BUSY";
  worker.job_id = job.job_id;
  worker.task_id = job.task_id;
  const identity = { job_id: job.job_id, worker: `TAB-${tabId}`, lease_token: job.lease_token };
  // Telemetria de vida (vai no resultado): hb_sw = renovações do SW,
  // slices = fatias de WAIT, cshb = pings da tab, rec = 1 se houve resume.
  // Vão DENTRO da string worker: o relay rejeita campos desconhecidos (400).
  let hbSw = 0;
  let slices = 0;
  let csHb = 0;
  // Persiste ANTES de qualquer efeito no browser: restart no meio do caminho
  // recupera pelo storage em vez de órfão. Sem prompt/imagens (ver omaSaveActive).
  await omaSaveActive(tabId, {
    job_id: job.job_id, task_id: job.task_id, worker: identity.worker,
    lease_token: job.lease_token, kind: job.kind || "CHAT_TASK",
    timeout_s: job.timeout_s || 180, new_chat: !!job.new_chat,
    conversation_url: job.conversation_url || null,
    deadlineMs: Date.now() + (job.timeout_s || 180) * 1000,
    last_conv: worker.last_conv || null,
    sent: false, hb_sw: 0, slices: 0, images_attached: 0,
  });
  const renew = async () => {
    await omaRenewIdentity(identity);
    hbSw++;
    await omaSaveActive(tabId, { hb_sw: hbSw });
  };
  let leaseLost = false;
  const heartbeat = setInterval(() => renew().catch(async (e) => {
    // Só 400 (servidor rejeitou o lease) prova perda. Blip de rede cura no
    // próximo ciclo: o lease tem 30s de folga e o heartbeat roda a cada 10s.
    // (Antes: QUALQUER erro abortava uma geração saudável.)
    if (!String((e && e.message) || e).includes("RELAY_HTTP_400")) return;
    leaseLost = true;
    try { await omaSendToTab(tabId, { operation: "STOP_GENERATION" }); } catch (_) {}
  }), OMA_HB_MS);
  const postResult = async (payload) => omaPostResult(identity, job, payload);
  // Read-only probe: do not reload or discard an uncertain submission/draft.
  if (job.kind === "STATUS_PROBE") {
    try {
      await renew();
      await omaWaitTabReady(tabId, 20000);
      const st = await omaSendToTab(tabId, { operation: "GET_STATUS" });
      const r = (st && st.result) || {};
      await postResult({
        job_id: job.job_id, task_id: job.task_id, status: "COMPLETED",
        result: JSON.stringify({ send_available: !!r.send_available,
          cap_banner: r.cap_banner || null, url: r.url || null,
          finished: r.finished !== false,
          composer_found: r.composer_found, diagnostics: r.diagnostics || null,
          sw_version: OMA_SW_VERSION, cs_version: r.cs_version || "unknown",
          worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION}` }),
        worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} hb=${hbSw} rec=0`,
      });
    } catch (e) {
      await postResult({ job_id: job.job_id, task_id: job.task_id, status: "FAILED",
        error: `[sw=${OMA_SW_VERSION} hb=${hbSw} rec=0] probe: ` + String((e && e.message) || e) });
    } finally {
      clearInterval(heartbeat);
      await omaClearActive(tabId);
      if (omaWorkers.has(tabId)) omaWorkers.set(tabId, { state: "IDLE" });
    }
    return;
  }
  if (job.kind === "DELETE_CHAT") {
    try {
      await renew();
      await omaWaitTabReady(tabId, 20000);
      let convId = null;
      if (job.conversation_url) {
        const m = job.conversation_url.match(/\/c\/([A-Za-z0-9-]{1,128})/);
        if (m) convId = m[1];
      }
      if (!convId && job.prompt) {
        const m = job.prompt.match(/[A-Za-z0-9-]{1,128}/);
        if (m) convId = m[0];
      }
      if (!convId) throw new Error("DELETE_CHAT: conversation_id not found in url or prompt");

      const del = await omaSendToTab(tabId, { operation: "DELETE_CONVERSATION", conversation_id: convId });
      const delResult = (del && del.result) || {};
      try {
        const tabInfo = await chrome.tabs.get(tabId);
        if (tabInfo && tabInfo.url && tabInfo.url.includes(convId)) {
          await chrome.tabs.update(tabId, { url: "https://chatgpt.com/" });
        }
      } catch (_) {}

      await postResult({
        job_id: job.job_id, task_id: job.task_id, status: "COMPLETED",
        result: JSON.stringify({ deleted: !!delResult.deleted, conversation_id: convId, details: delResult.details }),
        worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} hb=${hbSw} rec=0`,
      });
    } catch (e) {
      await postResult({
        job_id: job.job_id, task_id: job.task_id, status: "FAILED",
        error: `[sw=${OMA_SW_VERSION} hb=${hbSw} rec=0] delete: ` + String((e && e.message) || e),
      });
    } finally {
      clearInterval(heartbeat);
      await omaClearActive(tabId);
      if (omaWorkers.has(tabId)) omaWorkers.set(tabId, { state: "IDLE" });
    }
    return;
  }
  try {
    await renew(); // ACK delivery before any browser side effect.
    if (job.new_chat) {
      // Navegação é feita pelo worker (chrome.tabs): navegar via content-script
      // mataria o canal de mensagem antes da resposta.
      // SPA pode trocar de rota sem reload: EXIGE conversa zerada, com reload
      // forçado como fallback. Prompt em conversa obsoleta = contaminação.
      let fresh = false;
      for (let attempt = 0; attempt < 3 && !fresh; attempt++) {
        if (attempt === 0) {
          await chrome.tabs.update(tabId, { url: "https://chatgpt.com/" });
        } else {
          await chrome.tabs.reload(tabId); // reload real: nova injeção garantida
        }
      await omaWaitTabDeparted(tabId);
      await omaWaitTabComplete(tabId);
      await omaWaitTabReady(tabId);
      await omaEnsureFreshScript(tabId);
      try {
        const st = await omaSendToTab(tabId, { operation: "GET_STATUS" });
        fresh = !!(st.result && st.result.is_fresh_chat);
      } catch (_) { fresh = false; }
      }
      if (!fresh) {
        throw new Error("STALE_CONVERSATION: sem chat zerado após 3 tentativas; "
          + "job abortado para não contaminar");
      }
    } else {
      if (!/^https:\/\/chatgpt\.com\/c\/[A-Za-z0-9-]{1,128}(\/|\?.*)?$/.test(job.conversation_url || "")) {
        throw new Error("CONVERSATION_MISMATCH: continuação exige URL explícita");
      }
      const targetConvIdMatch = (job.conversation_url || "").match(/\/c\/([A-Za-z0-9-]{1,128})/);
      const targetConvId = targetConvIdMatch ? targetConvIdMatch[1] : null;
      let alreadyOnConv = false;
      try {
        const currentTab = await chrome.tabs.get(tabId);
        const currentConvIdMatch = (currentTab && currentTab.url && currentTab.url.match(/\/c\/([A-Za-z0-9-]{1,128})/));
        const currentConvId = currentConvIdMatch ? currentConvIdMatch[1] : null;
        if (targetConvId && currentConvId && targetConvId === currentConvId) {
          alreadyOnConv = true;
        }
      } catch (_) {}

      if (!alreadyOnConv) {
        await chrome.tabs.update(tabId, { url: job.conversation_url });
        await omaWaitTabDeparted(tabId);
        await omaWaitTabComplete(tabId);
        await omaWaitTabReady(tabId);
        await omaEnsureFreshScript(tabId);
      }
      // Conversa existente pode estar hidratando/streamando: só envia com a
      // página estabilizada (sem geração em curso), senão cliques são engolidos.
      await omaWaitSettled(tabId);
      const actual = await omaSendToTab(tabId, { operation: "GET_CONVERSATION_URL" });
      const actualConvId = (actual && actual.result && (actual.result.conversation_id || ((actual.result.url || "").match(/\/c\/([A-Za-z0-9-]{1,128})/) || [])[1])) || null;
      const urlMatches = actual && actual.result && actual.result.url && (
        (targetConvId && actualConvId && targetConvId === actualConvId) ||
        actual.result.url.split("?")[0].replace(/\/$/, "") === job.conversation_url.split("?")[0].replace(/\/$/, "")
      );
      if (!actual.ok || !actual.result || !urlMatches) {
        throw new Error("CONVERSATION_MISMATCH: tab não abriu a conversa solicitante");
      }
    }
    if (leaseLost) throw new Error("LEASE_LOST");
    await renew();
    await omaProgressPhase(tabId, identity, "ready");
    await omaProgressPhase(tabId, identity, "sending");
    // A channel/submit error is not proof that nothing was sent. Never replay.
    const sent = await omaSendToTab(tabId, {
      operation: "SEND_MESSAGE", text: job.prompt, images: job.images || [],
    });
    const attached = (sent && sent.result && sent.result.images_attached) || 0;
    // Envio confirmado: a partir daqui o resume pode esperar+postar sem reenviar.
    await omaSaveActive(tabId, { sent: true, images_attached: attached });
    await omaProgressPhase(tabId, identity, "sent");
    worker.state = "WAITING_RESPONSE";
    // WAIT FATIADO (o coração do fix): nenhuma pendência SW<->tab atravessa a
    // janela de suspensão do SW (~30s) nem o lease (30s). Cada fatia renova o
    // lease antes de esperar; TIMEOUT de fatia com geração em curso = continuar,
    // não falhar. A tab preserva omaPendingResponseBaseline entre fatias, então
    // re-entrar no WAIT nunca confunde o turno anterior com o atual. Se a
    // resposta já estiver pronta no DOM (caso do sintoma), a primeira fatia
    // resolve em ~2-3s (3 amostras estáveis).
    const waitDeadline = Date.now() + (job.timeout_s || 180) * 1000;
    let waited = null;
    for (;;) {
      const remaining = waitDeadline - Date.now();
      if (remaining <= 0) {
        throw new Error("TIMEOUT waiting stable response (WAIT fatiado esgotou o timeout do job)");
      }
      if (leaseLost) throw new Error("LEASE_LOST");
      try {
        await renew();
      } catch (e) {
        if (String((e && e.message) || e).includes("RELAY_HTTP_400")) throw new Error("LEASE_LOST");
      }
      const slice = Math.min(OMA_WAIT_SLICE_MS, remaining);
      slices++;
      if (slices % 3 === 1) await omaProgressPhase(tabId, identity, "waiting");
      try {
        waited = await omaSendToTab(tabId, { operation: "WAIT_RESPONSE", timeout_ms: slice });
        const hb = waited && waited.result && waited.result.hb_cs;
        if (typeof hb === "number" && Number.isFinite(hb)) csHb += hb;
        break;
      } catch (e) {
        const msg = String((e && e.message) || e);
        const m = msg.match(/csping=(\d+)/);
        if (m) { try { csHb += parseInt(m[1], 10); } catch (_) {} }
        if (/TIMEOUT/.test(msg) && Date.now() < waitDeadline) {
          await omaSaveActive(tabId, { slices });
          continue;
        }
        throw e;
      }
    }
    await omaSaveActive(tabId, { slices });
    await omaProgressPhase(tabId, identity, "reading");
    const conv = await omaSendToTab(tabId, { operation: "GET_CONVERSATION_URL" });
    const convId = conv.result ? conv.result.conversation_id : null;
    // Guarda anti-contaminação: com new_chat, o ID da conversa TEM que mudar.
    if (job.new_chat && worker.last_conv && convId && convId === worker.last_conv) {
      throw new Error("STALE_CONVERSATION: conversa não mudou após new_chat "
        + `(id repetido ${convId}); prompt pode ter caído no chat anterior`);
    }
    if (convId) worker.last_conv = convId;
    await postResult({
      job_id: job.job_id, task_id: job.task_id, status: "COMPLETED",
      result: waited.result ? waited.result.text : "",
      conversation_url: conv.result ? conv.result.url : null,
      conversation_id: conv.result ? conv.result.conversation_id : null,
      images_attached: attached,
      worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} cs=${omaLastCsVersion} err=${omaSwErrors} hb=${hbSw} slices=${slices} cshb=${csHb} rec=0`,
    });
  } catch (e) {
    await omaNoteError("process_job");
    const msg = String((e && e.message) || e);
    if (/SUBMIT_FAILED|TAB_STALE/.test(msg)) {
      const n = (omaSubmitFails.get(tabId) || 0) + 1;
      omaSubmitFails.set(tabId, n);
      if (n >= 2) {
        await omaRecycleTab(tabId); // tab degradada: fecha, pool recria zerada
      }
    } else {
      omaSubmitFails.delete(tabId);
    }
    await postResult({
      job_id: job.job_id, task_id: job.task_id, status: "FAILED",
      error: `[sw=${OMA_SW_VERSION} hb=${hbSw} slices=${slices} rec=0] ` + msg,
    });
  } finally {
    clearInterval(heartbeat);
    await omaClearActive(tabId);
    if (omaWorkers.has(tabId)) {
      // Preserva last_conv entre jobs (guarda anti-contaminação); limpa o resto.
      omaWorkers.set(tabId, { state: "IDLE", last_conv: omaWorkers.get(tabId).last_conv });
    }
  }
}

const omaResumeBusy = new Set();

// Retoma job órfão de restart do SW: a tab está viva (a resposta pode já estar
// no DOM) mas o contexto que renovava/postava morreu com o SW antigo. NUNCA
// reenvia: só renova, espera fatiado (o baseline da tab continua intacto) e
// posta. Respeita o deadline original — resume não estende o timeout do job.
async function omaResumeJob(tabId, active) {
  if (!omaWorkers.has(tabId)) omaWorkers.set(tabId, { state: "IDLE" });
  const worker = omaWorkers.get(tabId);
  if (!worker || worker.state !== "IDLE") return;
  worker.state = "WAITING_RESPONSE";
  worker.job_id = active.job_id;
  worker.task_id = active.task_id;
  const identity = { job_id: active.job_id, worker: active.worker, lease_token: active.lease_token };
  let hbSw = active.hb_sw || 0;
  let slices = active.slices || 0;
  let csHb = 0;
  const deadline = active.deadlineMs || (Date.now() + 60000);
  try {
    try {
      await omaRenewIdentity(identity);
      hbSw++;
    } catch (e) {
      if (!String((e && e.message) || e).includes("RELAY_HTTP_400")) {
        // Blip de rede no primeiro renew: segue para o loop fatiado, que
        // renova a cada fatia (e detecta LEASE_LOST real lá).
      } else {
        // Lease já expirou no servidor (DELIVERY_EXPIRED registrado lá):
        // nenhum post salvaria; para a geração órfã e desiste sem ruído.
        try { await omaSendToTab(tabId, { operation: "STOP_GENERATION" }); } catch (_) {}
        return;
      }
    }
    let waited = null;
    for (;;) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        throw new Error("TIMEOUT waiting stable response (resume esgotou o timeout do job)");
      }
      try {
        await omaRenewIdentity(identity);
        hbSw++;
      } catch (e) {
        if (String((e && e.message) || e).includes("RELAY_HTTP_400")) throw new Error("LEASE_LOST");
      }
      const slice = Math.min(OMA_WAIT_SLICE_MS, remaining);
      slices++;
      if (slices % 3 === 1) await omaProgressPhase(tabId, identity, "waiting");
      try {
        waited = await omaSendToTab(tabId, { operation: "WAIT_RESPONSE", timeout_ms: slice });
        const hb = waited && waited.result && waited.result.hb_cs;
        if (typeof hb === "number" && Number.isFinite(hb)) csHb += hb;
        break;
      } catch (e) {
        const msg = String((e && e.message) || e);
        const m = msg.match(/csping=(\d+)/);
        if (m) { try { csHb += parseInt(m[1], 10); } catch (_) {} }
        if (/TIMEOUT/.test(msg) && Date.now() < deadline) continue;
        throw e;
      }
    }
    const conv = await omaSendToTab(tabId, { operation: "GET_CONVERSATION_URL" });
    const convId = conv.result ? conv.result.conversation_id : null;
    // Guarda anti-contaminação do caminho normal, com o last_conv de ANTES do
    // job (persistido — o em memória morreu com o SW antigo).
    if (active.new_chat && active.last_conv && convId && convId === active.last_conv) {
      throw new Error("STALE_CONVERSATION: conversa não mudou após new_chat "
        + `(id repetido ${convId}); prompt pode ter caído no chat anterior`);
    }
    if (convId) {
      const mem = omaWorkers.get(tabId);
      if (mem) mem.last_conv = convId;
    }
    await omaPostResult(identity, active, {
      job_id: active.job_id, task_id: active.task_id, status: "COMPLETED",
      result: waited.result ? waited.result.text : "",
      conversation_url: conv.result ? conv.result.url : null,
      conversation_id: conv.result ? conv.result.conversation_id : null,
      images_attached: active.images_attached || 0,
      worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} cs=${omaLastCsVersion} err=${omaSwErrors} hb=${hbSw} slices=${slices} cshb=${csHb} rec=1`,
    });
  } catch (e) {
    await omaNoteError("resume_job");
    const msg = String((e && e.message) || e);
    // Se o lease já expirou no servidor, este post é descartado pelo relay
    // (400) e some no flush — correto: o servidor já registrou DELIVERY_EXPIRED.
    await omaPostResult(identity, active, {
      job_id: active.job_id, task_id: active.task_id, status: "FAILED",
      error: `[sw=${OMA_SW_VERSION} rec=1 hb=${hbSw} slices=${slices}] ` + msg,
    });
  } finally {
    await omaClearActive(tabId);
    if (omaWorkers.has(tabId)) {
      omaWorkers.set(tabId, { state: "IDLE", last_conv: (omaWorkers.get(tabId) || {}).last_conv });
    }
  }
}

// Varre jobs persistidos sem dono em memória (SW reiniciou no meio do voo).
// Só retoma CHAT_TASK já enviado. Não-enviado expira honestamente no servidor
// (reenviar envio incerto = risco de duplicar geração) e probe é barato de
// repetir via novo poll — ambos sem reanimação incerta aqui.
async function omaRecoverActive() {
  let all;
  try { all = await omaLoadAllActive(); } catch (_) { return; }
  for (const [suffix, active] of all) {
    try {
      const tabId = Number(suffix);
      if (!Number.isFinite(tabId) || !active || !active.job_id) {
        try { await chrome.storage.local.remove(OMA_ACTIVE_PREFIX + suffix); } catch (_) {}
        continue;
      }
      const mem = omaWorkers.get(tabId);
      if (mem && mem.state !== "IDLE") continue; // loop vivo é o dono
      if (omaResumeBusy.has(tabId)) continue;
      try {
        await chrome.tabs.get(tabId);
      } catch (_) {
        await omaClearActive(tabId); // tab sumiu: para de rastrear, servidor expira
        continue;
      }
      if (!active.sent || (active.kind && active.kind !== "CHAT_TASK")) continue;
      omaResumeBusy.add(tabId);
      // Sem await (paralelo como o poll); a trava + WAITING síncrono evitam
      // que o poll lease outro job para esta tab no mesmo tick.
      omaResumeJob(tabId, active)
        .catch(() => {})
        .finally(() => { omaResumeBusy.delete(tabId); });
    } catch (_) {}
  }
}

async function omaTick() {
  if (omaTickBusy) return;
  omaTickBusy = true;
  try {
    const settings = await chrome.storage.local.get({ oma_enabled: false, oma_relay_token: "" });
    if (!settings.oma_enabled || !settings.oma_relay_token) return;
    await omaFlushOutbox();
    await omaCheckForUpdates();
    await omaEnsureTabs();
    await omaRecoverActive(); // órfãos de restart antes de leasear trabalho novo
    for (const [tabId, worker] of omaWorkers) {
      if (worker.state !== "IDLE") continue;
      const busy = [...omaWorkers.values()].filter((w) => w.state !== "IDLE").length;
      if (busy >= OMA_POOL.maxTabs) break;
      let data = null;
      try {
        data = await omaRelay(`/jobs/poll?worker=TAB-${tabId}`);
      } catch (_) { return; } // relay offline: tenta de novo no próximo tick
      if (data && data.job) {
        omaProcessJob(tabId, data.job); // sem await: workers em paralelo
      }
    }
  } catch (_) {
    omaNoteError("tick");
  } finally {
    omaTickBusy = false;
  }
}

console.log(`[OMA Bridge] service worker ${OMA_SW_VERSION} ativo`);

async function omaStartupCleanup() {
  // Tabs próprias de gerações passadas (runs mortos, aborts) ficam órfãs e
  // cada SPA do ChatGPT consome centenas de MB — tabs novas hidratam mal.
  // Fecha TODAS as owned e recomeça do zero (nunca toca tabs do usuário).
  try {
    const stored = await chrome.storage.local.get({ oma_owned_tabs: [] });
    for (const tabId of stored.oma_owned_tabs || []) {
      try { await chrome.tabs.remove(tabId); } catch (_) {}
    }
    await chrome.storage.local.set({ oma_owned_tabs: [] });
  } catch (_) {}
  try { omaWorkers.clear(); } catch (_) {}
  try {
    // Tabs mortas = gerações mortas: actives pendentes virariam renovações
    // eternas de lease já expirado. Outbox (oma_result_*) é preservada — é
    // trabalho PRONTO que o próximo tick flusha.
    const stored = await chrome.storage.local.get(null);
    const actives = Object.keys(stored || {}).filter((k) => k.startsWith(OMA_ACTIVE_PREFIX));
    if (actives.length) await chrome.storage.local.remove(actives);
  } catch (_) {}
  try { omaResumeBusy.clear(); } catch (_) {}
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ oma_state: "PAIR_IN_OPTIONS" });
  chrome.alarms.create("oma-poll", { periodInMinutes: 1 });
  try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 0.5 }); }
  catch (_) { try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 1 }); } catch (_) {} }
});
chrome.runtime.onStartup.addListener(async () => {
  await omaStartupCleanup();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  // Retornar a promise estende a vida do SW até o trabalho assentar.
  if (alarm.name === "oma-poll") return omaTick();
  if (alarm.name === OMA_HB_ALARM) return omaRenewAllActive().catch(() => {});
  return undefined;
});
// Alarmes sobrevivem ao restart do SW, mas recriar no topo (idempotente)
// cobre update/reload que limpe a agenda sem disparar onInstalled.
try { chrome.alarms.create("oma-poll", { periodInMinutes: 1 }); } catch (_) {}
try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 0.5 }); }
catch (_) { try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 1 }); } catch (_) {} }

// Acordado pela tab: OMA_LEASE_PING (a cada ~10s durante o WAIT) renova o
// lease na hora; OMA_RESULT_READY (resposta estabilizou) dispara o recover.
// Mensagem de content-script ACORDA SW suspenso — é o canal que atravessa o
// kill de ~30s. Não conflita com omaSendToTab (tabs.sendMessage usa o canal
// de resposta, não este listener).
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (!request || (request.operation !== "OMA_LEASE_PING" && request.operation !== "OMA_RESULT_READY")) return false;
  const tabId = sender && sender.tab && sender.tab.id;
  (async () => {
    if (request.operation === "OMA_LEASE_PING" && typeof tabId === "number") {
      try { await omaRenewActive(tabId); } catch (_) {}
      return { ok: true };
    }
    try { await omaRecoverActive(); } catch (_) {}
    return { ok: true };
  })()
    .then((r) => { try { sendResponse(r); } catch (_) {} })
    .catch((e) => { try { sendResponse({ ok: false, error: String((e && e.message) || e) }); } catch (_) {} });
  return true;
});
setInterval(omaTick, OMA_POLL_MS);

