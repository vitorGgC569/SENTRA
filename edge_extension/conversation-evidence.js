/* Restricted ChatGPT MAIN-world reader. No actions, secrets or tool arguments.
 * Committed React path algorithm adapted from Chat On Steroids fiber.js at
 * 151e7ef96bc16bf594ffbd35efe620e4ef6e4c2c. MIT notice: COS-NOTICE.txt.
 * Page observations are data, never authentication or capability authority. */
(() => {
  'use strict';
  let documentId = crypto.randomUUID();
  let routeKey = location.origin + location.pathname;
  function currentDocument() {
    const now = location.origin + location.pathname;
    // SPA conversation navigation is a new evidence generation, even if
    // Chrome retains the same JS Document and React root.
    if (now !== routeKey) { routeKey = now; documentId = crypto.randomUUID(); }
    return documentId;
  }
  const ID = /^[A-Za-z0-9_-]{8,160}$/;
  function committed(fiber) {
    const path = [], seen = new Set();
    let at = fiber, root = null, current = null;
    while (at && path.length < 2048) {
      if (seen.has(at)) return null;
      seen.add(at);
      if (at.tag === 3) {
        root = at.stateNode; current = root?.current;
        if (!current || (current !== at && current !== at.alternate)) return null;
        break;
      }
      path.push(at); at = at.return;
    }
    if (!root) return null;
    let node = current, view = { memoizedProps: node.memoizedProps, return: null }, budget = 4096;
    for (let index = path.length - 1; index >= 0; index--) {
      let selected = null;
      for (let child = node.child; child; child = child.sibling) {
        if (--budget < 0) return null;
        if (child !== path[index] && child !== path[index].alternate) continue;
        if (selected) return null;
        selected = child;
      }
      if (!selected || root.current !== current) return null;
      node = selected;
      view = { memoizedProps: node.memoizedProps, return: view };
    }
    return view;
  }
  function fiberFor(element) {
    for (const key of Object.keys(element)) {
      if (key.startsWith('__reactFiber$')) return committed(element[key]);
    }
    return null;
  }
  function observe(nonce) {
    const scanDocument = currentDocument();
    if (location.origin !== 'https://chatgpt.com') return null;
    const routeId = /^\/c\/([A-Za-z0-9_-]{8,160})(?:\/|$)/.exec(location.pathname)?.[1];
    if (!routeId) return null;
    const requests = new Map(), messageOwners = new Map();
    let conversationId = null, conflict = false;
    const anchors = [...document.querySelectorAll(
      '[data-message-id],section[data-testid^="conversation-turn"],[data-turn-key]'
    )].slice(-200);
    for (const element of anchors) {
      const fiber = fiberFor(element);
      if (!fiber) continue;
      let at = fiber, branchConversation = null, messages = [];
      for (let depth = 0; at && depth < 80; depth++, at = at.return) {
        const p = at.memoizedProps;
        if (!p || typeof p !== 'object') continue;
        // Read primitive, durable IDs only. Never invoke page callbacks/signals.
        for (const value of [p.conversationId, p.clientThreadId, p.conversation?.id,
                             p.turn?.conversationId, p.entry?.conversationId]) {
          if (typeof value !== 'string' || !ID.test(value)) continue;
          if (branchConversation && branchConversation !== value) conflict = true;
          branchConversation = value;
        }
        for (const list of [p.messages, p.allMessages, p.turn?.messages]) {
          if (Array.isArray(list)) messages.push(...list.slice(0, 200));
        }
        if (p.message && typeof p.message === 'object') messages.push(p.message);
      }
      if (!branchConversation) continue;
      if (branchConversation !== routeId || (conversationId && conversationId !== branchConversation)) conflict = true;
      conversationId = branchConversation;
      for (const message of messages.slice(0, 600)) {
        if (message?.author?.role !== 'user') continue;
        const request = message?.metadata?.request_id, id = message?.id;
        if (typeof request !== 'string' || typeof id !== 'string' || !ID.test(request) || !ID.test(id)) continue;
        // Two different committed messages for one MCP request are
        // ambiguous; never let the last DOM walk silently replace proof.
        const prior = requests.get(request);
        if (prior && prior.message_id !== id) return null;
        const other = messageOwners.get(id);
        if (other && other !== request) return null;
        messageOwners.set(id, request);
        requests.set(request, { request_id: request, message_id: id });
        if (requests.size > 200) return null;
      }
    }
    if (conflict || !conversationId) return null;
    const approval = document.querySelector(
      '[data-testid="connector-approval"],[data-testid="tool-approval"],[data-testid="approval-card"]'
    );
    const stopped = document.querySelector('[data-testid="stop-button"],[data-testid="composer-stop-button"]');
    const composer = document.querySelector('#prompt-textarea,[data-testid="composer-input"]');
    const state = approval ? 'awaiting_approval' : stopped ? 'generating' : composer ? 'idle' : 'unknown';
    if (scanDocument !== currentDocument()) return null;
    return { nonce, document_id: scanDocument, conversation_id: conversationId,
      route_conversation_id: routeId, state, requests: [...requests.values()] };
  }
  function assistantFrame(expected) {
    if (location.origin !== 'https://chatgpt.com' || !expected || !ID.test(expected.request_id || '') ||
        !ID.test(expected.parent_user_message_id || '') || expected.document_id !== currentDocument()) return null;
    const route = /^\/c\/([A-Za-z0-9_-]{8,160})(?:\/|$)/.exec(location.pathname)?.[1];
    if (route !== expected.conversation_id) return null;
    const own = (object, key) => {
      const descriptor = object && typeof object === 'object' && Object.getOwnPropertyDescriptor(object, key);
      return descriptor && Object.hasOwn(descriptor, 'value') ? descriptor.value : undefined;
    };
    const found = new Map(); let budget = 4096;
    for (const element of [...document.querySelectorAll('[data-message-id],section[data-testid^="conversation-turn"]')].slice(-200)) {
      let node = fiberFor(element), branch = null, messages = [];
      for (let depth = 0; node && depth < 80; depth++, node = node.return) {
        const props = node.memoizedProps;
        for (const value of [own(props,'conversationId'),own(props,'clientThreadId'),own(own(props,'conversation'),'id')]) {
          if (!ID.test(value || '')) continue;
          if (branch && branch !== value) return null;
          branch = value;
        }
        for (const list of [own(props,'messages'),own(props,'allMessages'),own(own(props,'turn'),'messages')]) {
          if (Array.isArray(list)) { if (list.length > 600) return null; messages.push(...list); }
        }
        if (own(props,'message')) messages.push(own(props,'message'));
      }
      if (branch !== route) continue;
      for (const message of messages) {
        if (--budget < 0) return null;
        const id = own(message,'id'), role = own(own(message,'author'),'role');
        if (!ID.test(id || '') || !['user','assistant'].includes(role)) continue;
        const parts = own(own(message,'content'),'parts');
        // Native images must be committed assistant image_asset_pointer parts.
        // Never mine image URLs from Markdown, code output, tool messages or DOM.
        // An unsupported part means no assistant proof, not text-only success.
        let body = null, assets = [];
        if (role === 'assistant') {
          if (!Array.isArray(parts) || parts.length > 64) continue;
          const textParts = []; let unsupported = false;
          for (const part of parts) {
            if (typeof part === 'string') { textParts.push(part); continue; }
            const pointer = own(part,'asset_pointer');
            if (own(part,'content_type') === 'image_asset_pointer' &&
                typeof pointer === 'string' && /^file-service:\/\/file-[A-Za-z0-9_-]{8,160}$/.test(pointer)) {
              assets.push(pointer.slice('file-service://'.length));
              continue;
            }
            unsupported = true; break;
          }
          if (unsupported || assets.length > 4 || new Set(assets).size !== assets.length) continue;
          body = textParts.join('\n');
        }
        if (body !== null && body.length > 200000) return null;
        const value = { message_id:id,role,body,assets,parent:own(message,'parent_id'),
          request:own(own(message,'metadata'),'request_id'),status:own(message,'status') };
        if (found.has(id) && JSON.stringify(found.get(id)) !== JSON.stringify(value)) return null;
        found.set(id,value);
      }
    }
    const parent = found.get(expected.parent_user_message_id);
    if (!parent || parent.role !== 'user' || parent.request !== expected.request_id) return null;
    const children = [...found.values()].filter(item => item.role === 'assistant' && item.parent === parent.message_id);
    if (children.length !== 1 || currentDocument() !== expected.document_id) return null;
    const child = children[0];
    if (!['in_progress','finished_successfully'].includes(child.status)) return null;
    return { message_id:child.message_id,parent_user_message_id:parent.message_id,body:child.body,
      assets:child.assets,conversation_id:route,document_id:currentDocument(),complete:child.status === 'finished_successfully' };
  }

  // A document keeps its identity across scans and service-worker restarts.
  if (!globalThis.__sentraConversationEvidence) {
    Object.defineProperty(globalThis, '__sentraConversationEvidence', {
      value: { get documentId() { return currentDocument(); }, observe, assistantFrame }, configurable: true,
    });
  }
})();
