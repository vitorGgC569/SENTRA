/* content-script.js ÔÇö s├│ conhece opera├º├Áes primitivas. Nada de OMA/Quality Gate aqui.
 * Ops: NEW_CHAT, SEND_MESSAGE, WAIT_RESPONSE, READ_RESPONSE,
 *      GET_CONVERSATION_ID, GET_CONVERSATION_URL, STOP_GENERATION, GET_STATUS,
 *      DELETE_CONVERSATION. */
"use strict";

const OMA_CS_VERSION = "1.6.52";
const OMA_BUILD_ID = chrome.runtime.getManifest().sentra_build_id || "missing-build-id";
const OMA_SOURCE_HASH = chrome.runtime.getManifest().sentra_source_hash || "missing-source-hash";
let omaPendingResponseBaseline = null;

function omaProvider() {
  return window.location.hostname === "gemini.google.com" ? "gemini" : "chatgpt";
}

function omaHomeUrl() {
  return omaProvider() === "gemini"
    ? "https://gemini.google.com/app"
    : "https://chatgpt.com/";
}

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
  // Scope rate-limit detection to transient UI. The normal ChatGPT navigation
  // contains "Upgrade" / "Ver planos", which is not a usage cap.
  try {
    const candidates = [
      ...document.querySelectorAll(
        "[role='alert'],[role='alertdialog'],[role='status'],"
        + "[aria-live],div[data-state='open']"
      ),
    ];
    for (const node of candidates) {
      if (!node || !omaIsVisible(node)) continue;
      const text = omaFoldUiText(node.innerText || node.textContent || "");
      if (!text || text.length > 1200) continue;
      if (
        /atingiu.{0,100}limite/.test(text)
        || /limite.{0,100}mensagens/.test(text)
        || /excesso.{0,100}solicita/.test(text)
        || /too many requests/.test(text)
        || /rate limit/.test(text)
        || /message limit/.test(text)
      ) return text.slice(0, 160);
    }
    return null;
  } catch (_) { return null; }
}

const OMA_MAX_ADDITIONAL_CHECK_RECOVERIES = 1;
const OMA_ADDITIONAL_CHECKS_CLEAR_TIMEOUT_MS = 45000;
const OMA_ADDITIONAL_CHECKS_RESUME_COOLDOWN_MS = 3000;

function omaFoldUiText(text) {
  return String(text || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function omaIsAdditionalChecksMessage(text) {
  const folded = omaFoldUiText(text);
  const additionalChecksPt = (
    (
      folded.includes("verificacoes adicionais")
      || folded.includes("mais algumas verificacoes")
      || (
        folded.includes("nossos sistemas")
        && folded.includes("verificacoes")
        && folded.includes("solicitacao")
      )
    )
    && (
      folded.includes("antes de responder")
      || folded.includes("antes de fornecer uma resposta")
    )
  );
  const additionalChecksEn = (
    folded.includes("additional checks")
    && (
      folded.includes("before responding")
      || folded.includes("before we respond")
    )
  );
  const unusualActivity = (
    (
      folded.includes("atividade incomum")
      || folded.includes("atividade suspeita")
      || folded.includes("unusual activity")
      || folded.includes("suspicious activity")
    )
    && (
      folded.includes("sistema")
      || folded.includes("systems")
      || folded.includes("request")
      || folded.includes("solicitacao")
    )
  );
  return additionalChecksPt || additionalChecksEn || unusualActivity;
}

function omaFindAdditionalChecksBannerText(includeAssistantFallback = true) {
  // ChatGPT currently renders this warning as transient system UI and may split
  // the sentence across several nested spans. Search both semantic containers
  // and text-node ancestors while excluding user messages/composer content.
  try {
    const composer = omaQueryFirst(OMA_SELECTORS.composer);
    const seen = new Set();
    const candidates = [];
    const addCandidate = (node) => {
      if (!node || seen.has(node)) return;
      seen.add(node);
      candidates.push(node);
    };

    document.querySelectorAll(
      "[role='alert'],[role='status'],[aria-live],"
      + "[data-message-author-role='system'],main p,main div"
    ).forEach(addCandidate);

    // Some builds use anonymous div/span wrappers with no useful role. Walk a
    // bounded number of visible text nodes and test their ancestors so a banner
    // whose sentence is split across spans is still detected.
    const walker = document.createTreeWalker(
      document.body || document.documentElement,
      NodeFilter.SHOW_TEXT
    );
    let textNode = null;
    let scanned = 0;
    while ((textNode = walker.nextNode()) && scanned < 1200) {
      scanned++;
      const raw = String(textNode.nodeValue || "").trim();
      if (!raw) continue;
      const folded = omaFoldUiText(raw);
      if (
        !folded.includes("verific")
        && !folded.includes("additional")
        && !folded.includes("atividade")
        && !folded.includes("activity")
      ) continue;
      let node = textNode.parentElement;
      for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
        addCandidate(node);
      }
    }

    let best = null;
    for (const node of candidates) {
      if (!node || !omaIsVisible(node)) continue;
      if (node.closest("[data-message-author-role='user']")) continue;
      if (node.closest("[data-message-author-role='assistant']")) continue;
      if (composer && (node === composer || composer.contains(node) || node.contains(composer))) continue;
      const text = String(node.innerText || node.textContent || "").trim();
      if (!text || text.length > 2600 || !omaIsAdditionalChecksMessage(text)) continue;
      if (!best || text.length < best.length) best = text;
    }

    // Final fallback for UI variants that render the notice as an assistant-like
    // bubble instead of system chrome.
    if (includeAssistantFallback) {
      const latest = typeof omaLastAssistantText === "function" ? omaLastAssistantText() : "";
      if (latest && omaIsAdditionalChecksMessage(latest)) {
        if (!best || latest.length < best.length) best = latest;
      }
    }
    return best;
  } catch (_) {
    return null;
  }
}

async function omaStopGenerationForRecovery(timeoutMs = 6000) {
  try {
    const stop = omaQueryFirst(OMA_SELECTORS.stopButton);
    if (stop && omaIsVisible(stop)) stop.click();
  } catch (e) {
    throw new Error(`ADDITIONAL_CHECKS_STOP_FAILED: ${String((e && e.message) || e)}`);
  }
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try { if (omaGenerationFinished()) return true; } catch (_) {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("ADDITIONAL_CHECKS_STOP_FAILED: gera├º├úo n├úo encerrou ap├│s clicar em Parar");
}

let omaAdditionalChecksRecoveryPromise = null;
let omaAdditionalChecksRecoveryKey = null;
let omaAdditionalChecksRecoveryAttempts = 0;
let omaAdditionalChecksRecoveryBaselineCount = -1;

function omaAdditionalChecksConversationKey() {
  return omaConversationId() || window.location.pathname || "chatgpt-root";
}

function omaMaybeResetAdditionalChecksRecoveryCycle() {
  if (omaAdditionalChecksRecoveryAttempts < 1 || omaAdditionalChecksRecoveryBaselineCount < 0) return;
  try {
    const latest = omaLastAssistantText();
    if (
      omaAssistantMessageCount() > omaAdditionalChecksRecoveryBaselineCount
      && latest
      && !omaIsAdditionalChecksMessage(latest)
      && !omaFindAdditionalChecksBannerText(false)
    ) {
      omaAdditionalChecksRecoveryAttempts = 0;
      omaAdditionalChecksRecoveryBaselineCount = -1;
    }
  } catch (_) {}
}

async function omaWaitAdditionalChecksCleared(
  timeoutMs = OMA_ADDITIONAL_CHECKS_CLEAR_TIMEOUT_MS
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let finished = false;
    try { finished = omaGenerationFinished(); } catch (_) {}
    const composer = omaQueryFirst(OMA_SELECTORS.composer);
    const composerReady = !!(
      composer
      && omaIsVisible(composer)
      && composer.getAttribute("aria-disabled") !== "true"
      && !omaComposerText(composer).trim()
    );
    if (finished && composerReady) {
      await new Promise((resolve) => setTimeout(resolve, OMA_ADDITIONAL_CHECKS_RESUME_COOLDOWN_MS));
      if (omaGenerationFinished() && !omaComposerText(composer).trim()) return composer;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("ADDITIONAL_CHECKS_RESUME_TIMEOUT: composer nao ficou pronto apos interromper");
}

async function omaRecoverAdditionalChecks() {
  // WAIT_RESPONSE and the global UI watcher can observe the same banner on the
  // same mutation. Collapse both into one stop -> Continue transaction.
  if (omaAdditionalChecksRecoveryPromise) return omaAdditionalChecksRecoveryPromise;
  const key = omaAdditionalChecksConversationKey();
  if (key !== omaAdditionalChecksRecoveryKey) {
    omaAdditionalChecksRecoveryKey = key;
    omaAdditionalChecksRecoveryAttempts = 0;
  }
  if (omaAdditionalChecksRecoveryAttempts >= OMA_MAX_ADDITIONAL_CHECK_RECOVERIES) {
    throw new Error("ADDITIONAL_CHECKS_LOOP: recovery limit reached for this conversation");
  }
  omaAdditionalChecksRecoveryAttempts++;
  omaAdditionalChecksRecoveryPromise = (async () => {
    await omaStopGenerationForRecovery();
    await omaWaitAdditionalChecksCleared();
    // "Continue" starts a new assistant turn. Reset the response baseline after
    // the transient warning has fully cleared so WAIT_RESPONSE cannot mistake
    // the interrupted turn for the recovered one.
    omaAdditionalChecksRecoveryBaselineCount = omaAssistantMessageCount();
    omaPendingResponseBaseline = {
      count: omaAdditionalChecksRecoveryBaselineCount,
      text: omaLastAssistantText(),
    };
    await omaSendMessage("Continue", []);
    return true;
  })();
  try {
    return await omaAdditionalChecksRecoveryPromise;
  } finally {
    omaAdditionalChecksRecoveryPromise = null;
  }
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
  // Aceite = composer esvaziou OU gera├º├úo come├ºou (stop vis├¡vel). Estado, n├úo sleep.
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (!omaComposerText(box).trim()) return true;
    try { if (!omaGenerationFinished()) return true; } catch (_) {}
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function omaDismissBlockingOverlay() {
  // Modais (ex. rate-limit "Excesso de solicita├º├Áes", "Voc├¬ j├í carregou este arquivo")
  // interceptam cliques no composer: detecta e dispensa se poss├¡vel.
  try {
    const dialogs = [...document.querySelectorAll("[role='dialog'], [role='alertdialog'], div[class*='modal'], div[class*='dialog'], div[data-state='open']")];
    for (const d of dialogs) {
      const txt = (d.innerText || "").toLowerCase();
      if (!/excesso|limite|rate|too many|slow down|aguarde|j├í carregou|carregou|already uploaded|experimente carregar/i.test(txt)) continue;
      const btns = [...d.querySelectorAll("button, [role='button']")];
      const ok = btns.find((b) => /entendido|entendi|ok|dismiss|fechar|close/i.test((b.innerText || b.textContent || "").trim()))
        || btns[0];
      if (ok) { ok.click(); return "dismissed-modal"; }
    }
    // Fallback: se houver bot├úo "OK" expl├¡cito e na tela tiver aviso de duplicata
    const bodyText = (document.body.innerText || "").slice(0, 5000).toLowerCase();
    if (/j├í carregou este arquivo|experimente carregar algo novo/i.test(bodyText)) {
      const allBtns = [...document.querySelectorAll("button")];
      const okBtn = allBtns.find((b) => /^(ok|entendi|entendido)$/i.test((b.innerText || "").trim()));
      if (okBtn) { okBtn.click(); return "dismissed-duplicate-modal"; }
    }
  } catch (_) {}
  return null;
}

async function omaWaitAttachment(box, timeoutMs = 15000) {
  // Confirma que o anexo apareceu no composer (img, chip, preview ou bot├úo remover).
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
  // Inputs file escondidos junto ao composer s├úo o vetor mais confi├ível:
  // atribuir File via DataTransfer n├úo depende de permiss├úo de clipboard.
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
  // ├Ültimo vetor: drop sint├®tico com NOSSO DataTransfer (sem tocar no
  // clipboard do usu├írio). Editores podem ignorar evento n├úo-confi├ível.
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
    if (scope.querySelectorAll("[style*='background-image']").length > 0) return true;
    const elements = [...scope.querySelectorAll("button, [data-testid], [class*='thumbnail'], [class*='preview'], [class*='file'], [class*='rounded']")];
    const has = elements.some((el) => {
      const testId = el.getAttribute("data-testid") || "";
      const aria = el.getAttribute("aria-label") || "";
      const cls = String(el.className || "");
      const txt = (el.innerText || el.textContent || "").toLowerCase();
      return /attach|file|image|preview|upload|remover|remove/i.test(testId + " " + aria + " " + cls)
        || /remover|remove/.test(txt);
    });
    if (has) return true;
  } catch (_) {}
  return false;
}

async function omaPasteImages(box, dataUrls) {
  // Ordem de vetores: file-input (determin├¡stico) -> clipboard real ->
  // drop sint├®tico. NUNCA execCommand("paste") sem antes escrever NOSSO
  // conte├║do (colaria o clipboard do usu├írio). Retorna quantas anexaram;
  // qualquer falha total aborta antes de qualquer envio.
  if (!dataUrls || dataUrls.length === 0) return 0;
  omaDismissBlockingOverlay();
  if (omaHasAttachment(box)) {
    return dataUrls.length; // J├í anexo no composer, reutiliza sem gerar alerta de duplicata
  }
  let attached = 0;
  for (const url of (dataUrls || []).slice(0, 2)) {
    omaDismissBlockingOverlay();
    if (omaHasAttachment(box)) {
      attached++;
      continue;
    }
    if (typeof url !== "string" || !url.startsWith("data:image/")) {
      throw new Error("IMAGE_PASTE_FAILED: anexo n├úo ├® data URL de imagem");
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
      throw new Error(`IMAGE_PASTE_FAILED: imagem ${attached + 1} n├úo apareceu no `
        + "composer (file-input, clipboard e drop falharam); nada foi enviado");
    }
    attached++;
  }
  return attached;
}

async function omaSendMessage(text, images) {
  const box = await omaWaitForComposer();
  // Composer virtualizado fora da viewport pode n├úo montar a toolbar de envio:
  // traz para a vista + foca + acomoda antes de preencher/enviar.
  try {
    box.scrollIntoView({ block: "center" });
    box.focus();
    await new Promise((r) => setTimeout(r, 1500));
  } catch (_) {}
  const overlay = omaDismissBlockingOverlay();
  box.focus();
  // Rascunho obsoleto (SPA preserva texto entre chats!) deve ser ELIMINADO antes:
  // sem isso o modelo responde ├á instru├º├úo antiga anexada. Verifica VAZIO real.
  const cleared = await omaClearComposer(box);
  if (!cleared) {
    throw new Error("CLEAR_FAILED: composer manteve rascunho obsoleto ap├│s 3 tentativas");
  }
  // Evid├¬ncia visual: anexa ANTES do texto (o clear acima destruiria anexos).
  // Falha aqui = job FAILED honesto, nada enviado.
  const imagesAttached = await omaPasteImages(box, images);
  // contenteditable ou textarea: preenche de forma compat├¡vel com o React.
  const fillOnce = (via) => {
    if (box.isContentEditable) {
      if (via === "exec") {
        // insertText em bloco colapsa \n simples em espa├ºo no editor: insere
        // linha a linha com insertLineBreak para preservar a estrutura
        // (blocos de c├│digo dependem das quebras).
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
    fillOnce("direct"); // execCommand falhou em sil├¬ncio: tenta via alternativa
  }
  const got = omaComposerText(box);
  if (!got.includes(text.slice(0, 40))) {
    throw new Error("FILL_FAILED: composer n├úo reteve o texto (editor o descartou?)");
  }
  // Rascunho residual faria o composer conter MUITO al├®m do texto novo.
  if (got.length > text.length * 1.5 + 200) {
    throw new Error(`STALE_DRAFT: composer com ${got.length} chars para prompt de ` +
      `${text.length} (rascunho obsoleto presente); abortando para n├úo contaminar`);
  }
  // P├│s-fill o React re-renderiza e o bot├úo pode sumir do DOM por um instante;
  // tentar nesse momento gera no-buttons-found esp├║rio. Espera a affordance.
  await omaWaitSendAffordance(15000);

  // Hidrata├º├úo: em tab rec├®m-criada o composer existe antes do app React.
  // Se nada de envio existir, espera a hidrata├º├úo e tenta a 2┬¬ rodada.
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
  // SOMENTE U+00A0: ├® o que o editor emite para indenta├º├úo. Todo outro espa├ºo
  // ex├│tico (U+2000+, U+3000...) falha fechado ÔÇö normaliz├í-los mascararia
  // diferen├ºas reais, inclusive conte├║do contrabandeado (validador l├│gico).
  return (s || "").replace(/┬á/g, " ");
}

function omaTextsMatch(actual, expected) {
  if (actual === expected) return true;
  const a = omaNormSpace(actual).replace(/\s+$/, "");
  const b = omaNormSpace(expected).replace(/\s+$/, "");
  if (a === b) return true;

  // Rich web editors may rewrite line breaks/indentation while preserving the
  // exact non-whitespace character stream. Accept only that narrow class of
  // DOM normalization; inserted/removed/reordered non-whitespace still fails
  // closed and triggers PROMPT_MISMATCH. Whitespace position itself is not
  // trusted because contenteditable may synthesize block-boundary newlines.
  const nonWhitespace = (value) => value.replace(/\s+/g, "");
  return nonWhitespace(a) === nonWhitespace(b);
}

async function omaWaitSendAffordance(timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const btns = document.querySelectorAll(
        OMA_SELECTORS.sendButton.join(",") + ",form button[type='submit']"
      );
      for (const b of btns) {
        if (omaIsVisible(b) && !b.disabled) return true;
      }
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return false; // chamador decide: tenta mesmo assim e falha com diagn├│stico
}

async function omaSubmitAttempt(box, text) {
  // Nunca envie prompt parcial/contaminado: confere o texto INTEIRO aqui,
  // n├úo s├│ o head. Fill truncado (ex. 1016 chars de 3.5KB) aborta alto.
  if (!omaTextsMatch(omaComposerText(box), text)) {
    const got = omaComposerText(box);
    let divAt = -1;
    const n = Math.min(got.length, text.length);
    for (let k = 0; k < n; k++) {
      if (got[k] !== text[k]) { divAt = k; break; }
    }
    if (divAt < 0) divAt = n; // prefixo comum: diferen├ºa ├® sufixo/tamanho
    const ctx = (s) => JSON.stringify((s || "").slice(Math.max(0, divAt - 40), divAt + 40));
    throw new Error(`PROMPT_MISMATCH: composer divergiu do prompt ├¡ntegro; envio bloqueado. `
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
  // 1) Bot├Áes de envio (v├írios seletores: testid/aria/form).
  const buttons = [
    ...document.querySelectorAll(OMA_SELECTORS.sendButton.join(",")),
    ...document.querySelectorAll("form button[type='submit']"),
  ];
  for (const btn of buttons) {
    try {
      if (btn && omaIsVisible(btn) && !btn.disabled) {
        btn.click();
        tried.push("button");
        if (await omaSubmitAccepted(box)) return { accepted: true, method: "button" };

        // Gemini/Angular can ignore HTMLElement.click() on a background tab
        // even though the Material send button is visible and enabled. Only
        // retry while the exact draft is still present, so an accepted but
        // delayed first click can never be duplicated.
        if (
          omaProvider() === "gemini"
          && omaTextsMatch(omaComposerText(box), text)
        ) {
          try {
            box.focus();
            box.dispatchEvent(new InputEvent("input", {
              bubbles: true,
              inputType: "insertText",
              data: null,
            }));
            await new Promise((resolve) => setTimeout(resolve, 120));
            if (!omaTextsMatch(omaComposerText(box), text)) {
              throw new Error("draft changed during Gemini submit resync");
            }

            const rect = btn.getBoundingClientRect();
            const clientX = rect.left + rect.width / 2;
            const clientY = rect.top + rect.height / 2;
            try { btn.focus({ preventScroll: true }); } catch (_) { try { btn.focus(); } catch (_) {} }
            const pointer = (type, buttons) => btn.dispatchEvent(new PointerEvent(type, {
              bubbles: true,
              cancelable: true,
              composed: true,
              pointerId: 1,
              pointerType: "mouse",
              isPrimary: true,
              button: 0,
              buttons,
              clientX,
              clientY,
            }));
            const mouse = (type, buttons) => btn.dispatchEvent(new MouseEvent(type, {
              bubbles: true,
              cancelable: true,
              composed: true,
              button: 0,
              buttons,
              clientX,
              clientY,
              view: window,
            }));
            pointer("pointerdown", 1);
            mouse("mousedown", 1);
            pointer("pointerup", 0);
            mouse("mouseup", 0);
            mouse("click", 0);
            tried.push("pointer-sequence");
            if (await omaSubmitAccepted(box)) {
              return { accepted: true, method: "pointer-sequence" };
            }
          } catch (_) {
            tried.push("pointer-sequence-error");
          }
        }
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
  // 3) Enter (evento n├úo-confi├ível: ├║ltimo recurso, pode ser ignorado).
  try {
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13,
      which: 13, bubbles: true, cancelable: true }));
    tried.push("enter");
    if (await omaSubmitAccepted(box)) return { accepted: true, method: "enter" };
  } catch (_) { tried.push("enter-error"); }
  const noAffordance = tried.includes("no-buttons-found") && tried.includes("no-form");
  return { accepted: false,
    hint: noAffordance ? "no-send-affordance" : "send-ignored",
    error: "SUBMIT_FAILED: composer preenchido mas envio n├úo aceito. "
      + `tried=[${tried.join(",")}] diag=${JSON.stringify(diag())}` };
}

function omaConversationId() {
  const path = window.location.pathname || "";
  if (omaProvider() === "gemini") {
    const m = path.match(/^\/app\/([A-Za-z0-9_-]{1,256})(?:\/|$)/);
    return m ? m[1] : null;
  }
  const m = path.match(/\/c\/([A-Za-z0-9-]+)/i);
  return m ? m[1] : null;
}

function omaGeminiModelLabel(model) {
  const normalized = String(model || "").trim().toLowerCase();
  if (normalized === "flash-lite") return "Flash-Lite";
  if (normalized === "flash") return "Flash";
  if (normalized === "pro") return "Pro";
  throw new Error("MODEL_SELECTION_FAILED: unsupported Gemini model");
}

function omaVisibleText(node) {
  if (!node || !omaIsVisible(node)) return "";
  return String(
    node.innerText || node.textContent || node.getAttribute("aria-label") || ""
  ).replace(/\s+/g, " ").trim();
}

function omaGeminiModelIdFromText(text) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  if (/\bflash[- ]?lite\b/i.test(value)) return "flash-lite";
  if (/\bflash\b/i.test(value)) return "flash";
  if (/\bpro\b/i.test(value)) return "pro";
  return null;
}

function omaGeminiNearbyModelLabel(composer) {
  if (!composer) return null;
  const composerRect = composer.getBoundingClientRect();
  const scopes = [];
  let scope = composer.parentElement;
  for (let depth = 0; scope && depth < 7; depth++, scope = scope.parentElement) {
    scopes.push(scope);
  }
  const seen = new Set();
  const acceptCandidate = (candidate) => {
    if (!candidate || seen.has(candidate) || !omaIsVisible(candidate)) return null;
    seen.add(candidate);
    if (candidate.children.length > 6) return null;
    const text = omaVisibleText(candidate);
    if (!text || text.length > 80) return null;
    const model = omaGeminiModelIdFromText(text);
    if (!model) return null;
    const rect = candidate.getBoundingClientRect();
    const verticalGap = Math.max(
      0,
      rect.top - composerRect.bottom,
      composerRect.top - rect.bottom,
    );
    const horizontalGap = Math.max(
      0,
      rect.left - composerRect.right,
      composerRect.left - rect.right,
    );
    if (
      verticalGap <= 320
      && horizontalGap <= Math.max(480, window.innerWidth * 0.35)
    ) {
      return { model, node: candidate };
    }
    return null;
  };

  for (const root of scopes) {
    let scanned = 0;
    for (const candidate of root.querySelectorAll("*")) {
      if (++scanned > 900) break;
      const accepted = acceptCandidate(candidate);
      if (accepted) return accepted;
    }
  }

  // Gemini may render the model switcher outside the rich-textarea ancestor
  // tree (for example in a sibling/custom-element footer). Scan text nodes in
  // the whole light DOM, but still accept only a compact model label close to
  // the composer. This avoids binding to sidebar/history occurrences.
  if (document.body && typeof NodeFilter !== "undefined") {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let current = walker.nextNode();
    let scannedText = 0;
    while (current && scannedText < 6000) {
      scannedText++;
      const raw = String(current.nodeValue || "").replace(/\s+/g, " ").trim();
      if (raw && raw.length <= 80 && omaGeminiModelIdFromText(raw)) {
        const accepted = acceptCandidate(current.parentElement);
        if (accepted) return accepted;
      }
      current = walker.nextNode();
    }
  }
  return null;
}

function omaGeminiCurrentModel() {
  if (omaProvider() !== "gemini") return null;
  const composer = omaQueryFirst(OMA_SELECTORS.composer);
  const scopes = [];
  if (composer) {
    let node = composer;
    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
      scopes.push(node);
    }
  }
  scopes.push(document);
  for (const scope of scopes) {
    const nodes = scope.querySelectorAll(
      "button,[role='button'][aria-haspopup],"
      + "[aria-label*='model' i],[mattooltip*='model' i],"
      + "[aria-label*='seletor de modo' i],[aria-label*='mode selector' i]"
    );
    for (const node of nodes) {
      if (!omaIsVisible(node)) continue;
      const text = omaVisibleText(node);
      const aria = String(node.getAttribute("aria-label") || "");
      const combined = (text + " " + aria).replace(/\s+/g, " ").trim();
      if (!combined || combined.length > 260) continue;
      const model = omaGeminiModelIdFromText(combined);
      if (model) return model;
    }
  }
  // Gemini currently renders the selected model label in a custom wrapper that
  // may have no button/role/aria-haspopup semantics. Restrict the fallback to
  // compact visible text geometrically adjacent to the composer.
  const nearby = omaGeminiNearbyModelLabel(composer);
  return nearby ? nearby.model : null;
}

async function omaSetGeminiModel(model, timeoutMs = 12000) {
  if (omaProvider() !== "gemini") {
    throw new Error("MODEL_SELECTION_FAILED: current site is not Gemini");
  }
  const target = String(model || "").trim().toLowerCase();
  const targetLabel = omaGeminiModelLabel(target);
  if (omaGeminiCurrentModel() === target) {
    return { selected: true, model: target, unchanged: true };
  }
  const composer = await omaWaitForComposer(timeoutMs);
  const deadline = Date.now() + timeoutMs;
  let toggle = null;
  while (Date.now() < deadline && !toggle) {
    if (omaGeminiCurrentModel() === target) {
      return { selected: true, model: target, unchanged: true };
    }
    const scopes = [];
    let node = composer;
    for (let depth = 0; node && depth < 7; depth++, node = node.parentElement) {
      scopes.push(node);
    }
    scopes.push(document);
    for (const scope of scopes) {
      const candidates = scope.querySelectorAll(
        "button,[role='button'][aria-haspopup='menu'],[role='button'][aria-haspopup='listbox'],[aria-haspopup='true']"
      );
      for (const candidate of candidates) {
        const text = omaVisibleText(candidate);
        const aria = String(candidate.getAttribute("aria-label") || "");
        const combined = `${text} ${aria}`;
        if (
          combined.length <= 240
          && (
            /flash[- ]?lite|\bflash\b|\bpro\b/i.test(combined)
            || /model|modelo|modo/i.test(aria)
          )
        ) {
          toggle = candidate;
          break;
        }
      }
      if (toggle) break;
    }
    if (!toggle) {
      const nearby = omaGeminiNearbyModelLabel(composer);
      if (nearby) {
        let clickable = nearby.node;
        for (let depth = 0; clickable && depth < 6; depth++, clickable = clickable.parentElement) {
          if (!omaIsVisible(clickable) || clickable === composer) continue;
          const semantic = clickable.matches(
            "button,[role='button'],[aria-haspopup],[tabindex],mat-select,mat-chip"
          );
          let pointer = false;
          try {
            pointer = window.getComputedStyle(clickable).cursor === "pointer";
          } catch (_) {}
          if (semantic || pointer) {
            toggle = clickable;
            break;
          }
        }
        if (!toggle && nearby.node instanceof HTMLElement) toggle = nearby.node;
      }
    }
    if (!toggle) await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!toggle) {
    throw new Error("MODEL_SELECTION_FAILED: Gemini model selector not found after wait");
  }
  toggle.click();
  let option = null;
  while (Date.now() < deadline && !option) {
    const candidates = document.querySelectorAll(
      "[role='menuitem'],[role='option'],mat-option,button,[role='button']"
    );
    for (const candidate of candidates) {
      if (!omaIsVisible(candidate) || candidate === toggle) continue;
      const text = omaVisibleText(candidate);
      if (!text || text.length > 180) continue;
      const candidateModel = omaGeminiModelIdFromText(text);
      if (candidateModel === target) {
        option = candidate;
        break;
      }
    }
    if (!option) await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!option) {
    throw new Error("MODEL_SELECTION_FAILED: requested Gemini model option not found");
  }
  option.click();

  while (Date.now() < deadline) {
    if (omaGeminiCurrentModel() === target) {
      return { selected: true, model: target, unchanged: false };
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("MODEL_SELECTION_FAILED: Gemini UI did not confirm requested model");
}

function omaGeminiModelDiagnostics(composer) {
  if (omaProvider() !== "gemini" || !composer || !document.body) return [];
  const composerRect = composer.getBoundingClientRect();
  const describeCandidate = (node, text) => {
    const rect = node.getBoundingClientRect();
    const chain = [];
    let current = node;
    for (let depth = 0; current && depth < 5; depth++, current = current.parentElement) {
      let cursor = "";
      try { cursor = window.getComputedStyle(current).cursor || ""; } catch (_) {}
      chain.push({
        tag: current.tagName,
        class_name: String(current.className || "").slice(0, 160),
        role: current.getAttribute("role"),
        aria_label: current.getAttribute("aria-label"),
        aria_haspopup: current.getAttribute("aria-haspopup"),
        tabindex: current.getAttribute("tabindex"),
        cursor,
      });
    }
    return {
      text: String(text || "").slice(0, 80),
      model: omaGeminiModelIdFromText(text),
      rect: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      },
      composer_rect: {
        x: Math.round(composerRect.x), y: Math.round(composerRect.y),
        width: Math.round(composerRect.width), height: Math.round(composerRect.height),
      },
      vertical_gap: Math.round(Math.max(
        0,
        rect.top - composerRect.bottom,
        composerRect.top - rect.bottom,
      )),
      horizontal_gap: Math.round(Math.max(
        0,
        rect.left - composerRect.right,
        composerRect.left - rect.right,
      )),
      chain,
    };
  };

  const results = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let current = walker.nextNode();
  let scanned = 0;
  while (current && scanned < 6000 && results.length < 12) {
    scanned++;
    const raw = String(current.nodeValue || "").replace(/\s+/g, " ").trim();
    const parent = current.parentElement;
    if (
      raw
      && raw.length <= 80
      && omaGeminiModelIdFromText(raw)
      && parent
      && !seen.has(parent)
      && omaIsVisible(parent)
    ) {
      seen.add(parent);
      results.push(describeCandidate(parent, raw));
    }
    current = walker.nextNode();
  }
  return results;
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
  const sendCandidates = [];
  try {
    const nodes = document.querySelectorAll(OMA_SELECTORS.sendButton.join(","));
    for (const node of [...nodes].slice(0, 12)) {
      const rect = node.getBoundingClientRect();
      const cx = Math.max(0, Math.min(window.innerWidth - 1, rect.left + rect.width / 2));
      const cy = Math.max(0, Math.min(window.innerHeight - 1, rect.top + rect.height / 2));
      let top = null;
      try { top = document.elementFromPoint(cx, cy); } catch (_) {}
      sendCandidates.push(Object.assign(describe(node), {
        class_name: String(node.className || "").slice(0, 200),
        mattooltip: node.getAttribute("mattooltip"),
        text: String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
        rect: {
          x: Math.round(rect.x), y: Math.round(rect.y),
          width: Math.round(rect.width), height: Math.round(rect.height),
        },
        topmost: !!top && (top === node || node.contains(top)),
        top_tag: top ? top.tagName : null,
        top_class: top ? String(top.className || "").slice(0, 120) : null,
      }));
    }
  } catch (_) {}
  return { composer: describe(box), form: describe(form),
    form_buttons: form ? [...form.querySelectorAll("button")].slice(0,20).map(describe) : [],
    send_candidates: sendCandidates,
    composer_candidates: OMA_SELECTORS.composer.map(selector => ({selector,
      nodes: [...document.querySelectorAll(selector)].slice(0,4).map(describe)})),
    gemini_model_candidates: omaGeminiModelDiagnostics(box),
    composer_len: box ? omaComposerText(box).length : 0,
    ready_state: document.readyState, visibility: document.visibilityState };
}


function omaBrowserSelector(value) {
  const selector = String(value || "");
  if (!selector || selector.length > 500 || selector.includes("\0")) {
    throw new Error("browser selector must be 1..500 characters");
  }
  return selector;
}

function omaBrowserNode(selector) {
  let node = null;
  try { node = document.querySelector(omaBrowserSelector(selector)); }
  catch (e) { throw new Error("invalid browser selector"); }
  if (!node) throw new Error("browser selector did not match");
  return node;
}

function omaBrowserSetValue(node, text, clear) {
  const value = String(text || "");
  if (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) {
    if (clear) node.value = "";
    const proto = node instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(node, clear ? value : node.value + value);
    else node.value = clear ? value : node.value + value;
  } else if (node.isContentEditable) {
    node.focus();
    if (clear) node.textContent = "";
    node.textContent = (clear ? "" : (node.textContent || "")) + value;
  } else {
    throw new Error("browser target is not editable");
  }
  node.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
  node.dispatchEvent(new Event("change", { bubbles: true }));
}

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  // NEW_CHAT navega a p├ígina: responde de forma s├¡ncrona ANTES de navegar,
  // sen├úo o canal morre com o contexto JS (message channel closed).
  if (request && request.operation === "NEW_CHAT") {
    try { sendResponse({ ok: true, result: { navigating: true } }); } catch (_) {}
    setTimeout(() => { window.location.href = omaHomeUrl(); }, 100);
    return false;
  }
  (async () => {
    switch (request.operation) {
      case "BROWSER_EXTRACT": {
        const node = omaBrowserNode(request.selector || "body");
        const maxChars = Math.max(1, Math.min(Number(request.max_chars) || 200000, 1000000));
        const text = omaNodeReadableText(node);
        return {
          text: text.slice(0, maxChars),
          truncated: text.length > maxChars,
          url: window.location.href,
        };
      }
      case "BROWSER_CLICK": {
        const node = omaBrowserNode(request.selector);
        if (!omaIsVisible(node)) throw new Error("browser target is not visible");
        node.click();
        return { clicked: true, url: window.location.href };
      }
      case "BROWSER_TYPE": {
        const node = omaBrowserNode(request.selector);
        if (!omaIsVisible(node)) throw new Error("browser target is not visible");
        omaBrowserSetValue(node, request.text || "", !!request.clear);
        return { typed: true, url: window.location.href };
      }
      case "SET_MODEL":
        return await omaSetGeminiModel(request.model);
      case "SEND_MESSAGE": {
        omaPendingResponseBaseline = {
          count: omaAssistantMessageCount(),
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
        const assistantCount = omaAssistantMessageCount();
        const userNodes = document.querySelectorAll(
          OMA_SELECTORS.userMessages.join(","));
        const capBanner = omaCapBanner();
        const sendBtns = [
          ...document.querySelectorAll(OMA_SELECTORS.sendButton.join(",")),
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
        const hasConv = !!omaConversationId();
        let draftEmpty = true;
        try {
          const box = omaQueryFirst(OMA_SELECTORS.composer);
          draftEmpty = !box || !omaComposerText(box).trim();
        } catch (_) { draftEmpty = false; }
        const additionalChecks = omaFindAdditionalChecksBannerText();
        return { finished: omaGenerationFinished(), url: window.location.href,
                 provider: omaProvider(), model: omaGeminiCurrentModel(),
                 cs_version: OMA_CS_VERSION, cs_build_id: OMA_BUILD_ID,
                 cs_source_hash: OMA_SOURCE_HASH,
                 assistant_count: assistantCount,
                 user_count: userNodes.length,
                 message_count: assistantCount + userNodes.length,
                 conversation_id: omaConversationId(),
                 has_conversation: hasConv,
                 generation_running: !omaGenerationFinished(),
                 is_fresh_chat: !hasConv && assistantCount === 0 && userNodes.length === 0 && draftEmpty,
                 send_available: sendAvailable, cap_banner: capBanner,
                 additional_checks: additionalChecks,
                 additional_checks_recovery_attempts: omaAdditionalChecksRecoveryAttempts,
                 additional_checks_recovery_active: !!omaAdditionalChecksRecoveryPromise,
                 composer_found: composerFound, buttons_sample: buttonsSample,
                 diagnostics: omaComposerDiagnostics() };
      }
      case "SET_CONVERSATION_TITLE": {
        if (omaProvider() !== "chatgpt") {
          throw new Error("TITLE_UPDATE_FAILED: unsupported for Gemini");
        }
        const convId = request.conversation_id || omaConversationId();
        const title = String(request.title || "").trim();
        if (!convId) throw new Error("conversation_id required");
        if (!title || title.length > 200) throw new Error("title must be 1..200 characters");
        const sessionResp = await fetch("/api/auth/session", { credentials: "same-origin" });
        if (!sessionResp.ok) {
          throw new Error("TITLE_UPDATE_FAILED: session unavailable");
        }
        const sessionData = await sessionResp.json();
        const token = sessionData && sessionData.accessToken;
        if (!token) throw new Error("TITLE_UPDATE_FAILED: access token unavailable");
        const patchResp = await fetch(`/backend-api/conversation/${convId}`, {
          method: "PATCH",
          credentials: "same-origin",
          headers: {
            "Authorization": `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ title }),
        });
        if (!patchResp.ok) {
          throw new Error(`TITLE_UPDATE_FAILED: HTTP ${patchResp.status}`);
        }
        return { updated: true, conversation_id: convId, title };
      }
      case "DELETE_CONVERSATION": {
        if (omaProvider() !== "chatgpt") {
          throw new Error("DELETE_CONVERSATION: unsupported for Gemini");
        }
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
        window.location.href = omaHomeUrl();
        return { navigating: true };
      default:
        throw new Error(`UNKNOWN_OPERATION: ${request.operation}`);
    }
  })()
    .then((result) => sendResponse({ ok: true, result }))
    .catch((e) => sendResponse({ ok: false, error: String((e && e.message) || e) }));
  return true; // resposta ass├¡ncrona
});


let omaGlobalChecksScheduled = false;
let omaGlobalChecksBusy = false;
let omaGlobalChecksLastSignature = "";
let omaGlobalChecksLastAt = 0;

async function omaMaybeRecoverGlobalAdditionalChecks() {
  if (omaProvider() !== "chatgpt") return;
  // 1.6.50+: the autonomous guard owns global recovery so an already-open tab
  // can be repaired after extension reload without duplicating Stop/Continue.
  if (globalThis.__SENTRA_RECOVERY_GUARD__) return;
  if (omaGlobalChecksBusy) return;
  let settings = {};
  try {
    settings = await chrome.storage.local.get({
      oma_auto_recover_additional_checks: true,
    });
  } catch (_) {
    return;
  }
  // This is a local safety/recovery behavior for the current ChatGPT page.
  // It must not depend on the OMA scheduler being paired or enabled.
  if (settings.oma_auto_recover_additional_checks === false) return;

  const banner = omaFindAdditionalChecksBannerText(false);
  if (!banner) {
    omaMaybeResetAdditionalChecksRecoveryCycle();
    return;
  }

  // Never destroy a user's draft while auto-recovering a system warning.
  try {
    const composer = omaQueryFirst(OMA_SELECTORS.composer);
    if (composer && omaComposerText(composer).trim()) return;
  } catch (_) {
    return;
  }

  const signature = omaFoldUiText(banner).slice(0, 240);
  if (signature === omaGlobalChecksLastSignature && Date.now() - omaGlobalChecksLastAt < 12000) {
    return;
  }
  omaGlobalChecksLastSignature = signature;
  omaGlobalChecksLastAt = Date.now();
  omaGlobalChecksBusy = true;
  try {
    await omaRecoverAdditionalChecks();
    omaSendSwPing("OMA_ADDITIONAL_CHECKS_RECOVERED");
  } catch (e) {
    omaSendSwPing("OMA_ADDITIONAL_CHECKS_RECOVERY_FAILED");
  } finally {
    omaGlobalChecksBusy = false;
  }
}

function omaScheduleGlobalAdditionalChecksScan() {
  if (omaGlobalChecksScheduled) return;
  omaGlobalChecksScheduled = true;
  setTimeout(() => {
    omaGlobalChecksScheduled = false;
    void omaMaybeRecoverGlobalAdditionalChecks();
  }, 150);
}

try {
  const omaGlobalChecksObserver = new MutationObserver(omaScheduleGlobalAdditionalChecksScan);
  omaGlobalChecksObserver.observe(document.documentElement || document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  setInterval(() => void omaMaybeRecoverGlobalAdditionalChecks(), 1000);
  void omaMaybeRecoverGlobalAdditionalChecks();
} catch (_) {}

/*
 * MV3 service workers may sleep between the 1-minute alarm ticks. Controller tabs are
 * long-lived, so use them as the liveness source: a lightweight message wakes
 * the SW, whose listener verifies that the sender tab is the currently adopted
 * controller before polling the relay. This closes the gap where a worker looked online by
 * heartbeat but could miss a short targeted job deadline.
 */
const OMA_IDLE_WAKE_INTERVAL_MS = 2000;
function omaWakeWorker() {
  try {
    const pending = chrome.runtime.sendMessage({ operation: "OMA_IDLE_WAKE" });
    if (pending && typeof pending.catch === "function") pending.catch(() => {});
  } catch (_) {}
}
omaWakeWorker();
setInterval(omaWakeWorker, OMA_IDLE_WAKE_INTERVAL_MS);
