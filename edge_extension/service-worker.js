/* service-worker.js (MV3) — coordena o pool de tabs REAIS próprias da extensão.
 * A fila principal vive no OMA (fonte de verdade); aqui há apenas atuadores.
 * Tabs do usuário NUNCA são adotadas: o pool cria tabs próprias (segundo plano)
 * e só opera nelas. Estados: IDLE -> BUSY(task) -> WAITING_RESPONSE -> IDLE. */
"use strict";

const OMA_RELAY = "http://127.0.0.1:8765";
const OMA_POOL = { minTabs: 2, maxTabs: 4 };
const OMA_POLL_MS = 2000;
const OMA_SW_VERSION = "1.4.0";
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
  const renew = () => omaRelay("/jobs/lease", { method: "POST", body: JSON.stringify(identity) });
  let leaseLost = false;
  const heartbeat = setInterval(() => renew().catch(async () => {
    leaseLost = true;
    try { await omaSendToTab(tabId, { operation: "STOP_GENERATION" }); } catch (_) {}
  }), 10000);
  const postResult = async (payload) => {
    await chrome.storage.local.set({ [`oma_result_${job.job_id}`]: { ...payload, ...identity } });
    await omaFlushOutbox();
  };
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
        worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION}`,
      });
    } catch (e) {
      await postResult({ job_id: job.job_id, task_id: job.task_id, status: "FAILED",
        error: `[sw=${OMA_SW_VERSION}] probe: ` + String((e && e.message) || e) });
    } finally {
      clearInterval(heartbeat);
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
      if (!/^https:\/\/chatgpt\.com\/c\/[A-Za-z0-9-]{1,128}$/.test(job.conversation_url || "")) {
        throw new Error("CONVERSATION_MISMATCH: continuação exige URL explícita");
      }
      await chrome.tabs.update(tabId, { url: job.conversation_url });
      await omaWaitTabDeparted(tabId);
      await omaWaitTabComplete(tabId);
      await omaWaitTabReady(tabId);
      await omaEnsureFreshScript(tabId);
      // Conversa existente pode estar hidratando/streamando: só envia com a
      // página estabilizada (sem geração em curso), senão cliques são engolidos.
      await omaWaitSettled(tabId);
      const actual = await omaSendToTab(tabId, { operation: "GET_CONVERSATION_URL" });
      if (!actual.ok || !actual.result || actual.result.url !== job.conversation_url) {
        throw new Error("CONVERSATION_MISMATCH: tab não abriu a conversa solicitante");
      }
    }
    if (leaseLost) throw new Error("LEASE_LOST");
    await renew();
    // A channel/submit error is not proof that nothing was sent. Never replay.
    const sent = await omaSendToTab(tabId, {
      operation: "SEND_MESSAGE", text: job.prompt, images: job.images || [],
    });
    const attached = (sent && sent.result && sent.result.images_attached) || 0;
    worker.state = "WAITING_RESPONSE";
    const waited = await omaSendToTab(tabId, {
      operation: "WAIT_RESPONSE", timeout_ms: (job.timeout_s || 180) * 1000,
    });
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
      worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} cs=${omaLastCsVersion} err=${omaSwErrors}`,
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
      error: `[sw=${OMA_SW_VERSION}] ` + msg,
    });
  } finally {
    clearInterval(heartbeat);
    if (omaWorkers.has(tabId)) {
      // Preserva last_conv entre jobs (guarda anti-contaminação); limpa o resto.
      omaWorkers.set(tabId, { state: "IDLE", last_conv: omaWorkers.get(tabId).last_conv });
    }
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
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ oma_state: "PAIR_IN_OPTIONS" });
  chrome.alarms.create("oma-poll", { periodInMinutes: 1 });
});
chrome.runtime.onStartup.addListener(async () => {
  await omaStartupCleanup();
});
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === "oma-poll") omaTick(); });
setInterval(omaTick, OMA_POLL_MS);

