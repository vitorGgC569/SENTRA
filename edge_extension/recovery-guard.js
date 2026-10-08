(() => {
  "use strict";
  if (window.location.hostname !== "chatgpt.com") return;

  const VERSION = "1.6.52";
  const KEY = "__SENTRA_RECOVERY_GUARD__";
  const previous = globalThis[KEY];
  if (previous && previous.version === VERSION) return;
  try { if (previous && typeof previous.cleanup === "function") previous.cleanup(); } catch (_) {}

  const state = {
    version: VERSION,
    busy: false,
    attempted: false,
    baselineCount: -1,
    observer: null,
    timer: 0,
    cleanup: null,
  };
  globalThis[KEY] = state;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const fold = (text) => String(text || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

  const visible = (el) => {
    if (!el) return false;
    try {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    } catch (_) { return false; }
  };

  const composer = () => (
    document.querySelector("#prompt-textarea")
    || document.querySelector('textarea[data-testid="chat-input"]')
    || document.querySelector('[role="textbox"][contenteditable="true"]')
    || document.querySelector('[contenteditable="true"]')
  );

  const composerText = (box) => {
    try {
      return String(box && (box.isContentEditable ? box.innerText : box.value) || "");
    } catch (_) { return ""; }
  };

  const stopButton = () => {
    const selectors = [
      "button[data-testid='stop-button']",
      "button[aria-label='Stop generating']",
      "button[aria-label*='Interromper']",
      "button[aria-label*='Parar']",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (visible(el)) return el;
    }
    return null;
  };

  const sendButton = () => {
    const selectors = [
      "button[data-testid='send-button']",
      "button[aria-label*='Send']",
      "button[aria-label*='Enviar']",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (visible(el) && !el.disabled && el.getAttribute("aria-disabled") !== "true") return el;
    }
    return null;
  };

  const isWarning = (text) => {
    const s = fold(text);
    const pt = (
      (
        s.includes("verificacoes adicionais")
        || s.includes("mais algumas verificacoes")
        || (
          s.includes("nossos sistemas")
          && s.includes("verificacoes")
          && s.includes("solicitacao")
        )
      )
      && (
        s.includes("antes de responder")
        || s.includes("antes de fornecer uma resposta")
      )
    );
    const en = s.includes("additional checks")
      && (s.includes("before responding") || s.includes("before we respond"));
    return pt || en;
  };

  const findWarning = () => {
    try {
      const box = composer();
      const seen = new Set();
      const candidates = [];
      const add = (node) => {
        if (!node || seen.has(node)) return;
        seen.add(node);
        candidates.push(node);
      };
      document.querySelectorAll(
        "[role='alert'],[role='status'],[aria-live],[data-message-author-role='system'],main p,main div"
      ).forEach(add);
      const walker = document.createTreeWalker(
        document.body || document.documentElement,
        NodeFilter.SHOW_TEXT
      );
      let node = null;
      let scanned = 0;
      while ((node = walker.nextNode()) && scanned < 1200) {
        scanned++;
        const raw = String(node.nodeValue || "").trim();
        if (!raw) continue;
        const s = fold(raw);
        if (!s.includes("verific") && !s.includes("additional")) continue;
        let parent = node.parentElement;
        for (let depth = 0; parent && depth < 6; depth++, parent = parent.parentElement) add(parent);
      }
      let best = null;
      for (const el of candidates) {
        if (!visible(el)) continue;
        if (el.closest("[data-message-author-role='user']")) continue;
        if (el.closest("[data-message-author-role='assistant']")) continue;
        if (box && (el === box || box.contains(el) || el.contains(box))) continue;
        const text = String(el.innerText || el.textContent || "").trim();
        if (!text || text.length > 2600 || !isWarning(text)) continue;
        if (!best || text.length < best.length) best = text;
      }
      return best;
    } catch (_) { return null; }
  };

  const assistantCount = () => {
    try { return document.querySelectorAll("[data-message-author-role='assistant']").length; }
    catch (_) { return 0; }
  };

  const generationFinished = () => !stopButton();

  async function waitComposerReady(timeoutMs = 45000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const box = composer();
      if (
        box && visible(box)
        && box.getAttribute("aria-disabled") !== "true"
        && !composerText(box).trim()
        && generationFinished()
      ) return box;
      await sleep(250);
    }
    throw new Error("RECOVERY_GUARD_COMPOSER_TIMEOUT");
  }

  async function sendContinue(box) {
    box.focus();
    if (box.isContentEditable) {
      document.execCommand("selectAll", false, null);
      document.execCommand("delete", false, null);
      document.execCommand("insertText", false, "Continue");
      box.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: "Continue" }));
    } else {
      box.value = "Continue";
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
    await sleep(250);
    if (!composerText(box).includes("Continue")) throw new Error("RECOVERY_GUARD_FILL_FAILED");

    const sendDeadline = Date.now() + 15000;
    let button = null;
    while (Date.now() < sendDeadline) {
      button = sendButton();
      if (button) break;
      await sleep(250);
    }
    if (!button) throw new Error("RECOVERY_GUARD_SEND_BUTTON_MISSING");
    button.click();

    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      if (!composerText(box).trim() || !generationFinished()) return true;
      await sleep(200);
    }
    throw new Error("RECOVERY_GUARD_SUBMIT_NOT_ACCEPTED");
  }

  async function scan() {
    if (state.busy) return;
    const warning = findWarning();

    if (!warning) {
      if (state.attempted && state.baselineCount >= 0 && assistantCount() > state.baselineCount) {
        state.attempted = false;
        state.baselineCount = -1;
      }
      return;
    }

    if (state.attempted) return;

    const box = composer();
    if (box && composerText(box).trim()) return;

    state.busy = true;
    state.attempted = true;
    try {
      const stop = stopButton();
      if (stop) stop.click();

      const stopDeadline = Date.now() + 6000;
      while (Date.now() < stopDeadline && !generationFinished()) await sleep(100);
      if (!generationFinished()) throw new Error("RECOVERY_GUARD_STOP_TIMEOUT");

      const ready = await waitComposerReady();
      await sleep(3000);
      if (!generationFinished() || composerText(ready).trim()) {
        throw new Error("RECOVERY_GUARD_NOT_SAFE_TO_RESUME");
      }

      state.baselineCount = assistantCount();
      await sendContinue(ready);
      try {
        chrome.runtime.sendMessage({ operation: "OMA_ADDITIONAL_CHECKS_RECOVERED", source: "recovery-guard" });
      } catch (_) {}
    } catch (error) {
      try {
        chrome.runtime.sendMessage({
          operation: "OMA_ADDITIONAL_CHECKS_RECOVERY_FAILED",
          source: "recovery-guard",
          error: String((error && error.message) || error).slice(0, 300),
        });
      } catch (_) {}
    } finally {
      state.busy = false;
    }
  }

  const schedule = () => { setTimeout(() => { void scan(); }, 100); };
  state.observer = new MutationObserver(schedule);
  state.observer.observe(document.documentElement || document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  state.timer = setInterval(() => { void scan(); }, 1000);
  state.cleanup = () => {
    try { state.observer.disconnect(); } catch (_) {}
    try { clearInterval(state.timer); } catch (_) {}
  };

  chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
    if (!request || request.operation !== "SENTRA_RECOVERY_GUARD_STATUS") return false;
    sendResponse({
      ok: true,
      version: VERSION,
      busy: state.busy,
      attempted: state.attempted,
      baseline_count: state.baselineCount,
    });
    return false;
  });

  void scan();
})();