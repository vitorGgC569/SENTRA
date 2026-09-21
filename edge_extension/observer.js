/* observer.js — espera orientada a eventos e recuperação de estados transitórios. */
"use strict";

let omaStableWaitPings = 0;

function omaSendSwPing(operation) {
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
  const nodes = document.querySelectorAll(OMA_SELECTORS.assistantMessages.join(","));
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
    let sampleBusy = false;
    let recoveryCount = 0;
    let lastRecoveredMessageCount = -1;
    omaStableWaitPings = 0;

    const finish = (ok, value) => {
      if (settled) return;
      settled = true;
      try { observer.disconnect(); } catch (_) {}
      try { clearInterval(ticker); } catch (_) {}
      if (ok) omaSendSwPing("OMA_RESULT_READY");
      ok ? resolve(value) : reject(value);
    };

    const recoverSpecialUi = async (text, count) => {
      if (typeof omaIsAdditionalChecksMessage !== "function" ||
          !omaIsAdditionalChecksMessage(text)) return false;
      if (count === lastRecoveredMessageCount) return true;
      if (typeof OMA_MAX_ADDITIONAL_CHECK_RECOVERIES !== "number" ||
          recoveryCount >= OMA_MAX_ADDITIONAL_CHECK_RECOVERIES) {
        finish(false, new Error(
          "MODEL_ERROR: ADDITIONAL_CHECKS_LOOP: aviso de verificações adicionais persistiu"
        ));
        return true;
      }

      recoveryCount++;
      lastRecoveredMessageCount = count;
      previousHash = null;
      stableCount = 0;
      lastText = "";
      try {
        if (typeof omaRecoverAdditionalChecks !== "function") {
          throw new Error("ADDITIONAL_CHECKS_RECOVERY_FAILED: helper indisponível");
        }
        await omaRecoverAdditionalChecks();
        omaSendSwPing("OMA_ADDITIONAL_CHECKS_RECOVERED");
      } catch (e) {
        finish(false, e instanceof Error ? e : new Error(String(e)));
      }
      return true;
    };

    const sample = async () => {
      if (settled || sampleBusy) return;
      sampleBusy = true;
      try {
        if (Date.now() > deadline) {
          finish(false, new Error("TIMEOUT waiting stable response (" + lastText.length + " chars)"));
          return;
        }
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
        if (await recoverSpecialUi(text, count)) return;

        if (baseline && count <= baseline.count && text === baseline.text) {
          stableCount = 0;
          return;
        }

        let h = 0;
        for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
        if (h === previousHash && text) stableCount++;
        else { stableCount = 0; previousHash = h; }
        lastText = text;

        let done = false;
        try { done = omaGenerationFinished(); } catch (_) { done = false; }
        if (done && stableCount >= stableSamples && text) finish(true, text);
      } finally {
        sampleBusy = false;
      }
    };

    const observer = new MutationObserver(() => { void sample(); });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    ticker = setInterval(() => {
      if (settled) clearInterval(ticker);
      else void sample();
    }, 1000);
    void sample();
  });
}
