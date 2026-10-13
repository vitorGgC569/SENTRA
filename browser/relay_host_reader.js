/* SERVER-SELECTED read-only Edge collector. Never installed as an extension
 * authority. CDP evaluates these reviewed bytes in the bound physical target.
 * Committed React path follows the MIT COS algorithm (COS-NOTICE.txt). No
 * network/storage/cookies, callbacks, approval actions or renderer frame reads.
 * Missing/ambiguous account, model or logical message stays unknown. */
(function sentraEdgeHostRead(selectors) {
  'use strict';
  const own = (object, key) => {
    const d = object && typeof object === 'object' && Object.getOwnPropertyDescriptor(object, key);
    return d && Object.hasOwn(d, 'value') ? d.value : undefined;
  };
  const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(value);
  const unknown = reason => ({ observed:false, reason });
  if (location.origin !== 'https://chatgpt.com') return unknown('wrong_origin');
  let budget = 20000;
  function propsFor(element) {
    const keys = Object.keys(element).filter(key => key.startsWith('__reactFiber$'));
    if (keys.length !== 1) return [];
    let node = own(element, keys[0]); const path = [], visited = new Set();
    while (node && own(node,'tag') !== 3 && path.length < 2048 && !visited.has(node)) {
      visited.add(node); path.push(node); node = own(node,'return');
    }
    const root = own(node,'stateNode'), current = own(root,'current');
    if (!current || (current !== node && current !== own(node,'alternate'))) return [];
    node = current; const props = [own(node,'memoizedProps')];
    for (const expected of path.reverse()) {
      let selected; const siblings = new Set();
      for (let child = own(node,'child'); child; child = own(child,'sibling')) {
        if (--budget < 0 || siblings.has(child)) return [];
        siblings.add(child);
        if (child !== expected && child !== own(expected,'alternate')) continue;
        if (selected) return [];
        selected = child;
      }
      if (!selected || own(root,'current') !== current) return [];
      node = selected; props.push(own(node,'memoizedProps'));
    }
    return props.slice(-80);
  }
  const accounts = new Set(), users = new Set(), models = new Set(), efforts = new Set();
  for (const element of [...document.querySelectorAll('[data-testid="accounts-profile-button"],[data-testid="profile-button"]')].slice(0,8)) {
    for (const p of propsFor(element)) {
      const a = own(own(p,'account'),'id'), u = own(own(p,'user'),'id');
      if (id(a)) accounts.add(a);
      if (id(u)) users.add(u);
    }
  }
  // No guessed labels or ordinal slider->effort mappings. Observe primitive
  // committed selected values on the picker ancestry, or the selected option.
  const visible = element => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
  for (const element of [...document.querySelectorAll('[data-testid="model-switcher-dropdown-button"],[data-testid="thinking-effort-dropdown-button"],[role="menuitemradio"][aria-checked="true"]')].filter(visible).slice(0,16)) {
    for (const p of propsFor(element)) {
      for (const value of [own(own(p,'selectedModel'),'slug'),own(p,'selectedModelSlug'),own(p,'currentModelSlug')]) {
        if (typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,120}$/.test(value)) models.add(value);
      }
      if (own(p,'automaticMode') === true) models.add('automatic');
      for (const value of [own(p,'selectedReasoningEffort'),own(p,'reasoningEffort')]) {
        if (typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value)) efforts.add(value);
      }
    }
    const slug = element.getAttribute('data-model-slug'), effort = element.getAttribute('data-reasoning-effort');
    if (slug && /^[A-Za-z0-9_.:-]{1,120}$/.test(slug)) models.add(slug);
    if (effort && /^[A-Za-z0-9_-]{1,120}$/.test(effort)) efforts.add(effort);
  }
  const pending = [...document.querySelectorAll('[data-testid="connector-approval"],[data-testid="tool-approval"],[data-testid="approval-card"]')].some(visible);
  const route = /^\/c\/([A-Za-z0-9_-]{8,160})(?:\/|$)/.exec(location.pathname)?.[1] || null;
  // Extension document ID is correlation DATA only. Independent CDP loader,
  // OS process/profile and the server's CP epoch enrollment bind this value.
  const evidence = own(globalThis,'__sentraConversationEvidence');
  const documentId = evidence ? evidence.documentId : null;
  const found = new Map(), assistantChildren = new Set();
  if (selectors.message_id) {
    if (route !== selectors.conversation_id || !id(selectors.message_id) || !id(selectors.parent_user_message_id)) return unknown('route_or_selector');
    for (const element of [...document.querySelectorAll('[data-message-id],[data-turn-key],[data-turn-id-container],section[data-testid^="conversation-turn"]')].slice(-200)) {
      const props = propsFor(element), values = []; let branch = null;
      for (const p of props) {
        for (const value of [own(p,'conversationId'),own(p,'clientThreadId'),own(own(p,'conversation'),'id'),own(own(p,'turn'),'conversationId')]) {
          if (!id(value)) continue;
          if (branch && branch !== value) return unknown('branch_conflict');
          branch = value;
        }
        for (const list of [own(p,'messages'),own(p,'allMessages'),own(own(p,'turn'),'messages')]) {
          if (!Array.isArray(list)) continue;
          if (list.length > 600) return unknown('message_quota');
          values.push(...list);
        }
        if (own(p,'message')) values.push(own(p,'message'));
      }
      if (branch !== route) continue;
      for (const m of values) {
        if (--budget < 0) return unknown('collector_quota');
        const mid = own(m,'id'), role = own(own(m,'author'),'role');
        if (role === 'assistant' && own(m,'parent_id') === selectors.parent_user_message_id && id(mid)) assistantChildren.add(mid);
        if (mid !== selectors.message_id && mid !== selectors.parent_user_message_id) continue;
        const parts = own(own(m,'content'),'parts');
        if (!['assistant','user'].includes(role) || (role === 'assistant' && (!Array.isArray(parts) || parts.some(part => typeof part !== 'string')))) return unknown('content_or_role');
        const body = role === 'assistant' ? parts.join('\n') : null;
        if (body !== null && body.length > 200000) return unknown('body_quota');
        const status = own(m,'status'), value = {message_id:mid,role,body,parent_id:own(m,'parent_id') || null,
          request_id:own(own(m,'metadata'),'request_id') || null,
          complete:status === 'finished_successfully' ? true : status === 'in_progress' ? false : null};
        if (found.has(mid) && JSON.stringify(found.get(mid)) !== JSON.stringify(value)) return unknown('message_conflict');
        found.set(mid,value);
      }
    }
  }
  if (budget < 0) return unknown('collector_quota');
  return {observed:true,url:location.href,conversation_id:route,document_id:documentId,
    account_id:accounts.size === 1 ? [...accounts][0] : null,user_id:users.size === 1 ? [...users][0] : null,
    model_slug:models.size === 1 ? [...models][0] : null,effort:efforts.size === 1 ? [...efforts][0] : null,
    effort_observed:efforts.size === 1,approval_state:pending ? 'pending' : 'unknown',messages:[...found.values()],
    assistant_children:[...assistantChildren]};
})
