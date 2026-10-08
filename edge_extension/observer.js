/* observer.js — espera orientada a eventos e recuperação de estados transitórios. */
"use strict";

let omaStableWaitPings = 0;
const OMA_IDLE_WAKE_MS = 15000;
const OMA_RESPONSE_QUIET_MS = 5000;
const OMA_DONE_QUIET_MS = 3000;

function omaSendSwPing(operation) {
  try {
    const p = chrome.runtime.sendMessage({ operation });
    if (p && typeof p.catch === "function") p.catch(() => {});
  } catch (_) {}
}

// MV3 service workers are suspended while idle. Content scripts remain alive,
 // so owned tabs periodically wake the worker. The service worker itself verifies
 // sender.tab.id against oma_owned_tabs before polling; personal ChatGPT tabs are
 // therefore harmless even though this content script is injected there too.
 try {
   setInterval(() => omaSendSwPing("OMA_IDLE_WAKE"), OMA_IDLE_WAKE_MS);
 } catch (_) {}

function omaGenerationFinished() {
  const stop = omaQueryFirst(OMA_SELECTORS.stopButton);
  return !(stop && omaIsVisible(stop));
}

function omaNodeReadableText(node) {
  if (!node) return "";
  try {
    const rendered = String(node.innerText || "").trim();
    if (rendered) return rendered;
  } catch (_) {}
  try {
    return String(node.textContent || "").trim();
  } catch (_) {
    return "";
  }
}

function omaChatGptAccessibleAssistantNodes() {
  if (typeof OMA_SITE !== "undefined" && OMA_SITE !== "chatgpt") return [];
  const found = [];
  const seen = new Set();
  let labels = [];
  try {
    labels = [...document.querySelectorAll("main [class*='sr-only']")];
  } catch (_) {
    return found;
  }
  for (const label of labels) {
    const labelText = omaNodeReadableText(label);
    if (!/chatgpt/i.test(labelText)) continue;
    const candidates = [];
    if (label.nextElementSibling) candidates.push(label.nextElementSibling);
    if (label.parentElement) {
      for (const child of label.parentElement.children) {
        if (child !== label) candidates.push(child);
      }
    }
    for (const candidate of candidates) {
      if (!candidate || seen.has(candidate)) continue;
      const text = omaNodeReadableText(candidate);
      if (!text || text === labelText) continue;
      seen.add(candidate);
      found.push(candidate);
      break;
    }
  }
  return found;
}

function omaAssistantMessageCount() {
  if (typeof OMA_SITE !== "undefined" && OMA_SITE === "gemini") {
    return document.querySelectorAll("model-response").length;
  }
  const direct = document.querySelectorAll(OMA_SELECTORS.assistantMessages.join(","));
  if (direct.length) return direct.length;
  return omaChatGptAccessibleAssistantNodes().length;
}

function omaLastAssistantText() {
  const nodes = document.querySelectorAll(OMA_SELECTORS.assistantMessages.join(","));
  if (nodes.length) return omaNodeReadableText(nodes[nodes.length - 1]);
  const fallback = omaChatGptAccessibleAssistantNodes();
  if (!fallback.length) return "";
  return omaNodeReadableText(fallback[fallback.length - 1]);
}

function omaWaitForStableResponse(timeoutMs, stableSamples = 3, baseline = null) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    let previousHash = null;
    let stableCount = 0;
    let lastText = "";
    let lastTextChangedAt = Date.now();
    let doneSince = null;
    let settled = false;
    let ticker = 0;
    let lastPing = Date.now();
    let sampleBusy = false;
    let recoveryCount = 0;
    let lastRecoveredMessageCount = -1;
    let recoveryPending = null;
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
      const banner = (
        typeof omaFindAdditionalChecksBannerText === "function"
          ? omaFindAdditionalChecksBannerText()
          : null
      );
      const detectedText = (
        typeof omaIsAdditionalChecksMessage === "function"
        && omaIsAdditionalChecksMessage(text)
      ) ? text : banner;
      if (!detectedText) {
        // A new non-warning assistant response proves the recovered turn moved on.
        if (recoveryPending && count > recoveryPending.count) recoveryPending = null;
        return false;
      }

      const signature = (
        typeof omaFoldUiText === "function"
          ? omaFoldUiText(detectedText)
          : String(detectedText).toLowerCase()
      ).slice(0, 240);

      // After sending Continue the previous warning remains visible until the
      // next assistant turn appears. Do not immediately stop the new generation
      // and send Continue again. Retry only if the same warning is still the
      // terminal state after a grace period.
      if (
        recoveryPending
        && recoveryPending.signature === signature
        && count <= recoveryPending.count
      ) {
        let finished = true;
        try { finished = omaGenerationFinished(); } catch (_) {}
        if (!finished || Date.now() - recoveryPending.at < 12000) return true;
      }

      if (typeof OMA_MAX_ADDITIONAL_CHECK_RECOVERIES !== "number" ||
          recoveryCount >= OMA_MAX_ADDITIONAL_CHECK_RECOVERIES) {
        finish(false, new Error(
          "MODEL_ERROR: ADDITIONAL_CHECKS_LOOP: aviso de verificações adicionais persistiu"
        ));
        return true;
      }

      recoveryCount++;
      lastRecoveredMessageCount = count;
      recoveryPending = { signature, count, at: Date.now() };
      previousHash = null;
      stableCount = 0;
      lastText = "";
      lastTextChangedAt = Date.now();
      doneSince = null;
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
        const count = omaAssistantMessageCount();
        if (await recoverSpecialUi(text, count)) return;

        if (baseline && count <= baseline.count && text === baseline.text) {
          stableCount = 0;
          doneSince = null;
          lastTextChangedAt = Date.now();
          return;
        }

        let h = 0;
        for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
        if (h === previousHash && text) {
          stableCount++;
        } else {
          stableCount = 0;
          previousHash = h;
          lastTextChangedAt = Date.now();
        }
        lastText = text;

        let done = false;
        try { done = omaGenerationFinished(); } catch (_) { done = false; }
        if (done) {
          if (doneSince === null) doneSince = Date.now();
        } else {
          doneSince = null;
        }
        const now = Date.now();
        const textQuiet = now - lastTextChangedAt >= OMA_RESPONSE_QUIET_MS;
        const doneQuiet = doneSince !== null && now - doneSince >= OMA_DONE_QUIET_MS;
        if (
          done
          && stableCount >= stableSamples
          && text
          && textQuiet
          && doneQuiet
        ) finish(true, text);
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
