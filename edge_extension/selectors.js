/* selectors.js — seletores do chatgpt.com isolados num único módulo.
 * Se o DOM mudar, só este arquivo precisa de atualização. */
"use strict";

const OMA_SITE = (
  window.location.hostname === "gemini.google.com" ? "gemini" : "chatgpt"
);

const OMA_CHATGPT_SELECTORS = {
  composer: [
    '[role="textbox"]',
    "#prompt-textarea",
    'textarea[data-testid="chat-input"]',
    "[contenteditable='true']",
  ],
  sendButton: [
    "button[data-testid='send-button']",
    "button[aria-label*='Send']",
    "button[aria-label*='Enviar']",
  ],
  stopButton: [
    "button[data-testid='stop-button']",
    "button[aria-label='Stop generating']",
    "button[aria-label*='Interromper']",
  ],
  assistantMessages: [
    "[data-message-author-role='assistant']",
    "[data-message-author-role='assistant'] [data-message-id]",
    "article [data-message-author-role='assistant']",
    "main article .markdown",
  ],
  userMessages: [
    "[data-message-author-role='user']",
    "article [data-message-author-role='user']",
  ],
  newChatLink: [
    "a[href='/']",
  ],
  modelTrigger: [],
};

const OMA_GEMINI_SELECTORS = {
  composer: [
    "rich-textarea .ql-editor[contenteditable='true']",
    ".ql-editor[contenteditable='true'][role='textbox']",
    "rich-textarea [contenteditable='true']",
    "[role='textbox'][contenteditable='true']",
  ],
  sendButton: [
    "button[aria-label='Send message']",
    "button[aria-label='Enviar mensagem']",
    "button.send-button",
    "button[mattooltip='Send message']",
  ],
  stopButton: [
    "button[aria-label*='Stop']",
    "button[aria-label*='Parar']",
    "button[aria-label*='Interromper']",
    "button[aria-label*='Cancelar']",
    "button[mattooltip*='Stop' i]",
    "button[mattooltip*='Interromper' i]",
    "button:has(mat-icon[fonticon='stop'])",
    "button:has(.stop-icon)",
  ],
  assistantMessages: [
    ".model-response-text",
    ".markdown.markdown-main-panel",
    ".markdown-main-panel",
    "model-response message-content .markdown",
    "model-response message-content",
    "model-response .response-content",
    "model-response .markdown",
    "model-response",
  ],
  userMessages: [
    "user-query .query-text",
    "user-query",
  ],
  newChatLink: [
    "a[href='/app']",
    "a[href='https://gemini.google.com/app']",
  ],
  modelTrigger: [
    "[data-test-id='model-selector']",
    "button[aria-label*='model' i]",
    "button[aria-haspopup='menu']",
    "button[aria-haspopup='listbox']",
  ],
};

const OMA_SELECTORS = (
  OMA_SITE === "gemini" ? OMA_GEMINI_SELECTORS : OMA_CHATGPT_SELECTORS
);

function omaQueryFirst(selectors, root = document) {
  for (const sel of selectors) {
    const el = root.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function omaIsVisible(el) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
