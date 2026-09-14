/* observer.js — espera orientada a eventos (MutationObserver), sem polling burro.
 * Resolve quando a geração termina: botão stop some E último texto estabiliza.
 * Prova de vida MV3: durante a espera a tab (viva) pinga o SW a cada ~10s via
 * runtime.sendMessage. Cada ping ACORDA um SW suspenso a tempo de renovar o
 * lease de 30s; sem isso, só o setInterval do SW renovava — e ele morre junto
 * com o SW (~30s sem eventos), órfão do resultado. Custo: 1 msg/10s por tab. */
"use strict";

// Contador de pings da fatia WAIT atual (o content-script lê para telemetria).
let omaStableWaitPings = 0;

function omaSendSwPing(operation) {
  // Best-effort: SW morto = sendMessage rejeita; o próximo ping/alarmes curam.
  try {
    const p = chrome.runtime.sendMessage({ operation });
    if (p && typeof p.catch === "function") p.catch(() => {});
  } catch (_) {}
}

function omaGenerationFinished() {
  const stop = omaQueryFirst(OMA_SELECTORS.stopButton);
  return !(stop && omaIsVisible(stop));
}

function omaLastAssistantText() {
  const nodes = document.querySelectorAll(
    OMA_SELECTORS.assistantMessages.join(",")
  );
  if (!nodes.length) return "";
  return (nodes[nodes.length - 1].innerText || "").trim();
}

function omaWaitForStableResponse(timeoutMs, stableSamples = 3, baseline = null) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    let previousHash = null;
    let stableCount = 0;
    let lastText = "";
    let settled = false;
    let ticker = 0;
    let lastPing = Date.now();
    omaStableWaitPings = 0;

    const finish = (ok, value) => {
      if (settled) return;
      settled = true;
      try { observer.disconnect(); } catch (_) {}
      try { clearInterval(ticker); } catch (_) {}
      // Resposta pronta: acorda o SW na hora. Se o reply desta chamada cair
      // num contexto morto, o recover do SW puxa o texto via nova fatia
      // (o baseline desta espera sobrevive na tab).
      if (ok) omaSendSwPing("OMA_RESULT_READY");
      ok ? resolve(value) : reject(value);
    };

    const sample = () => {
      if (Date.now() > deadline) {
        finish(false, new Error(
          `TIMEOUT waiting stable response (${lastText.length} chars)`));
        return;
      }
      // Liveness antes de qualquer early-return: pinga mesmo com o turno
      // anterior ainda na tela (geração pode nem ter começado).
      try {
        if (Date.now() - lastPing >= 10000) {
          lastPing = Date.now();
          omaStableWaitPings++;
          omaSendSwPing("OMA_LEASE_PING");
        }
      } catch (_) {}
      let text = "";
      try { text = omaLastAssistantText(); } catch (_) { text = ""; }
      const count = document.querySelectorAll(OMA_SELECTORS.assistantMessages.join(",")).length;
      if (baseline && count <= baseline.count && text === baseline.text) {
        stableCount = 0;
        return; // The previous turn cannot satisfy a new SEND_MESSAGE.
      }
      // Hash simples e síncrono: suficiente para detectar estabilidade.
      let h = 0;
      for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
      if (h === previousHash && text) stableCount++;
      else { stableCount = 0; previousHash = h; }
      lastText = text;
      let done = false;
      try { done = omaGenerationFinished(); } catch (_) { done = false; }
      if (done && stableCount >= stableSamples && text) finish(true, text);
    };

    const observer = new MutationObserver(sample);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    ticker = setInterval(() => { if (settled) clearInterval(ticker); else sample(); }, 1000);
    sample();
  });
}
