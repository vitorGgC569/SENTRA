/* content-script.js — só conhece operações primitivas. Nada de OMA/Quality Gate aqui.
 * Ops: NEW_CHAT, SEND_MESSAGE, WAIT_RESPONSE, READ_RESPONSE,
 *      GET_CONVERSATION_ID, GET_CONVERSATION_URL, STOP_GENERATION, GET_STATUS,
 *      DELETE_CONVERSATION. */
"use strict";

const OMA_CS_VERSION = "1.6.3";
let omaPendingResponseBaseline = null;

async function omaWaitForComposer(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const box = omaQueryFirst(OMA_SELECTORS.composer);
    if (box && omaIsVisible(box)) return box;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("DEPENDENCY_ERROR: composer ausente (login exigido? DOM alterado?)");
}

function omaCapBanner() {
  try {
    const body = (document.body.innerText || "").slice(0, 4000).toLowerCase();
    const m = body.match(/(atingiu[^.]{0,80}limite[^.]{0,80}|limite[^.]{0,80}mensagens[^.]{0,80}|upgrade[^.]{0,60}plano[^.]{0,60}|excesso[^.]{0,80}solicita[^.]{0,80})/);
    return m ? m[0].slice(0, 160) : null;
  } catch (_) { return null; }
}

function omaComposerText(box) {
  try {
    if (box.isContentEditable) return box.innerText || "";
    return box.value || "";
  } catch (_) { return ""; }
}

async function omaClearComposer(box) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      box.focus();
      if (box.isContentEditable) {
        document.execCommand("selectAll", false, null);
        document.execCommand("delete", false, null);
        if (!omaComposerText(box).trim()) {
          box.textContent = "";
          box.dispatchEvent(new InputEvent("input", { bubbles: true }));
        }
      } else {
        box.focus();
        box.value = "";
        box.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (!omaComposerText(box).trim()) return true;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return !!box && !omaComposerText(box).trim();
}

async function omaSubmitAccepted(box, timeoutMs = 8000) {
  // Aceite = composer esvaziou OU geração começou (stop visível). Estado, não sleep.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (!omaComposerText(box).trim()) return true;
    try { if (!omaGenerationFinished()) return true; } catch (_) {}
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function omaDismissBlockingOverlay() {
  // Modais (ex. rate-limit "Excesso de solicitações", "Você já carregou este arquivo")
  // interceptam cliques no composer: detecta e dispensa se possível.
  try {
    const dialogs = [...document.querySelectorAll("[role='dialog'], [role='alertdialog'], div[class*='modal'], div[class*='dialog']")];
    for (const d of dialogs) {
      const txt = (d.innerText || "").toLowerCase();
      if (!/excesso|limite|rate|too many|slow down|aguarde|já carregou|carregou|already uploaded/i.test(txt)) continue;
      const btns = [...d.querySelectorAll("button")];
      const ok = btns.find((b) => /entendido|entendi|ok|dismiss|fechar|close/i.test(b.innerText || ""))
        || btns[0];
      if (ok) { ok.click(); return "dismissed-modal"; }
    }
  } catch (_) {}
  return null;
}

async function omaWaitAttachment(box, timeoutMs = 15000) {
  // Confirma que o anexo apareceu no composer (img, chip, preview ou botão remover).
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      omaDismissBlockingOverlay();
      const scope = box.closest("form") || (box.parentElement && box.parentElement.parentElement) || document;
      if (scope.querySelectorAll("img").length > 0) return true;
      const hasAttachment = [...scope.querySelectorAll("button, [data-testid], [class*='thumbnail'], [class*='preview'], [class*='file']")].some((el) => {
        const testId = el.getAttribute("data-testid") || "";
        const aria = el.getAttribute("aria-label") || "";
        const cls = String(el.className || "");
        return /attach|file|image|preview|upload|remover|remove/i.test(testId + " " + aria + " " + cls);
      });
      if (hasAttachment) return true;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 400));
  }
  return false;
}

function omaFindFileInputs(box) {
  // Inputs file escondidos junto ao composer são o vetor mais confiável:
  // atribuir File via DataTransfer não depende de permissão de clipboard.
  const inputs = [...document.querySelectorAll("input[type='file']")];
  const near = [];
  const far = [];
  for (const input of inputs) {
    try {
      const accept = (input.getAttribute("accept") || "").toLowerCase();
      if (/image/.test(accept)) { near.unshift(input); continue; }
      let node = input;
      let close = false;
      for (let depth = 0; node && depth < 6; depth++) {
        if (node === box || (box.contains && box.contains(node))) { close = true; break; }
        node = node.parentElement;
      }
      (close ? near : far).push(input);
    } catch (_) {}
  }
  return [...near, ...far];
}

async function omaAttachViaFileInput(box, file) {
  const inputs = omaFindFileInputs(box);
  for (const input of inputs) {
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (_) {
      continue;
    }
    if (await omaWaitAttachment(box, 12000)) return true;
    try {
      input.files = new DataTransfer().files; // limpa tentativa parcial
    } catch (_) {}
  }
  return false;
}

async function omaAttachViaDrop(box, file) {
  // Último vetor: drop sintético com NOSSO DataTransfer (sem tocar no
  // clipboard do usuário). Editores podem ignorar evento não-confiável.
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    const evt = new DragEvent("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(evt, "dataTransfer", { value: dt });
    (box.parentElement || box).dispatchEvent(evt);
  } catch (_) {
    return false;
  }
  return await omaWaitAttachment(box, 10000);
}

function omaHasAttachment(box) {
  try {
    omaDismissBlockingOverlay();
    const scope = box.closest("form") || (box.parentElement && box.parentElement.parentElement) || document;
    if (scope.querySelectorAll("img").length > 0) return true;
    const has = [...scope.querySelectorAll("button, [data-testid], [class*='thumbnail'], [class*='preview'], [class*='file']")].some((el) => {
      const testId = el.getAttribute("data-testid") || "";
      const aria = el.getAttribute("aria-label") || "";
      const cls = String(el.className || "");
      return /attach|file|image|preview|upload|remover|remove/i.test(testId + " " + aria + " " + cls);
    });
    if (has) return true;
  } catch (_) {}
  return false;
}

async function omaPasteImages(box, dataUrls) {
  // Ordem de vetores: file-input (determinístico) -> clipboard real ->
  // drop sintético. NUNCA execCommand("paste") sem antes escrever NOSSO
  // conteúdo (colaria o clipboard do usuário). Retorna quantas anexaram;
  // qualquer falha total aborta antes de qualquer envio.
  if (!dataUrls || dataUrls.length === 0) return 0;
  omaDismissBlockingOverlay();
  if (omaHasAttachment(box)) {
    return dataUrls.length; // Já anexo no composer, reutiliza sem gerar alerta de duplicata
  }
  let attached = 0;
  for (const url of (dataUrls || []).slice(0, 2)) {
    omaDismissBlockingOverlay();
    if (omaHasAttachment(box)) {
      attached++;
      continue;
    }
    if (typeof url !== "string" || !url.startsWith("data:image/")) {
      throw new Error("IMAGE_PASTE_FAILED: anexo não é data URL de imagem");
    }
    const blob = await (await fetch(url)).blob();
    const type = (blob.type && blob.type.startsWith("image/")) ? blob.type : "image/png";
    const uniqueSuffix = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const file = new File([blob], `evidence-${attached + 1}-${uniqueSuffix}.png`, { type });
    box.focus();
    let ok = await omaAttachViaFileInput(box, file);
    if (!ok) {
      try {
        await navigator.clipboard.write([new ClipboardItem({ [type]: blob })]);
        if (document.execCommand("paste")) {
          ok = await omaWaitAttachment(box, 15000);
        }
      } catch (_) {}
    }
    if (!ok) {
      ok = await omaAttachViaDrop(box, file);
    }
    if (!ok) {
      throw new Error(`IMAGE_PASTE_FAILED: imagem ${attached + 1} não apareceu no `
        + "composer (file-input, clipboard e drop falharam); nada foi enviado");
    }
    attached++;
  }
  return attached;
}

async function omaSendMessage(text, images) {
  const box = await omaWaitForComposer();
  // Composer virtualizado fora da viewport pode não montar a toolbar de envio:
  // traz para a vista + foca + acomoda antes de preencher/enviar.
  try {
    box.scrollIntoView({ block: "center" });
    box.focus();
    await new Promise((r) => setTimeout(r, 1500));
  } catch (_) {}
  const overlay = omaDismissBlockingOverlay();
  box.focus();
  // Rascunho obsoleto (SPA preserva texto entre chats!) deve ser ELIMINADO antes:
  // sem isso o modelo responde à instrução antiga anexada. Verifica VAZIO real.
  const cleared = await omaClearComposer(box);
  if (!cleared) {
    throw new Error("CLEAR_FAILED: composer manteve rascunho obsoleto após 3 tentativas");
  }
  // Evidência visual: anexa ANTES do texto (o clear acima destruiria anexos).
  // Falha aqui = job FAILED honesto, nada enviado.
  const imagesAttached = await omaPasteImages(box, images);
  // contenteditable ou textarea: preenche de forma compatível com o React.
  const fillOnce = (via) => {
    if (box.isContentEditable) {
      if (via === "exec") {
        // insertText em bloco colapsa \n simples em espaço no editor: insere
        // linha a linha com insertLineBreak para preservar a estrutura
        // (blocos de código dependem das quebras).
        document.execCommand("selectAll", false, null);
        const lines = text.split("\n");
        lines.forEach((ln, idx) => {
          if (ln) document.execCommand("insertText", false, ln);
          if (idx < lines.length - 1) document.execCommand("insertLineBreak", false, null);
        });
      } else {
        box.focus();
        box.textContent = text;
        box.dispatchEvent(new InputEvent("input", { bubbles: true }));
      }
    } else {
      box.focus();
      box.value = text;
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
  };
  fillOnce("exec");
  if (!omaComposerText(box).includes(text.slice(0, 40))) {
    fillOnce("direct"); // execCommand falhou em silêncio: tenta via alternativa
  }
  const got = omaComposerText(box);
  if (!got.includes(text.slice(0, 40))) {
    throw new Error("FILL_FAILED: composer não reteve o texto (editor o descartou?)");
  }
  // Rascunho residual faria o composer conter MUITO além do texto novo.
  if (got.length > text.length * 1.5 + 200) {
    throw new Error(`STALE_DRAFT: composer com ${got.length} chars para prompt de ` +
      `${text.length} (rascunho obsoleto presente); abortando para não contaminar`);
  }
  // Pós-fill o React re-renderiza e o botão pode sumir do DOM por um instante;
  // tentar nesse momento gera no-buttons-found espúrio. Espera a affordance.
  await omaWaitSendAffordance(15000);

  // Hidratação: em tab recém-criada o composer existe antes do app React.
  // Se nada de envio existir, espera a hidratação e tenta a 2ª rodada.
  for (let round = 0; round < 2; round++) {
    const r = await omaSubmitAttempt(box, text);
    if (r.accepted) return Object.assign({}, r, { images_attached: imagesAttached });
    if (r.hint === "no-send-affordance" && round === 0) {
      await new Promise((res) => setTimeout(res, 8000));
      continue;
    }
    throw new Error(r.error);
  }
  throw new Error("SUBMIT_FAILED:unreachable");
}

function omaNormSpace(s) {
  // SOMENTE U+00A0: é o que o editor emite para indentação. Todo outro espaço
  // exótico (U+2000+, U+3000...) falha fechado — normalizá-los mascararia
  // diferenças reais, inclusive conteúdo contrabandeado (validador lógico).
  return (s || "").replace(/ /g, " ");
}

function omaTextsMatch(actual, expected) {
  if (actual === expected) return true;
  const a = omaNormSpace(actual).replace(/\s+$/, "");
  const b = omaNormSpace(expected).replace(/\s+$/, "");
  return a === b;
}

async function omaWaitSendAffordance(timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const btns = document.querySelectorAll(
        "button[data-testid='send-button'],button[aria-label*='Send'],"
        + "button[aria-label*='Enviar'],form button[type='submit']");
      for (const b of btns) {
        if (omaIsVisible(b) && !b.disabled) return true;
      }
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false; // chamador decide: tenta mesmo assim e falha com diagnóstico
}

async function omaSubmitAttempt(box, text) {
  // Nunca envie prompt parcial/contaminado: confere o texto INTEIRO aqui,
  // não só o head. Fill truncado (ex. 1016 chars de 3.5KB) aborta alto.
  if (!omaTextsMatch(omaComposerText(box), text)) {
    const got = omaComposerText(box);
    let divAt = -1;
    const n = Math.min(got.length, text.length);
    for (let k = 0; k < n; k++) {
      if (got[k] !== text[k]) { divAt = k; break; }
    }
    if (divAt < 0) divAt = n; // prefixo comum: diferença é sufixo/tamanho
    const ctx = (s) => JSON.stringify((s || "").slice(Math.max(0, divAt - 40), divAt + 40));
    throw new Error(`PROMPT_MISMATCH: composer divergiu do prompt íntegro; envio bloqueado. `
      + `len composer=${got.length} len prompt=${text.length} diverge@${divAt} `
      + `composer=${ctx(got)} prompt=${ctx(text)}`);
  }
  const tried = [];
  const diag = () => {
    let stop = false;
    try { stop = !omaGenerationFinished(); } catch (_) {}
    const cap = omaCapBanner();
    return { stop_visible: stop, composer_len: omaComposerText(box).length,
             url: window.location.href, account_cap: cap };
  };
  // 1) Botões de envio (vários seletores: testid/aria/form).
  const buttons = [
    ...document.querySelectorAll("button[data-testid='send-button']"),
    ...document.querySelectorAll("button[aria-label*='Send']"),
    ...document.querySelectorAll("button[aria-label*='Enviar']"),
    ...document.querySelectorAll("form button[type='submit']"),
  ];
  for (const btn of buttons) {
    try {
      if (btn && omaIsVisible(btn) && !btn.disabled) {
        btn.click();
        tried.push("button");
        if (await omaSubmitAccepted(box)) return { accepted: true, method: "button" };
      } else if (btn) {
        tried.push("button-disabled-or-hidden");
      }
    } catch (_) { tried.push("button-error"); }
  }
  if (!buttons.length) tried.push("no-buttons-found");
  // 2) Submit do form (dispara onSubmit do React).
  try {
    const form = box.closest("form");
    if (form) {
      if (form.requestSubmit) {
        const b = form.querySelector("button");
        if (b) form.requestSubmit(b); else form.requestSubmit();
      } else if (form.submit) form.submit();
      tried.push("form");
      if (await omaSubmitAccepted(box)) return { accepted: true, method: "form" };
    } else {
      tried.push("no-form");
    }
  } catch (_) { tried.push("form-error"); }
  // 3) Enter (evento não-confiável: último recurso, pode ser ignorado).
  try {
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13,
      which: 13, bubbles: true, cancelable: true }));
    tried.push("enter");
    if (await omaSubmitAccepted(box)) return { accepted: true, method: "enter" };
  } catch (_) { tried.push("enter-error"); }
  const noAffordance = tried.includes("no-buttons-found") && tried.includes("no-form");
  return { accepted: false,
    hint: noAffordance ? "no-send-affordance" : "send-ignored",
    error: "SUBMIT_FAILED: composer preenchido mas envio não aceito. "
      + `tried=[${tried.join(",")}] diag=${JSON.stringify(diag())}` };
}

function omaConversationId() {
  const m = window.location.pathname.match(/\/c\/([a-f0-9-]+)/i);
  return m ? m[1] : null;
}

function omaComposerDiagnostics() {
  const describe = (node) => node ? {
    tag: node.tagName, id: node.id || null, role: node.getAttribute("role"),
    type: node.getAttribute("type"), testid: node.getAttribute("data-testid"),
    label: node.getAttribute("aria-label"), visible: omaIsVisible(node),
    editable: !!node.isContentEditable, disabled: !!node.disabled,
  } : null;
  const box = omaQueryFirst(OMA_SELECTORS.composer);
  const form = box && box.closest("form");
  return { composer: describe(box), form: describe(form),
    form_buttons: form ? [...form.querySelectorAll("button")].slice(0,20).map(describe) : [],
    composer_candidates: OMA_SELECTORS.composer.map(selector => ({selector,
      nodes: [...document.querySelectorAll(selector)].slice(0,4).map(describe)})),
    composer_len: box ? omaComposerText(box).length : 0,
    ready_state: document.readyState, visibility: document.visibilityState };
}

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  // NEW_CHAT navega a página: responde de forma síncrona ANTES de navegar,
  // senão o canal morre com o contexto JS (message channel closed).
  if (request && request.operation === "NEW_CHAT") {
    try { sendResponse({ ok: true, result: { navigating: true } }); } catch (_) {}
    setTimeout(() => { window.location.href = "https://chatgpt.com/"; }, 100);
    return false;
  }
  (async () => {
    switch (request.operation) {
      case "SEND_MESSAGE": {
        omaPendingResponseBaseline = {
          count: document.querySelectorAll(OMA_SELECTORS.assistantMessages.join(",")).length,
          text: omaLastAssistantText(),
        };
        return await omaSendMessage(request.text || "", request.images || []);
      }
      case "WAIT_RESPONSE": {
        // Fatia do SW (< 30s, ver service-worker.js): cada chamada relata os
        // pings enviados na fatia (hb_cs = prova de vida da tab). No TIMEOUT
        // o contador vai na mensagem (csping=N) para o SW acumular.
        omaStableWaitPings = 0;
        try {
          const text = await omaWaitForStableResponse(request.timeout_ms || 120000, 3, omaPendingResponseBaseline);
          return { text, hb_cs: omaStableWaitPings };
        } catch (e) {
          try { e.message = `${(e && e.message) || e} csping=${omaStableWaitPings}`; } catch (_) {}
          throw e;
        }
      }
      case "READ_RESPONSE":
        return { text: omaLastAssistantText() };
      case "GET_CONVERSATION_ID":
        return { conversation_id: omaConversationId() };
      case "GET_CONVERSATION_URL":
        return { url: window.location.href, conversation_id: omaConversationId() };
      case "STOP_GENERATION": {
        const stop = omaQueryFirst(OMA_SELECTORS.stopButton);
        if (stop) stop.click();
        return { stopped: true };
      }
      case "GET_STATUS": {
        const nodes = document.querySelectorAll(
          OMA_SELECTORS.assistantMessages.join(","));
        const capBanner = omaCapBanner();
        const sendBtns = [
          ...document.querySelectorAll("button[data-testid='send-button']"),
          ...document.querySelectorAll("button[aria-label*='Send']"),
          ...document.querySelectorAll("button[aria-label*='Enviar']"),
        ];
        const sendAvailable = !capBanner && sendBtns.some((b) => omaIsVisible(b) && !b.disabled);
        // Telemetria para distinguir cap de UI quebrada/parcial (custo zero).
        let buttonsSample = [];
        let composerFound = false;
        try {
          composerFound = !!omaQueryFirst(OMA_SELECTORS.composer);
          buttonsSample = [...document.querySelectorAll("button")]
            .slice(0, 40).map((b) => (b.getAttribute("aria-label")
              || b.getAttribute("data-testid") || (b.innerText || "").trim()).slice(0, 40))
            .filter(Boolean);
        } catch (_) {}
        const hasConv = /\/c\/[a-f0-9-]+/i.test(window.location.pathname);
        let draftEmpty = true;
        try {
          const box = omaQueryFirst(OMA_SELECTORS.composer);
          draftEmpty = !box || !omaComposerText(box).trim();
        } catch (_) { draftEmpty = false; }
        return { finished: omaGenerationFinished(), url: window.location.href,
                 cs_version: OMA_CS_VERSION, assistant_count: nodes.length,
                 is_fresh_chat: !hasConv && nodes.length === 0 && draftEmpty,
                 send_available: sendAvailable, cap_banner: capBanner,
                 composer_found: composerFound, buttons_sample: buttonsSample,
                 diagnostics: omaComposerDiagnostics() };
      }
      case "DELETE_CONVERSATION": {
        const convId = request.conversation_id || omaConversationId();
        if (!convId) throw new Error("conversation_id required");
        let deleted = false;
        let details = null;
        try {
          const sessionResp = await fetch("/api/auth/session", { credentials: "same-origin" });
          if (sessionResp.ok) {
            const sessionData = await sessionResp.json();
            const token = sessionData && sessionData.accessToken;
            if (token) {
              const patchResp = await fetch(`/backend-api/conversation/${convId}`, {
                method: "PATCH",
                credentials: "same-origin",
                headers: {
                  "Authorization": `Bearer ${token}`,
                  "Content-Type": "application/json",
                },
                body: JSON.stringify({ is_visible: false }),
              });
              if (patchResp.ok) {
                deleted = true;
                details = "api_patch_success";
              } else {
                details = `api_patch_failed_${patchResp.status}`;
              }
            } else {
              details = "no_access_token";
            }
          } else {
            details = `session_failed_${sessionResp.status}`;
          }
        } catch (e) {
          details = "api_patch_error: " + String((e && e.message) || e);
        }
        return { deleted, conversation_id: convId, details };
      }
      case "NEW_CHAT":
        window.location.href = "https://chatgpt.com/";
        return { navigating: true };
      default:
        throw new Error(`UNKNOWN_OPERATION: ${request.operation}`);
    }
  })()
    .then((result) => sendResponse({ ok: true, result }))
    .catch((e) => sendResponse({ ok: false, error: String((e && e.message) || e) }));
  return true; // resposta assíncrona
});
