/* observer.js — espera orientada a eventos (MutationObserver), sem polling burro.
 * Resolve quando a geração termina: botão stop some E último texto estabiliza. */
"use strict";

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

    const finish = (ok, value) => {
      if (settled) return;
      settled = true;
      try { observer.disconnect(); } catch (_) {}
      ok ? resolve(value) : reject(value);
    };

    const sample = () => {
      if (Date.now() > deadline) {
        finish(false, new Error(
          `TIMEOUT waiting stable response (${lastText.length} chars)`));
        return;
      }
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
    const ticker = setInterval(() => { if (settled) clearInterval(ticker); else sample(); }, 1000);
    sample();
  });
}
