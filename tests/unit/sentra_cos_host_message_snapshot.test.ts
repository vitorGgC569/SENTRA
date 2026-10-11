import { test, expect, beforeAll, afterAll } from 'bun:test';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const qa = process.env.SENTRA_BROWSER_QA_TREE;
if (!qa) throw Error('Set SENTRA_BROWSER_QA_TREE to disposable patched source');
const { chromium } = await import(resolve(qa, 'node_modules/playwright-core/index.mjs'));
const req = createRequire(resolve(qa, 'launcher/package.json'));
const { BrowserHost, collectSentraCommittedMessages } = req('./electron/browser-host.cjs');
const { BrowserControlServer } = req('./electron/control-server.cjs');
const sha = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex');
const doc = { document_id: 'a'.repeat(32), identity_epoch: 'b'.repeat(32), surface_id: 'isolated-surface' };
const userId = 'user-message-actual', assistantId = 'assistant-message-actual', requestId = 'request-user-actual';
let browser: any;
beforeAll(async () => { browser = await chromium.launch({ headless: true, executablePath: process.env.SENTRA_QA_CHROMIUM }); }, 30000);
afterAll(async () => { await browser?.close(); });

async function fixture() {
  const context = await browser.newContext();
  const page = await context.newPage();
  // All requests fulfilled locally; no website, account or external service accessed.
  await context.route('**/*', (route: any) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body><article data-message-id="anchor-real"></article></body></html>' }));
  await page.goto('https://chatgpt.com/c/conversation-actual');
  await page.evaluate(({ doc, userId, assistantId, requestId }: any) => {
    (globalThis as any).__SENTRA_WEB_DOCUMENT__ = doc;
    const messages: any[] = [
      { id: userId, author: { role: 'user' }, content: { parts: ['prompt real observado'] }, metadata: { request_id: requestId }, status: 'finished_successfully' },
      { id: assistantId, author: { role: 'assistant' }, content: { parts: ['resposta parcial'] }, metadata: { revision: 4 }, parent_id: userId, status: 'in_progress' },
    ];
    // Credential getters are adversarial: independent collector must not invoke them.
    for (const m of messages) Object.defineProperty(m, 'accessToken', { get() { throw Error('credential read'); } });
    const root: any = { tag: 3, memoizedProps: {}, stateNode: {} }; root.stateNode.current = root;
    const props = { conversationId: 'conversation-actual', messages };
    const child: any = { memoizedProps: props, return: root }; root.child = child;
    (document.querySelector('article') as any).__reactFiber$test = child;
    Object.assign(globalThis, { qaMessages: messages, qaRoot: root, qaFiber: child, qaProps: props });
  }, { doc, userId, assistantId, requestId });
  const contents: any = { isDestroyed: () => false, getURL: () => page.url(), executeJavaScript: (code: string) => page.evaluate(code) };
  const tab: any = { id: 'owned-tab', traceId: 'trace-private-actual', surfaceId: doc.surface_id,
    status: 'running', interactionMode: 'automatic', sentraDocument: doc, view: { webContents: contents } };
  const host: any = Object.assign(Object.create(BrowserHost.prototype), {
    turnTabs: new Map([[tab.id, tab]]), profile: 'development', partition: 'fixture-only', authenticationRevision: 0,
  });
  const log: any[] = [];
  const server = new BrowserControlServer({ logger: { info(...args: any[]) { log.push(args); }, warn(...args: any[]) { log.push(args); }, error(...args: any[]) { log.push(args); } }, getBrowserHost: () => host, getPreferences: () => ({}) });
  await server.start();
  const descriptor = server.descriptor();
  const post = async (path: string, data: any, auth = true) => {
    const res = await fetch(descriptor.endpoint + '/v1/sentra/' + path, { method: 'POST',
      headers: { 'content-type': 'application/json', ...(auth ? { authorization: 'Bearer ' + descriptor.token } : {}) }, body: JSON.stringify(data) });
    return { status: res.status, data: await res.json() as any };
  };
  const expected = (role = 'assistant', body = role === 'user' ? 'prompt real observado' : 'resposta parcial') => ({
    traceId: tab.traceId, ...doc, conversation_id: 'conversation-actual', message_id: role === 'user' ? userId : assistantId,
    expected_role: role, observed_request_id: requestId, ...(role === 'assistant' ? { parent_user_message_id: userId } : {}),
    body_sha256: sha(body), complete: role === 'user',
  });
  const observe = async (overrides: any = {}, role = 'assistant', body?: string) => {
    const challenge = await post('message-challenge', { ...expected(role, body), ...overrides });
    expect(challenge.status).toBe(200); expect(challenge.data.state).toBe('CHALLENGED');
    const result = await post('message-snapshot', { challenge_id: challenge.data.challenge_id });
    expect(result.status).toBe(200); expect(result.data.challenge_sha256).toBe(challenge.data.challenge_sha256);
    return result.data;
  };
  return { page, context, contents, tab, host, post, expected, observe, log, descriptor,
    async close() { await new Promise<void>(done => server.server.close(() => done())); await context.close(); } };
}

function denied(value: any, reason?: string) {
  expect(value.matched).toBe(false); expect(value.state).toBe('UNKNOWN'); expect(value.role).toBe('UNKNOWN');
  expect(value.account_verified).toBe(false); expect(value.approval_state).toBe('UNKNOWN');
  if (reason) expect(value.reason).toBe(reason);
}

test('private real Host HTTP observes user and assistant parent, source and host revisions without body/credentials', async () => {
  const f = await fixture();
  try {
    const user = await f.observe({}, 'user');
    expect(user.role).toBe('user'); expect(user.observed_request_id).toBe(requestId); expect(user.parent_user_message_id).toBeNull();
    const a = await f.observe();
    expect(a.matched).toBe(true); expect(a.role).toBe('assistant'); expect(a.message_id).toBe(assistantId);
    expect(a.parent_user_message_id).toBe(userId); expect(a.observed_request_id).toBe(requestId);
    expect(a.metadata_request_id).toBeNull(); expect(a.body_sha256).toBe(sha('resposta parcial'));
    expect(a).not.toHaveProperty('body'); expect(a.host_revision).toBe(1); expect(a.provider_revision).toBe(4); expect(a.complete).toBe(false);
    expect(a.account_verified).toBe(false); expect(a.approval_state).toBe('UNKNOWN');
    expect(a.collector_sha256).toBe(sha(collectSentraCommittedMessages.toString())); expect(a.host_source_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect((await f.observe()).host_revision).toBe(1);
    await f.page.evaluate(() => { const m = (globalThis as any).qaMessages[1]; m.content.parts = ['resposta final']; m.status = 'finished_successfully'; m.metadata.revision = 5; });
    const final = await f.observe({ body_sha256: sha('resposta final'), complete: true });
    expect(final.host_revision).toBe(2); expect(final.provider_revision).toBe(5); expect(final.complete).toBe(true);
    expect(JSON.stringify(f.log)).not.toContain('prompt real observado'); expect(JSON.stringify(f.log)).not.toContain('resposta');
  } finally { await f.close(); }
});

test('Host issues one-use nonce; snapshot cannot replace challenge; bearer and closed schema required', async () => {
  const f = await fixture();
  try {
    expect((await f.post('message-challenge', f.expected(), false)).status).toBe(401);
    for (const extra of [{ revision: 900 }, { body: 'forged' }, { role: 'assistant' }, { challenge_id: 'c'.repeat(32) }]) {
      expect((await f.post('message-challenge', { ...f.expected(), ...extra })).status).toBe(400);
    }
    const c = (await f.post('message-challenge', f.expected())).data;
    expect(c.role).toBe('UNKNOWN'); expect(c.challenge_id).toMatch(/^[a-f0-9]{32}$/);
    expect((await f.post('message-snapshot', { challenge_id: c.challenge_id, body_sha256: sha('other') })).status).toBe(400);
    expect((await f.post('message-snapshot', { challenge_id: c.challenge_id })).data.matched).toBe(true);
    denied((await f.post('message-snapshot', { challenge_id: c.challenge_id })).data, 'challenge_unknown_or_consumed');
    denied((await f.post('message-snapshot', { challenge_id: 'f'.repeat(32) })).data, 'challenge_unknown_or_consumed');
    const expired = (await f.post('message-challenge', f.expected())).data;
    f.host.sentraMessageChallenges.get(expired.challenge_id).expiry = Date.now() - 1;
    denied((await f.post('message-snapshot', { challenge_id: expired.challenge_id })).data, 'challenge_expired');
  } finally { await f.close(); }
});

test('requested role and DOM labels never provide actual role; missing/foreign message ID denied', async () => {
  const f = await fixture();
  try {
    denied(await f.observe({ message_id: 'forged-message-id' }), 'message_role_unverified');
    await f.page.evaluate(() => { (globalThis as any).qaMessages[1].author.role = 'user'; document.querySelector('article')!.setAttribute('data-message-author-role', 'assistant'); });
    denied(await f.observe(), 'message_role_unverified');
    await f.page.evaluate(() => { delete (globalThis as any).qaMessages[1].author.role; });
    denied(await f.observe(), 'message_role_unverified');
  } finally { await f.close(); }
});

test('assistant parent must be actual user with actual request; no caller binding supplies missing chain', async () => {
  const f = await fixture();
  try {
    denied(await f.observe({ parent_user_message_id: 'parent-forged-id' }), 'parent_mismatch');
    await f.page.evaluate(() => { (globalThis as any).qaMessages[0].metadata.request_id = 'request-other-user'; });
    denied(await f.observe(), 'parent_request_unverified');
    await f.page.evaluate(() => { delete (globalThis as any).qaMessages[0].metadata.request_id; });
    denied(await f.observe(), 'parent_request_unverified'); denied(await f.observe({}, 'user'), 'request_mismatch');
    await f.page.evaluate(() => { (globalThis as any).qaMessages[0].author.role = 'assistant'; });
    denied(await f.observe(), 'parent_request_unverified');
    await f.page.evaluate(() => { delete (globalThis as any).qaMessages[1].parent_id; });
    denied(await f.observe(), 'parent_mismatch');
  } finally { await f.close(); }
});

test('body hash and completion use actual content/status; provider revision regression denied', async () => {
  const f = await fixture();
  try {
    denied(await f.observe({ body_sha256: sha('forged') }), 'body_changed');
    denied(await f.observe({ complete: true }), 'completion_unverified');
    expect((await f.observe()).host_revision).toBe(1);
    await f.page.evaluate(() => { (globalThis as any).qaMessages[1].metadata.revision = 3; });
    denied(await f.observe(), 'provider_revision_regressed');
    await f.page.evaluate(() => { delete (globalThis as any).qaMessages[1].metadata.revision; });
    denied(await f.observe(), 'provider_revision_regressed');
    await f.page.evaluate(() => { (globalThis as any).qaMessages[1].status = 'unknown-provider-status'; });
    denied(await f.observe(), 'completion_unverified');
  } finally { await f.close(); }
});

test('duplicate message IDs with different bodies and stale React branch are UNKNOWN', async () => {
  const f = await fixture();
  try {
    await f.page.evaluate(() => { const g = globalThis as any; g.qaMessages.push({ ...g.qaMessages[1], content: { parts: ['conflicting body'] } }); });
    denied(await f.observe(), 'message_conflict');
    await f.page.evaluate(() => { const g = globalThis as any; g.qaMessages.pop(); g.qaRoot.stateNode.current = { tag: 3, stateNode: g.qaRoot.stateNode }; });
    denied(await f.observe(), 'conversation_unobserved');
  } finally { await f.close(); }
});

test('committed alternate is read instead of stale original; unsupported content and getter role block', async () => {
  const f = await fixture();
  try {
    await f.page.evaluate(() => {
      const g = globalThis as any; const root = { ...g.qaRoot, alternate: g.qaRoot };
      const child = { ...g.qaFiber, alternate: g.qaFiber, return: root,
        memoizedProps: { ...g.qaProps, messages: [{ ...g.qaMessages[1], author: {} }, g.qaMessages[0]] } };
      root.child = child; g.qaRoot.alternate = root; g.qaFiber.alternate = child; g.qaRoot.stateNode.current = root;
    });
    denied(await f.observe(), 'message_role_unverified');
    await f.page.evaluate(() => { const g = globalThis as any; g.qaRoot.stateNode.current = g.qaRoot; g.qaMessages[1].content.parts = [{ text: 'unsupported' }]; });
    denied(await f.observe(), 'message_content_unsupported');
    await f.page.evaluate(() => { const g = globalThis as any; g.qaMessages[1].content.parts = ['resposta parcial']; Object.defineProperty(g.qaMessages[1].author, 'role', { get() { throw Error('role getter untrusted'); } }); });
    denied(await f.observe(), 'message_role_unverified');
  } finally { await f.close(); }
});

test('body changing between independent reads and conversation conflict fail closed', async () => {
  const f = await fixture();
  try {
    const original = f.contents.executeJavaScript; let n = 0;
    f.contents.executeJavaScript = async (source: string) => {
      const observation = await original(source);
      if (++n === 1) await f.page.evaluate(() => { (globalThis as any).qaMessages[1].content.parts = ['changed during snapshot']; });
      return observation;
    };
    denied(await f.observe(), 'observation_changed'); f.contents.executeJavaScript = original;
    await f.page.evaluate(() => { (globalThis as any).qaProps.conversationId = 'foreign-conversation'; });
    denied(await f.observe(), 'conversation_conflict');
  } finally { await f.close(); }
});

test('challenge ownership, document epoch, authentication and partition are revalidated before/after', async () => {
  const f = await fixture();
  try {
    for (const mutate of [() => { f.host.authenticationRevision++; }, () => { f.host.partition += '-changed'; },
      () => { f.tab.sentraDocument = { ...doc }; }]) {
      const c = (await f.post('message-challenge', f.expected())).data; mutate();
      denied((await f.post('message-snapshot', { challenge_id: c.challenge_id })).data, 'document_changed');
    }
    const original = f.contents.executeJavaScript;
    f.contents.executeJavaScript = async (source: string) => { const o = await original(source); f.host.authenticationRevision++; return o; };
    denied(await f.observe(), 'document_changed'); f.contents.executeJavaScript = original;
    await f.page.evaluate(() => { (globalThis as any).__SENTRA_WEB_DOCUMENT__.identity_epoch = 'c'.repeat(32); });
    denied(await f.observe(), 'document_or_conversation_changed');
  } finally { await f.close(); }
});

test('approval absence/hidden cards is UNKNOWN; visible pending and explicit committed idle preserve source', async () => {
  const f = await fixture();
  try {
    expect((await f.observe()).approval_state).toBe('UNKNOWN');
    await f.page.evaluate(() => { const e = document.createElement('div'); e.dataset.testid = 'approval-card'; e.style.display = 'none'; e.textContent = 'approval fixture'; document.body.appendChild(e); });
    expect((await f.observe()).approval_state).toBe('UNKNOWN');
    await f.page.evaluate(() => { (document.querySelector('[data-testid="approval-card"]') as HTMLElement).style.display = 'block'; });
    const p = await f.observe(); expect(p.approval_state).toBe('pending'); expect(p.approval_source).toBe('visible-approval-card');
    await f.page.evaluate(() => { document.querySelector('[data-testid="approval-card"]')!.remove(); (globalThis as any).qaProps.approvalState = 'idle'; });
    const idle = await f.observe(); expect(idle.approval_state).toBe('idle'); expect(idle.approval_source).toBe('committed-react:approvalState');
    expect(idle.account_verified).toBe(false);
    await f.page.evaluate(() => { (globalThis as any).qaRoot.memoizedProps.approvalState = 'pending'; });
    expect((await f.observe()).approval_state).toBe('UNKNOWN');
  } finally { await f.close(); }
});

test('same message ID cannot rebind parent/request/role; observation busy/unknown roles never succeed', async () => {
  const f = await fixture();
  try {
    expect((await f.observe()).matched).toBe(true);
    await f.page.evaluate(() => {
      const g = globalThis as any; const parent = { ...g.qaMessages[0], id: 'new-user-parent-id' };
      g.qaMessages.push(parent); g.qaMessages[1].parent_id = parent.id;
    });
    denied(await f.observe({ parent_user_message_id: 'new-user-parent-id' }), 'message_binding_changed');
    f.tab.sentraMessageObservationBusy = true;
    denied(await f.observe(), 'observation_busy');
  } finally { await f.close(); }
});
