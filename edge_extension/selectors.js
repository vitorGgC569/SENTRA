/* selectors.js — seletores do chatgpt.com isolados num único módulo.
 * Se o DOM mudar, só este arquivo precisa de atualização. */
"use strict";

const OMA_SELECTORS = {
  composer: [
    '[role="textbox"]',
    "#prompt-textarea",
    'textarea[data-testid="chat-input"]',
    "[contenteditable='true']",
  ],
  sendButton: [
    "button[data-testid='send-button']",
  ],
  stopButton: [
    "button[data-testid='stop-button']",
    "button[aria-label='Stop generating']",
  ],
  assistantMessages: [
    "[data-message-author-role='assistant']",
  ],
  newChatLink: [
    "a[href='/']",
  ],
};

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
