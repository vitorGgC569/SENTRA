/* service-worker.js (MV3) — coordena uma única aba existente do Edge principal.
 * A fila principal vive no relay/OMA. Research usa conversation_id: envia em
 * um chat, navega para o próximo e coleta depois pelo id. Nenhum pool paralelo.
 * SENTRA nunca cria nem fecha abas; adota temporariamente uma aba chatgpt.com
 * já aberta e restaura sua URL original ao liberar o controller. */
"use strict";

const OMA_RELAY = "http://127.0.0.1:8765";
const OMA_POOL = { minTabs: 1, maxTabs: 1 };
const OMA_POLL_MS = 2000;
const OMA_SW_VERSION = "1.6.26";
// Budgets MV3 (somente-leitura; a verdade est├í no servidor/Chrome):
// - native_bridge/job_store.py concede lease de 120s: renovar < 120s ou o relay
//   marca expirado e nenhum post tardio ├® aceito. Janela folgada de prop├│sito
//   (suspens├úo MV3 ~30-60s); heartbeat 10s + fatias 25s + pings renovam sempre.
// - Chrome suspende o SW ap├│s ~30s sem eventos; setInterval N├âO impede e o
//   contexto (heartbeat, promises pendentes, mapa em mem├│ria) morre junto.
// Estrat├®gia anti-morte-silenciosa, sem permiss├úo nova:
//  a) WAIT fatiado em 25s (nenhuma pend├¬ncia atravessa a janela de kill);
//  b) a tab (viva) pinga o SW a cada ~10s e cada ping renova o lease;
//  c) job ativo persistido em storage: restart do SW retoma sem reenviar;
//  d) alarme de 30s como backstop (pode ser clampado p/ 60s ÔÇö n├úo ├® o plano A).
const OMA_LEASE_MS = 30000;
const OMA_HB_MS = 10000;
const OMA_WAIT_SLICE_MS = 25000;
const OMA_HB_ALARM = "oma-hb";
const OMA_ACTIVE_PREFIX = "oma_active_";
const OMA_UPDATE_CHECK_MS = 30000;
// Keep the adopted controller stable for an MCP browser session. Normal
// release is explicit via BROWSER_ACTION close/browser shutdown; this timeout is
// only a crash/abandonment failsafe. The user's tab is restored, never closed.
const OMA_CONTROLLER_IDLE_RELEASE_MS = 300000;
let omaLastUpdateCheck = 0;
let omaTickBusy = false;
let omaControllerLastWorkAt = Date.now();

async function omaPoolInstanceId() {
  const stored = await chrome.storage.local.get({ oma_pool_instance_id: "" });
  let value = String(stored.oma_pool_instance_id || "");
  if (!/^POOL-[A-Za-z0-9-]{8,120}$/.test(value)) {
    let suffix;
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      suffix = globalThis.crypto.randomUUID();
    } else {
      suffix = String(Date.now()) + "-" + Math.random().toString(36).slice(2);
    }
    value = "POOL-" + suffix;
    await chrome.storage.local.set({ oma_pool_instance_id: value });
  }
  return value;
}

async function omaControllerOrigins() {
  const stored = await chrome.storage.local.get({ oma_controller_origins: {} });
  return stored.oma_controller_origins || {};
}

async function omaRememberControllerOrigin(tab) {
  if (!tab || typeof tab.id !== "number") return;
  const url = String(tab.url || "");
  if (!/^https:\/\/chatgpt\.com\//.test(url)) return;
  const origins = await omaControllerOrigins();
  const key = String(tab.id);
  if (!origins[key]) {
    origins[key] = url;
    await chrome.storage.local.set({ oma_controller_origins: origins });
  }
}

async function omaForgetControllerOrigin(tabId) {
  const origins = await omaControllerOrigins();
  const key = String(tabId);
  if (Object.prototype.hasOwnProperty.call(origins, key)) {
    delete origins[key];
    await chrome.storage.local.set({ oma_controller_origins: origins });
  }
}

async function omaRestoreControllerTab(tabId) {
  const origins = await omaControllerOrigins();
  const key = String(tabId);
  const origin = origins[key];
  if (!origin) return;
  try {
    const tab = await chrome.tabs.get(tabId);
    const current = String(tab.url || "");
    if (/^https:\/\/chatgpt\.com\//.test(origin) && current !== origin) {
      await chrome.tabs.update(tabId, { url: origin });
    }
  } catch (_) {
    // User closed the tab: only clear SENTRA bookkeeping.
  } finally {
    await omaForgetControllerOrigin(tabId);
  }
}

async function omaRestoreControllerTabs() {
  const origins = await omaControllerOrigins();
  for (const key of Object.keys(origins)) {
    const tabId = Number(key);
    if (Number.isFinite(tabId)) await omaRestoreControllerTab(tabId);
  }
}

async function omaReleaseRelayWorker(tabId) {
  try {
    await omaRelay("/workers/release", {
      method: "POST",
      body: JSON.stringify({ worker: `TAB-${tabId}` }),
    });
  } catch (_) {}
}

async function omaReleaseControllerReferences() {
  // Principal-Edge-only invariant: SENTRA never creates or closes browser tabs.
  // Deregister every local reference immediately so relay inventory cannot show
  // a released controller as online for the 45s heartbeat grace window.
  const referenced = new Set([...omaWorkers.keys()]);
  try {
    for (const tabId of await omaOwnedTabIds()) referenced.add(tabId);
  } catch (_) {}
  for (const tabId of referenced) await omaReleaseRelayWorker(tabId);

  // Restore the adopted tab to the user's original ChatGPT URL, then forget only
  // SENTRA's controller reference.
  await omaRestoreControllerTabs();
  omaWorkers.clear();
  omaSubmitFails.clear();
  try {
    await chrome.storage.local.set({ oma_owned_tabs: [] });
    await chrome.storage.local.remove("oma_created_tabs");
  } catch (_) {}
}

async function omaClaimPoolLeadership() {
  const instanceId = await omaPoolInstanceId();
  const result = await omaRelay("/workers/pool-claim", {
    method: "POST",
    body: JSON.stringify({ instance_id: instanceId }),
  });
  return !!(result && result.leader);
}

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

async function omaHeartbeatWorkers() {
  // Heartbeat never creates/adopts tabs; only the work scheduler may adopt one.
  for (const [tabId] of omaWorkers) {
    let status = {};
    try {
      await omaWaitTabReady(tabId, 5000);
      const st = await omaSendToTab(tabId, { operation: "GET_STATUS" });
      const r = (st && st.result) || {};
      status = {
        send_available: !!r.send_available,
        cap_banner: r.cap_banner || null,
        additional_checks: r.additional_checks || null,
        additional_checks_recovery_attempts: Number(r.additional_checks_recovery_attempts || 0),
        additional_checks_recovery_active: !!r.additional_checks_recovery_active,
        url: r.url || null,
        finished: r.finished !== false,
        composer_found: !!r.composer_found,
        diagnostics: r.diagnostics || null,
        sw_version: OMA_SW_VERSION,
        cs_version: r.cs_version || "unknown",
      };
    } catch (e) {
      status = {
        url: null,
        composer_found: false,
        sw_version: OMA_SW_VERSION,
        error: String((e && e.message) || e).slice(0, 500),
      };
    }
    try {
      await omaRelay("/workers/heartbeat", {
        method: "POST",
        body: JSON.stringify({ worker: `TAB-${tabId}`, status }),
      });
    } catch (_) {}
  }
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
  // Auto-update sem Ôå╗ manual: se o relay anuncia vers├úo maior e nenhum worker
  // est├í ocupado, recarrega a extens├úo. Jobs na fila do relay sobrevivem
  // (relay ├® processo separado); tabs pr├│prias s├úo re-adotadas via storage.
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

// tabId -> { state, job_id, task_id } — somente a referência ao controller
// existente que foi adotado temporariamente pelo worker.
const omaWorkers = new Map();

// Controllers que falham submit repetidamente degradam (composer travado,
// overlay persistente). A referência é liberada/restaurada; a tab do usuário
// nunca é fechada nem recriada pelo SENTRA.
const omaSubmitFails = new Map();

async function omaRecycleTab(tabId) {
  // Degraded controllers are references to the user's existing tab. Never close
  // or recreate it; deregister immediately, restore the original URL, then
  // release only SENTRA's reference.
  await omaReleaseRelayWorker(tabId);
  await omaRestoreControllerTab(tabId);
  omaWorkers.delete(tabId);
  omaSubmitFails.delete(tabId);
  await omaForgetOwned(tabId);
}

// Contador persistente de erros por local (catches nunca mais s├úo invis├¡veis).
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
  // Job em voo TEM que sobreviver a restart do SW (s├│ mem├│ria = amn├®sia =
  // resultado ├│rf├úo). NUNCA persiste prompt/imagens (quota do storage; o
  // resume jamais reenvia ÔÇö s├│ renova, espera e posta).
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
// sent, waiting, reading). Best-effort de prop├│sito: relay antigo devolve 404
// e rede pode solu├ºar ÔÇö telemetria nunca pode quebrar a entrega. O latch
// may_have_sent do servidor s├│ ├® confi├ível com relay novo; sem ele, o
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

// Renova o lease de um job persistido. Quem chama ├® sempre um EVENTO Chrome
// (alarme, ping da tab, fatia de espera) ÔÇö eventos acordam SW suspenso, que ├®
// exatamente o que o setInterval morto n├úo fazia.
async function omaRenewActive(tabId) {
  const active = await omaLoadActive(tabId);
  if (!active || !active.job_id || !active.lease_token) return false;
  await omaRenewIdentity({ job_id: active.job_id, worker: active.worker, lease_token: active.lease_token });
  active.hb_sw = (active.hb_sw || 0) + 1;
  active.updated = Date.now();
  try { await chrome.storage.local.set({ [omaActiveKey(tabId)]: active }); } catch (_) {}
  return true;
}

// Backstop do alarme: renova tudo em voo. N├âO substitui os pings da tab
// (alarme pode ser clampado para 60s > lease de 30s); s├│ encurta a janela.
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
        // Servidor declarou o lease morto: gera├º├úo ├│rf├ú nunca postar├í.
        // Para (economiza quota/compute) e para de rastrear.
        try { await omaSendToTab(tabId, { operation: "STOP_GENERATION" }); } catch (_) {}
        await omaClearActive(tabId);
      }
      // Erro de rede/transiente: mant├®m o active; a pr├│xima tentativa cura.
    }
  }
}

// Post dur├ível: resultado primeiro no storage (outbox), depois flush. Se o SW
// morrer entre os dois, o pr├│ximo tick re-flusha ÔÇö nunca perde post pronto.
// Preserva a identidade do worker que obteve o lease (TAB-xxx) para garantir
// que o job_store valide o post com sucesso.
async function omaPostResult(identity, jobRef, payload) {
  const workerIdentity = identity.worker || payload.worker;
  const merged = { ...payload, ...identity, worker: workerIdentity };
  await chrome.storage.local.set({ [`oma_result_${jobRef.job_id}`]: merged });
  await omaFlushOutbox();
}

chrome.tabs.onRemoved.addListener((tabId) => {
  void omaReleaseRelayWorker(tabId);
  omaForgetOwned(tabId);
  omaForgetControllerOrigin(tabId);
});

async function omaEnsureTabs(desiredTabs = OMA_POOL.minTabs) {
  const target = Math.max(
    OMA_POOL.minTabs,
    Math.min(OMA_POOL.maxTabs, Number(desiredTabs) || OMA_POOL.minTabs)
  );

  const alive = [];
  for (const tabId of await omaOwnedTabIds()) {
    try {
      const tab = await chrome.tabs.get(tabId);
      const url = String(tab.url || "");
      if (!/^https:\/\/chatgpt\.com\//.test(url)) {
        await omaForgetOwned(tabId);
        continue;
      }
      alive.push(tabId);
      if (!omaWorkers.has(tabId)) {
        omaWorkers.set(tabId, { state: "IDLE", adopted: true });
      }
    } catch (_) {
      await omaForgetOwned(tabId);
    }
  }

  for (const tabId of [...omaWorkers.keys()]) {
    if (!alive.includes(tabId)) {
      omaWorkers.delete(tabId);
      await omaForgetOwned(tabId);
    }
  }
  if (alive.length >= target) return;

  // Principal-Edge-only: adopt exactly one already-open, INACTIVE ChatGPT tab.
  // Never hijack the user's active ChatGPT tab (which may be this control chat).
  // If no inactive controller candidate exists, fail closed: SENTRA does not
  // create a tab and never launches/falls back to another browser/profile.
  const candidates = (await chrome.tabs.query({ url: ["https://chatgpt.com/*"] }))
    .filter((tab) => (
      typeof tab.id === "number"
      && tab.active !== true
      && /^https:\/\/chatgpt\.com\//.test(String(tab.url || ""))
    ))
    .sort((a, b) => Number(b.lastAccessed || 0) - Number(a.lastAccessed || 0));

  if (!candidates.length) return;

  const tab = candidates[0];
  await omaRememberControllerOrigin(tab);
  await omaRememberOwned(tab.id);
  omaWorkers.set(tab.id, { state: "IDLE", adopted: true, original_url: String(tab.url || "") });
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

function omaIsRecoverableMessageChannelError(error) {
  const message = String((error && error.message) || error || "");
  return /back\/forward cache|message channel is closed|receiving end does not exist|could not establish connection/i.test(message);
}

async function omaSendReadOnlyToTab(tabId, message, maxAttempts = 2) {
  let lastError = null;
  const attempts = Math.max(1, Math.min(Number(maxAttempts) || 1, 5));
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await omaSendToTab(tabId, message);
    } catch (error) {
      lastError = error;
      if (!omaIsRecoverableMessageChannelError(error) || attempt + 1 >= attempts) {
        throw error;
      }
      // Chromium can expose a completed tab while the previous document's port
      // is still entering BFCache. Read-only retries are safe; SEND_MESSAGE and
      // other side effects never use this helper. A BFCache/closed-port race can
      // still report the correct cs_version briefly, so force a real reload here
      // instead of trusting version freshness alone.
      const messageText = String((error && error.message) || error || "");
      if (/back\/forward cache|message channel is closed/i.test(messageText)) {
        try {
          await chrome.tabs.reload(tabId);
          await omaWaitTabDeparted(tabId, 8000);
          await omaWaitTabComplete(tabId, 15000);
        } catch (_) {}
      } else if (attempt === 0) {
        try { await omaEnsureFreshScript(tabId); } catch (_) {}
      }
      try { await omaWaitTabReady(tabId, 10000); } catch (_) {}
      await new Promise((r) => setTimeout(r, 350));
    }
  }
  throw lastError || new Error(`TAB_ERROR tab=${tabId}: read-only channel did not recover`);
}

async function omaWaitTabComplete(tabId, timeoutMs = 60000) {
  // Estado via API (n├úo sleep): s├│ fala com o content-script ap├│s carga completa,
  // eliminando a race onde a p├ígina antiga responde e o unload mata o canal.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === "complete" && tab.url && tab.url.startsWith("https://chatgpt.com/")) {
        return;
      }
    } catch (e) {
      throw new Error(`TAB_ERROR tab=${tabId}: tab sumiu durante navega├º├úo`);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`TAB_ERROR tab=${tabId}: navega├º├úo n├úo completou`);
}

async function omaWaitSettled(tabId, timeoutMs = 60000) {
  // Espera gera├º├úo anterior terminar + 2s de acomoda├º├úo antes de enviar.
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
  throw new Error(`TAB_ERROR tab=${tabId}: conversa n├úo estabilizou (gera├º├úo presa?)`);
}

async function omaWaitTabDeparted(tabId, timeoutMs = 15000) {
  // Ap├│s update/reload, o status ainda mostra o estado PR├ë-navega├º├úo por um
  // instante; ler "complete" a├¡ valida a p├ígina velha. Espera sair primeiro.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status !== "complete") return;
    } catch (e) {
      throw new Error(`TAB_ERROR tab=${tabId}: tab sumiu durante navega├º├úo`);
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  // SPA pode trocar de rota sem reload (status nunca sai de complete):
  // n├úo ├® erro, o caller valida frescura pelo script em seguida.
}

async function omaEnsureFreshScript(tabId) {
  // Soft-navigations SPA preservam content-scripts obsoletos indefinidamente.
  // Arquivos ├¡ntegros t├¬m cs_version == manifest.version;
  // diverg├¬ncia = script obsoleto -> reload real (reinje├º├úo garantida).
  const manifestVersion = chrome.runtime.getManifest().version;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const ans = await chrome.tabs.sendMessage(tabId, { operation: "GET_STATUS" });
      const inner = (ans && ans.result) || ans || {};
      const csv = inner.cs_version || inner.version || null;
      if (csv === manifestVersion) {
        omaLastCsVersion = csv;
        return;
      }
    } catch (_) {}
    try {
      await chrome.tabs.reload(tabId);
      await omaWaitTabDeparted(tabId, 8000);
      await omaWaitTabComplete(tabId, 15000);
      await omaWaitTabReady(tabId, 15000);
    } catch (_) {}
  }
}

async function omaWaitTabReady(tabId, timeoutMs = 45000) {
  // Aguarda o content-script responder (p├│s-navega├º├úo) em vez de sleep fixo.
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
  throw new Error(`TAB_ERROR tab=${tabId}: content-script n├úo respondeu (login exigido? DOM alterado?)`);
}


async function omaOpenFreshControllerChat(tabId) {
  let fresh = false;
  for (let attempt = 0; attempt < 3 && !fresh; attempt++) {
    if (attempt === 0) {
      await chrome.tabs.update(tabId, { url: "https://chatgpt.com/" });
    } else {
      await chrome.tabs.reload(tabId);
    }
    await omaWaitTabDeparted(tabId);
    await omaWaitTabComplete(tabId);
    await omaWaitTabReady(tabId);
    await omaEnsureFreshScript(tabId);
    try {
      const st = await omaSendToTab(tabId, { operation: "GET_STATUS" });
      fresh = !!(st.result && st.result.is_fresh_chat);
    } catch (_) {
      fresh = false;
    }
  }
  if (!fresh) {
    throw new Error(
      "STALE_CONVERSATION: controlador não conseguiu abrir chat zerado após 3 tentativas"
    );
  }
}

async function omaOpenConversationByUrl(tabId, conversationUrl) {
  if (!/^https:\/\/chatgpt\.com\/c\/[A-Za-z0-9-]{1,128}(\/|\?.*)?$/.test(conversationUrl || "")) {
    throw new Error("CONVERSATION_MISMATCH: URL explícita de conversa é obrigatória");
  }
  const expected = (conversationUrl.match(/\/c\/([A-Za-z0-9-]{1,128})/) || [])[1] || null;
  let current = null;
  try {
    const tab = await chrome.tabs.get(tabId);
    current = ((tab.url || "").match(/\/c\/([A-Za-z0-9-]{1,128})/) || [])[1] || null;
  } catch (_) {}
  if (expected && current !== expected) {
    await chrome.tabs.update(tabId, { url: conversationUrl });
    await omaWaitTabDeparted(tabId);
    await omaWaitTabComplete(tabId);
    await omaWaitTabReady(tabId);
    await omaEnsureFreshScript(tabId);
  }
  const actual = await omaSendReadOnlyToTab(
    tabId,
    { operation: "GET_CONVERSATION_URL" },
    4,
  );
  const result = (actual && actual.result) || {};
  const actualId = result.conversation_id
    || (((result.url || "").match(/\/c\/([A-Za-z0-9-]{1,128})/) || [])[1] || null);
  if (!expected || !actualId || expected !== actualId) {
    throw new Error("CONVERSATION_MISMATCH: controlador não abriu a conversa solicitada");
  }
  return result;
}

async function omaWaitConversationIdentity(tabId, timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const conv = await omaSendToTab(tabId, { operation: "GET_CONVERSATION_URL" });
      const result = (conv && conv.result) || {};
      if (result.conversation_id && result.url) return result;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("CONVERSATION_ID_TIMEOUT: envio aceito mas conversation_id não apareceu");
}

async function omaWaitConversationResponse(tabId, identity, job, renew) {
  const waitDeadline = Date.now() + (job.timeout_s || 180) * 1000;
  let slices = 0;
  let csHb = 0;
  let waited = null;
  for (;;) {
    const remaining = waitDeadline - Date.now();
    if (remaining <= 0) {
      throw new Error("TIMEOUT waiting stable response (CHAT_COLLECT)");
    }
    await renew();
    const slice = Math.min(OMA_WAIT_SLICE_MS, remaining);
    slices++;
    if (slices % 3 === 1) await omaProgressPhase(tabId, identity, "waiting");
    try {
      waited = await omaSendReadOnlyToTab(tabId, { operation: "WAIT_RESPONSE", timeout_ms: slice });
      const hb = waited && waited.result && waited.result.hb_cs;
      if (typeof hb === "number" && Number.isFinite(hb)) csHb += hb;
      break;
    } catch (e) {
      const msg = String((e && e.message) || e);
      const m = msg.match(/csping=(\d+)/);
      if (m) {
        try { csHb += parseInt(m[1], 10); } catch (_) {}
      }
      if (/TIMEOUT/.test(msg) && Date.now() < waitDeadline) continue;
      throw e;
    }
  }
  return { waited, slices, csHb };
}

async function omaProcessJob(tabId, job) {
  const worker = omaWorkers.get(tabId);
  if (!worker) return;
  worker.state = "BUSY";
  worker.job_id = job.job_id;
  worker.task_id = job.task_id;
  const identity = { job_id: job.job_id, worker: `TAB-${tabId}`, lease_token: job.lease_token };
  // Telemetria de vida (vai no resultado): hb_sw = renova├º├Áes do SW,
  // slices = fatias de WAIT, cshb = pings da tab, rec = 1 se houve resume.
  // V├úo DENTRO da string worker: o relay rejeita campos desconhecidos (400).
  let hbSw = 0;
  let slices = 0;
  let csHb = 0;
  // Persiste ANTES de qualquer efeito no browser: restart no meio do caminho
  // recupera pelo storage em vez de ├│rf├úo. Sem prompt/imagens (ver omaSaveActive).
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
    // S├│ 400 (servidor rejeitou o lease) prova perda. Blip de rede cura no
    // pr├│ximo ciclo: o lease tem 30s de folga e o heartbeat roda a cada 10s.
    // (Antes: QUALQUER erro abortava uma gera├º├úo saud├ível.)
    if (!String((e && e.message) || e).includes("RELAY_HTTP_400")) return;
    leaseLost = true;
    try { await omaSendToTab(tabId, { operation: "STOP_GENERATION" }); } catch (_) {}
  }), OMA_HB_MS);
  const postResult = async (payload) => omaPostResult(identity, job, payload);


  if (job.kind === "CHAT_START") {
    try {
      await renew();
      await omaProgressPhase(tabId, identity, "preparing");
      await omaOpenFreshControllerChat(tabId);
      await omaProgressPhase(tabId, identity, "ready");
      await omaProgressPhase(tabId, identity, "sending");
      const sent = await omaSendToTab(tabId, {
        operation: "SEND_MESSAGE",
        text: job.prompt,
        images: job.images || [],
      });
      const attached = (sent && sent.result && sent.result.images_attached) || 0;
      await omaSaveActive(tabId, { sent: true, images_attached: attached });
      await omaProgressPhase(tabId, identity, "sent");
      const conv = await omaWaitConversationIdentity(tabId, 20000);
      if (conv.conversation_id) worker.last_conv = conv.conversation_id;
      await postResult({
        job_id: job.job_id,
        task_id: job.task_id,
        status: "COMPLETED",
        result: JSON.stringify({
          started: true,
          conversation_id: conv.conversation_id,
          conversation_url: conv.url,
        }),
        conversation_url: conv.url || null,
        conversation_id: conv.conversation_id || null,
        images_attached: attached,
        worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} mode=chat-start`,
      });
    } catch (e) {
      await omaNoteError("chat_start");
      await postResult({
        job_id: job.job_id,
        task_id: job.task_id,
        status: "FAILED",
        error: `[sw=${OMA_SW_VERSION}] chat_start: ${String((e && e.message) || e)}`,
      });
    } finally {
      clearInterval(heartbeat);
      await omaClearActive(tabId);
      if (omaWorkers.has(tabId)) {
        omaWorkers.set(tabId, { state: "IDLE", last_conv: worker.last_conv || null });
      }
    }
    return;
  }

  if (job.kind === "CHAT_COLLECT") {
    try {
      await renew();
      await omaProgressPhase(tabId, identity, "navigating");
      const conv = await omaOpenConversationByUrl(tabId, job.conversation_url);
      // Do NOT wait for "settled" here. WAIT_RESPONSE must observe the live UI
      // so transient additional-checks banners can be recovered while the
      // generation is still active.
      await omaProgressPhase(tabId, identity, "reading");
      const collected = await omaWaitConversationResponse(tabId, identity, job, renew);
      await postResult({
        job_id: job.job_id,
        task_id: job.task_id,
        status: "COMPLETED",
        result: collected.waited && collected.waited.result
          ? collected.waited.result.text
          : "",
        conversation_url: conv.url || job.conversation_url,
        conversation_id: conv.conversation_id || null,
        worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} mode=chat-collect slices=${collected.slices} cshb=${collected.csHb}`,
      });
    } catch (e) {
      await omaNoteError("chat_collect");
      await postResult({
        job_id: job.job_id,
        task_id: job.task_id,
        status: "FAILED",
        error: `[sw=${OMA_SW_VERSION}] chat_collect: ${String((e && e.message) || e)}`,
      });
    } finally {
      clearInterval(heartbeat);
      await omaClearActive(tabId);
      if (omaWorkers.has(tabId)) {
        omaWorkers.set(tabId, { state: "IDLE", last_conv: worker.last_conv || null });
      }
    }
    return;
  }

  if (job.kind === "BROWSER_ACTION") {
    let releaseAfter = false;
    try {
      await renew();
      const action = job.browser_action || "";
      const args = job.browser_args || {};
      let result = {};
      if (action === "navigate") {
        const target = String(args.url || "");
        const parsed = new URL(target);
        if (parsed.protocol !== "https:" || parsed.hostname !== "chatgpt.com") {
          throw new Error("BROWSER_ACTION navigate is restricted to https://chatgpt.com");
        }
        await chrome.tabs.update(tabId, { url: target });
        await omaWaitTabDeparted(tabId, 8000);
        await omaWaitTabComplete(tabId, 60000);
        await omaWaitTabReady(tabId, 30000);
        const tabInfo = await chrome.tabs.get(tabId);
        result = { url: tabInfo.url || target };
      } else if (action === "extract") {
        const reply = await omaSendToTab(tabId, {
          operation: "BROWSER_EXTRACT",
          selector: args.selector || "body",
          max_chars: args.max_chars || 200000,
        });
        result = (reply && reply.result) || {};
      } else if (action === "click") {
        const reply = await omaSendToTab(tabId, {
          operation: "BROWSER_CLICK",
          selector: args.selector,
        });
        result = (reply && reply.result) || {};
      } else if (action === "type") {
        const reply = await omaSendToTab(tabId, {
          operation: "BROWSER_TYPE",
          selector: args.selector,
          text: args.text || "",
          clear: !!args.clear,
        });
        result = (reply && reply.result) || {};
      } else if (action === "close") {
        result = { closed: true, tab_preserved: true, controller_released: true };
        releaseAfter = true;
      } else {
        throw new Error("unsupported BROWSER_ACTION");
      }
      await postResult({
        job_id: job.job_id,
        task_id: job.task_id,
        status: "COMPLETED",
        result: JSON.stringify(result),
        worker: `BROWSER_WORKER_${tabId} sw=${OMA_SW_VERSION} action=${action}`,
      });
      if (releaseAfter) {
        try { await omaReleaseControllerReferences(); } catch (_) {}
      }
    } catch (e) {
      await postResult({
        job_id: job.job_id,
        task_id: job.task_id,
        status: "FAILED",
        error: `[sw=${OMA_SW_VERSION}] browser_action: ${String((e && e.message) || e)}`,
      });
    } finally {
      clearInterval(heartbeat);
      await omaClearActive(tabId);
      if (omaWorkers.has(tabId)) omaWorkers.set(tabId, { state: "IDLE" });
    }
    return;
  }

  // Probe is read-only during normal operation. Immediately after an extension
  // reload the existing ChatGPT document can retain an orphaned old content
  // script; repair that one stale-injection case in-place before reading status.
  if (job.kind === "STATUS_PROBE") {
    try {
      await renew();
      await omaEnsureFreshScript(tabId);
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
      // Navega├º├úo ├® feita pelo worker (chrome.tabs): navegar via content-script
      // mataria o canal de mensagem antes da resposta.
      // SPA pode trocar de rota sem reload: EXIGE conversa zerada, com reload
      // for├ºado como fallback. Prompt em conversa obsoleta = contamina├º├úo.
      let fresh = false;
      for (let attempt = 0; attempt < 3 && !fresh; attempt++) {
        if (attempt === 0) {
          await chrome.tabs.update(tabId, { url: "https://chatgpt.com/" });
        } else {
          await chrome.tabs.reload(tabId); // reload real: nova inje├º├úo garantida
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
        throw new Error("STALE_CONVERSATION: sem chat zerado ap├│s 3 tentativas; "
          + "job abortado para n├úo contaminar");
      }
    } else {
      if (!/^https:\/\/chatgpt\.com\/c\/[A-Za-z0-9-]{1,128}(\/|\?.*)?$/.test(job.conversation_url || "")) {
        throw new Error("CONVERSATION_MISMATCH: continua├º├úo exige URL expl├¡cita");
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
      // Conversa existente pode estar hidratando/streamando: s├│ envia com a
      // p├ígina estabilizada (sem gera├º├úo em curso), sen├úo cliques s├úo engolidos.
      await omaWaitSettled(tabId);
      const actual = await omaSendReadOnlyToTab(
        tabId,
        { operation: "GET_CONVERSATION_URL" },
        4,
      );
      const actualConvId = (actual && actual.result && (actual.result.conversation_id || ((actual.result.url || "").match(/\/c\/([A-Za-z0-9-]{1,128})/) || [])[1])) || null;
      const urlMatches = actual && actual.result && actual.result.url && (
        (targetConvId && actualConvId && targetConvId === actualConvId) ||
        actual.result.url.split("?")[0].replace(/\/$/, "") === job.conversation_url.split("?")[0].replace(/\/$/, "")
      );
      if (!actual.ok || !actual.result || !urlMatches) {
        throw new Error("CONVERSATION_MISMATCH: tab n├úo abriu a conversa solicitante");
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
    // WAIT FATIADO (o cora├º├úo do fix): nenhuma pend├¬ncia SW<->tab atravessa a
    // janela de suspens├úo do SW (~30s) nem o lease (30s). Cada fatia renova o
    // lease antes de esperar; TIMEOUT de fatia com gera├º├úo em curso = continuar,
    // n├úo falhar. A tab preserva omaPendingResponseBaseline entre fatias, ent├úo
    // re-entrar no WAIT nunca confunde o turno anterior com o atual. Se a
    // resposta j├í estiver pronta no DOM (caso do sintoma), a primeira fatia
    // resolve em ~2-3s (3 amostras est├íveis).
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
    // Guarda anti-contamina├º├úo: com new_chat, o ID da conversa TEM que mudar.
    if (job.new_chat && worker.last_conv && convId && convId === worker.last_conv) {
      throw new Error("STALE_CONVERSATION: conversa n├úo mudou ap├│s new_chat "
        + `(id repetido ${convId}); prompt pode ter ca├¡do no chat anterior`);
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
        await omaRecycleTab(tabId); // tab degradada: libera referência; nunca fecha a tab do usuário
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
      // Preserva last_conv entre jobs (guarda anti-contamina├º├úo); limpa o resto.
      omaWorkers.set(tabId, { state: "IDLE", last_conv: omaWorkers.get(tabId).last_conv });
    }
  }
}

const omaResumeBusy = new Set();

// Retoma job ├│rf├úo de restart do SW: a tab est├í viva (a resposta pode j├í estar
// no DOM) mas o contexto que renovava/postava morreu com o SW antigo. NUNCA
// reenvia: s├│ renova, espera fatiado (o baseline da tab continua intacto) e
// posta. Respeita o deadline original ÔÇö resume n├úo estende o timeout do job.
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
        // renova a cada fatia (e detecta LEASE_LOST real l├í).
      } else {
        // Lease j├í expirou no servidor (DELIVERY_EXPIRED registrado l├í):
        // nenhum post salvaria; para a gera├º├úo ├│rf├ú e desiste sem ru├¡do.
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
    // Guarda anti-contamina├º├úo do caminho normal, com o last_conv de ANTES do
    // job (persistido ÔÇö o em mem├│ria morreu com o SW antigo).
    if (active.new_chat && active.last_conv && convId && convId === active.last_conv) {
      throw new Error("STALE_CONVERSATION: conversa n├úo mudou ap├│s new_chat "
        + `(id repetido ${convId}); prompt pode ter ca├¡do no chat anterior`);
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
    // Se o lease j├í expirou no servidor, este post ├® descartado pelo relay
    // (400) e some no flush ÔÇö correto: o servidor j├í registrou DELIVERY_EXPIRED.
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

// Varre jobs persistidos sem dono em mem├│ria (SW reiniciou no meio do voo).
// S├│ retoma CHAT_TASK j├í enviado. N├úo-enviado expira honestamente no servidor
// (reenviar envio incerto = risco de duplicar gera├º├úo) e probe ├® barato de
// repetir via novo poll ÔÇö ambos sem reanima├º├úo incerta aqui.
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
      if (mem && mem.state !== "IDLE") continue; // loop vivo ├® o dono
      if (omaResumeBusy.has(tabId)) continue;
      try {
        await chrome.tabs.get(tabId);
      } catch (_) {
        await omaClearActive(tabId); // tab sumiu: para de rastrear, servidor expira
        continue;
      }
      if (!active.sent || (active.kind && active.kind !== "CHAT_TASK")) continue;
      omaResumeBusy.add(tabId);
      // Sem await (paralelo como o poll); a trava + WAITING s├¡ncrono evitam
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
    // Version discovery is public, loopback-only and contains no secret. Run it
    // before pairing/auth so a stale relay token can never block self-update.
    await omaCheckForUpdates();

    const settings = await chrome.storage.local.get({
      oma_enabled: false,
      oma_relay_token: "",
      oma_pool_size: OMA_POOL.maxTabs,
    });
    if (!settings.oma_enabled || !settings.oma_relay_token) return;
    const desiredPool = Math.max(
      OMA_POOL.minTabs,
      Math.min(OMA_POOL.maxTabs, Number(settings.oma_pool_size) || OMA_POOL.maxTabs)
    );
    let leader = false;
    try { leader = await omaClaimPoolLeadership(); }
    catch (_) { return; }
    if (!leader) {
      await omaReleaseControllerReferences();
      return;
    }
    await omaFlushOutbox();

    // Lazy controller: no queued/leased work means no adopted controller
    // reference. The user's ChatGPT tab itself is never closed or created.
    let relayHealth = {};
    try { relayHealth = await omaRelay("/health"); } catch (_) { return; }
    const queued = Number(relayHealth.queued || 0);
    const leased = Number(relayHealth.leased || 0);
    const activeJobs = await omaLoadAllActive();
    const hasWork = queued > 0 || leased > 0 || activeJobs.length > 0;
    if (!hasWork) {
      if (
        omaWorkers.size > 0
        && Date.now() - omaControllerLastWorkAt >= OMA_CONTROLLER_IDLE_RELEASE_MS
      ) {
        await omaReleaseControllerReferences();
      }
      return;
    }

    omaControllerLastWorkAt = Date.now();
    const desiredTabs = Math.max(
      OMA_POOL.minTabs,
      Math.min(
        desiredPool,
        Math.max(queued + leased, activeJobs.length)
      )
    );
    await omaEnsureTabs(desiredTabs);
    await omaHeartbeatWorkers();
    await omaRecoverActive(); // órfãos de restart antes de leasear trabalho novo
    for (const [tabId, worker] of omaWorkers) {
      if (worker.state !== "IDLE") continue;
      const busy = [...omaWorkers.values()].filter((w) => w.state !== "IDLE").length;
      if (busy >= desiredTabs) break;
      let data = null;
      try {
        data = await omaRelay(`/jobs/poll?worker=TAB-${tabId}`);
      } catch (_) { return; } // relay offline: tenta de novo no pr├│ximo tick
      if (data && data.job) {
        omaControllerLastWorkAt = Date.now();
        omaProcessJob(tabId, data.job); // controller único; job continua async
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
  // Principal-Edge-only: never close browser tabs. Deregister + restore any
  // adopted tab left behind by a previous SW lifecycle, then clear stale SENTRA
  // bookkeeping. release_worker is best-effort if the relay is still offline.
  try { await omaReleaseControllerReferences(); } catch (_) {}
  try { omaWorkers.clear(); } catch (_) {}
  try {
    const stored = await chrome.storage.local.get(null);
    const actives = Object.keys(stored || {}).filter((k) => k.startsWith(OMA_ACTIVE_PREFIX));
    if (actives.length) await chrome.storage.local.remove(actives);
  } catch (_) {}
  try { omaResumeBusy.clear(); } catch (_) {}
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ oma_state: "PAIR_IN_OPTIONS" });
  try { chrome.alarms.create("oma-poll", { periodInMinutes: 0.5 }); }
  catch (_) { chrome.alarms.create("oma-poll", { periodInMinutes: 1 }); }
  try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 0.5 }); }
  catch (_) { try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 1 }); } catch (_) {} }
});
chrome.runtime.onStartup.addListener(async () => {
  await omaStartupCleanup();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  // Retornar a promise estende a vida do SW at├® o trabalho assentar.
  if (alarm.name === "oma-poll") return omaTick();
  if (alarm.name === OMA_HB_ALARM) {
    return Promise.allSettled([omaRenewAllActive(), omaHeartbeatWorkers(), omaTick()]);
  }
  return undefined;
});
// Alarmes sobrevivem ao restart do SW, mas recriar no topo (idempotente)
// cobre update/reload que limpe a agenda sem disparar onInstalled.
try { chrome.alarms.create("oma-poll", { periodInMinutes: 0.5 }); }
catch (_) { try { chrome.alarms.create("oma-poll", { periodInMinutes: 1 }); } catch (_) {} }
try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 0.5 }); }
catch (_) { try { chrome.alarms.create(OMA_HB_ALARM, { periodInMinutes: 1 }); } catch (_) {} }

// Acordado pela tab: OMA_LEASE_PING (a cada ~10s durante o WAIT) renova o
// lease na hora; OMA_RESULT_READY (resposta estabilizou) dispara o recover.
// Mensagem de content-script ACORDA SW suspenso ÔÇö ├® o canal que atravessa o
// kill de ~30s. N├úo conflita com omaSendToTab (tabs.sendMessage usa o canal
// de resposta, n├úo este listener).
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  const supported = new Set(["OMA_LEASE_PING", "OMA_RESULT_READY", "OMA_IDLE_WAKE"]);
  if (!request || !supported.has(request.operation)) return false;
  const tabId = sender && sender.tab && sender.tab.id;
  (async () => {
    if (request.operation === "OMA_IDLE_WAKE") {
      if (typeof tabId !== "number") return { ok: false, ignored: true };

      // Any existing ChatGPT tab may wake the lazy scheduler. It does not become
      // a controller merely by pinging: omaTick() adopts a tab only when relay
      // work exists. This avoids the MV3 deadlock where no owned tab existed yet.
      const senderUrl = String((sender && sender.tab && sender.tab.url) || "");
      if (!/^https:\/\/chatgpt\.com\//.test(senderUrl)) {
        return { ok: true, ignored: true };
      }

      const owned = await omaOwnedTabIds();
      if (owned.has(tabId)) {
        try {
          await omaRelay("/workers/heartbeat", {
            method: "POST",
            body: JSON.stringify({ worker: `TAB-${tabId}` }),
          });
        } catch (_) {}
      }
      await omaTick();
      return { ok: true, idle_wake: true, owned: owned.has(tabId) };
    }
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
// Bootstrap immediately after extension reload; subsequent wake-ups come from
// alarms and OMA_IDLE_WAKE pings from existing ChatGPT tabs.
void omaTick();
setInterval(omaTick, OMA_POLL_MS);

