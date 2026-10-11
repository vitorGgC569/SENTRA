import { test, expect, beforeAll, afterAll } from 'bun:test';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';

const qa = process.env.SENTRA_BROWSER_QA_TREE;
if (!qa) throw Error('Set SENTRA_BROWSER_QA_TREE to the disposable patched source tree');
const { SentraWebSubmission, ChatGptBrowserWorker, readSentraPageEvidence } = await import(resolve(qa, 'src/adapters/chatgpt-web/browser-worker.ts'));
const { sentraDurableWeb } = await import(resolve(qa, 'src/adapters/chatgpt-web/index.ts'));
const { chromium } = await import(resolve(qa, 'node_modules/playwright-core/index.mjs'));
const qaRequire = createRequire(resolve(qa, 'launcher/package.json'));
const { BrowserHost, collectSentraUiIdentity } = qaRequire('./electron/browser-host.cjs');
const { BrowserControlServer } = qaRequire('./electron/control-server.cjs');
let browser: any;
beforeAll(async () => {
  browser = await chromium.launch({ headless: true, executablePath: process.env.SENTRA_QA_CHROMIUM });
}, 30000);
afterAll(async () => { await browser?.close(); });
const PROMPT = 'Mensagem hermética — nenhum envio a uma conta real';
const SHA = createHash('sha256').update(PROMPT).digest('hex');
const identity = { document_id: 'a'.repeat(32), identity_epoch: 'b'.repeat(32), surface_id: 'owned-surface-fixture' };

test('actual Host collector and private HTTP snapshot never read session credentials or claim verified account', async () => {
  const { page, context } = await pageFixture();
  const tab: any = { id: 'isolated-tab', traceId: 'trace-fixture', surfaceId: identity.surface_id,
    status: 'running', interactionMode: 'automatic', sentraDocument: identity,
    view: { webContents: { isDestroyed: () => false, getURL: () => page.url(),
      executeJavaScript: (source: string) => page.evaluate(source) } } };
  const host = Object.assign(Object.create(BrowserHost.prototype), {
    turnTabs: new Map([[tab.id, tab]]), profile: 'development', partition: 'persist:codex-web-gpt-chatgpt-dev',
    authenticationRevision: 0,
  });
  const server = new BrowserControlServer({ logger: { info() {}, error() {} }, getBrowserHost: () => host,
    getPreferences: () => ({}) });
  await server.start();
  const binding = { ...identity, traceId: tab.traceId };
  try {
    const url = server.descriptor().endpoint + '/v1/sentra/identity-snapshot';
    expect((await fetch(url, { method: 'POST', body: JSON.stringify(binding) })).status).toBe(401);
    await page.evaluate(() => {
      const button: any = document.createElement('button'); button.dataset.testid = 'accounts-profile-button';
      document.body.appendChild(button);
      const root: any = { tag: 3, memoizedProps: {}, stateNode: {} }; root.stateNode.current = root;
      const account: any = { id: 'account-observed-fixture' };
      const user: any = { id: 'user-observed-fixture' };
      for (const key of ['accessToken', 'cookies', 'session']) Object.defineProperty(user, key, {
        get() { throw Error('credentials must not be read'); } });
      const child: any = { memoizedProps: { account, user }, return: root };
      root.child = child; button.__reactFiber$fixture = child;
    });
    const response = await fetch(url, { method: 'POST', headers: {
      authorization: 'Bearer ' + server.descriptor().token, 'content-type': 'application/json' }, body: JSON.stringify(binding) });
    expect(response.status).toBe(200);
    const snapshot: any = await response.json();
    expect(snapshot.account_id).toBe('account-observed-fixture');
    expect(snapshot.account_verified).toBe(false);
    expect(snapshot.reason).toBe('collector_schema_unverified');
    expect(snapshot.profile).toBe('development');
    expect(snapshot.provider_selection.selection_verified).toBe(false);
    expect(snapshot.approval_state).toBeNull();
    expect(snapshot.collector_sha256).toBe(createHash('sha256').update(collectSentraUiIdentity.toString()).digest('hex'));
    expect(snapshot.host_source_sha256).toMatch(/^[a-f0-9]{64}$/);
    tab.sentraDocument = { ...identity, identity_epoch: 'rotated' };
    await expect(host.sentraIdentitySnapshot(binding)).rejects.toThrow();
  } finally { await new Promise<void>(done => server.server.close(() => done())); await context.close(); }
});

test('account-menu observation rejects absent, conflicting and stale committed identities', async () => {
  const { page, context } = await pageFixture();
  try {
    expect((await page.evaluate(`(${collectSentraUiIdentity.toString()})()`)).reason).toBe('account_ui_identity_unavailable');
    await page.evaluate(() => {
      for (const id of ['one', 'two']) {
        const button: any = document.createElement('button'); button.dataset.testid = 'profile-button'; document.body.appendChild(button);
        const root: any = { tag: 3, stateNode: {}, memoizedProps: {} }; root.stateNode.current = root;
        const child: any = { memoizedProps: { account: { id } }, return: root }; root.child = child;
        button.__reactFiber$fixture = child;
      }
    });
    expect((await page.evaluate(`(${collectSentraUiIdentity.toString()})()`)).reason).toBe('identity_conflict');
    await page.evaluate(() => {
      for (const button of document.querySelectorAll('[data-testid="profile-button"]')) {
        const fiber = (button as any).__reactFiber$fixture; fiber.return.stateNode.current = {};
      }
    });
    expect((await page.evaluate(`(${collectSentraUiIdentity.toString()})()`)).account_id).toBeNull();
  } finally { await context.close(); }
});

test('Host provider selection reads explicit current controls independently of any requested model', async () => {
  const { page, context } = await pageFixture();
  try {
    await page.evaluate(() => {
      const menu = document.createElement('div');
      menu.innerHTML = '<div role="menuitemradio" aria-checked="true">GPT-6 Astra</div><div role="menuitem"><span>6 Astra High</span><div data-model-reasoning-effort-slider role="slider" aria-valuemin="0" aria-valuemax="4" aria-valuenow="2">slider</div></div>';
      document.body.appendChild(menu);
    });
    const observed = await page.evaluate(`(${collectSentraUiIdentity.toString()})()`);
    expect(observed.provider_selection.model).toBe('gpt-6');
    expect(observed.provider_selection.effort).toBe('high');
    expect(observed.provider_selection.selection_verified).toBe(true);
    await page.evaluate(() => { document.querySelector('[role="menuitemradio"]')!.textContent = 'GPT-5.6 Sol'; });
    expect((await page.evaluate(`(${collectSentraUiIdentity.toString()})()`)).provider_selection.selection_verified).toBe(false);
    await page.evaluate(() => { (document.querySelector('[role="slider"]') as HTMLElement).style.display = 'none'; });
    expect((await page.evaluate(`(${collectSentraUiIdentity.toString()})()`)).provider_selection.model).toBeNull();
  } finally { await context.close(); }
});

test('receipt ACK cannot hide document replacement during its HTTP await', async () => {
  const { page, context } = await pageFixture();
  const send = authority([]);
  const durable = submission(async (phase: string, data: any) => {
    const ack = await send(phase, data);
    if (phase === 'receipt') await page.evaluate(() => { (globalThis as any).__SENTRA_WEB_DOCUMENT__.identity_epoch = 'c'.repeat(32); });
    return ack;
  });
  try {
    await expect(physicalSend(page, durable)).rejects.toThrow('sentra_document_changed');
    expect(await page.evaluate(() => (globalThis as any).sendClicks)).toBe(1);
    await expect(durable.answer(page, true)).rejects.toThrow('sentra_answer_without_receipt');
  } finally { await context.close(); }
});

test('complete ACK cannot hide a changed physical assistant body during its HTTP await', async () => {
  const { page, context } = await pageFixture();
  const send = authority([]);
  const durable = submission(async (phase: string, data: any) => {
    if (phase !== 'answer') return send(phase, data);
    await page.evaluate(() => { (globalThis as any).fixtureMessages[1].content.parts = ['Changed during final ACK']; });
    return { ok: true, state: 'ANSWERED', job_id: data.request_id, answer_message_id: data.message_id, answer_revision: data.revision };
  });
  try {
    await physicalSend(page, durable);
    await page.evaluate(() => { (globalThis as any).fixtureMessages.push({ id: 'assistant-fixture', author: { role: 'assistant' },
      parent_id: 'message-fixture', content: { parts: ['Final observed content'] } }); });
    await expect(durable.answer(page, true)).rejects.toThrow('sentra_final_answer_changed_during_ack');
  } finally { await context.close(); }
});
async function pageFixture() {
  const context = await browser.newContext();
  await context.route('**/*', (route: any) => route.fulfill({ status: 200, contentType: 'text/html',
    body: '<form><div id="prompt-textarea" contenteditable="true"></div><button data-testid="send-button" type="button">Send</button></form><section data-message-id="anchor-fixture"></section>' }));
  const page = await context.newPage();
  await page.goto('https://chatgpt.com/c/conversation-fixture');
  await page.evaluate(({ identity, prompt }: any) => {
    (globalThis as any).__SENTRA_WEB_DOCUMENT__ = identity;
    const root: any = { tag: 3, memoizedProps: {}, stateNode: {} };
    root.stateNode.current = root;
    const child: any = { tag: 0, memoizedProps: { conversationId: 'conversation-fixture', messages: [] }, return: root };
    root.child = child;
    (document.querySelector('section') as any).__reactFiber$fixture = child;
    (globalThis as any).fixtureMessages = child.memoizedProps.messages;
    (globalThis as any).sendClicks = 0;
    document.querySelector('button')!.addEventListener('click', () => {
      (globalThis as any).sendClicks++;
      child.memoizedProps.messages.push({ id: 'message-fixture', author: { role: 'user' },
        metadata: { request_id: 'provider-request-fixture' }, content: { parts: [prompt] } });
    });
  }, { identity, prompt: PROMPT });
  return { page, context };
}
function authority(calls: any[], tweak?: (phase: string, data: any) => any) {
  return async (phase: string, data: any) => {
    calls.push({ phase, data });
    const response = tweak?.(phase, data);
    if (response !== undefined) return response;
    return phase === 'receipt' ? { ok: true, state: 'SENT', request_id: 'intent-request-fixture', message_id: data.message_id }
      : { ...data, prompt: undefined, ok: true, state: phase === 'preflight' ? 'READY' : 'SENDING',
          request_id: 'intent-request-fixture', account_verified: true };
  };
}
function submission(transport: any, index = 0) {
  return new SentraWebSubmission({ sentraCapability: 'stc_' + 'x'.repeat(48), traceId: 'trace-fixture' },
    index, PROMPT, 'gpt-6', 'high', identity.surface_id, 0, transport);
}
async function physicalSend(page: any, durable: any) {
  const worker = Object.create(ChatGptBrowserWorker.prototype);
  worker.activeComposer = async () => page.locator('#prompt-textarea');
  worker.waitForSubmissionAcceptedWithRecovery = async () => 'observed-user-turn';
  return worker.sendAttachedPrompt(page, {}, undefined, undefined, undefined,
    { onSendActivated: () => durable.authorize(page, async () => {}) }, undefined, undefined, durable);
}
test('managed legacy and durable flags cannot silently downgrade or activate from truthy strings', () => {
  const parsed: any = { _rawBody: { client_metadata: { sentra_managed: true, sentra_turn_capability: 'stc_' + 'x'.repeat(48) } } };
  expect(sentraDurableWeb(parsed)).toBe(false);
  parsed._rawBody.client_metadata.sentra_durable_web = 'true';
  expect(sentraDurableWeb(parsed)).toBe(false);
  parsed._rawBody.client_metadata.sentra_durable_web = true;
  expect(sentraDurableWeb(parsed)).toBe(true);
  delete parsed._rawBody.client_metadata.sentra_turn_capability;
  expect(() => sentraDurableWeb(parsed)).toThrow();
});
test('real BrowserWorker Send + real DOM committed React + loopback HTTP receipt', async () => {
  const calls: any[] = [];
  const server = Bun.serve({ hostname: '127.0.0.1', port: 0, async fetch(request) {
    expect(request.headers.get('authorization')).toBe('Bearer isolated-fixture');
    const data: any = await request.json();
    const phase = new URL(request.url).pathname.split('browser-')[1]!;
    calls.push({ phase, data });
    if (phase === 'preflight') expect(createHash('sha256').update(data.prompt).digest('hex')).toBe(data.prompt_sha256);
    return Response.json(phase === 'receipt'
      ? { ok: true, state: 'SENT', request_id: data.request_id, message_id: data.message_id }
      : { ...data, prompt: undefined, request_id: 'intent-request-fixture', ok: true,
          account_verified: true, state: phase === 'preflight' ? 'READY' : 'SENDING' });
  } });
  const previous = [process.env.SENTRA_TURN_AUTHORITY_URL, process.env.SENTRA_TURN_AUTHORITY_TOKEN];
  process.env.SENTRA_TURN_AUTHORITY_URL = `http://127.0.0.1:${server.port}`;
  process.env.SENTRA_TURN_AUTHORITY_TOKEN = 'isolated-fixture';
  const { page, context } = await pageFixture();
  try {
    const durable = new SentraWebSubmission({ sentraCapability: 'stc_' + 'x'.repeat(48), traceId: 'trace-fixture' }, 0, PROMPT, 'gpt-6', 'high', identity.surface_id, 0);
    await physicalSend(page, durable);
    expect(calls.map(call => call.phase)).toEqual(['preflight', 'sending', 'receipt']);
    expect(calls[2].data.observed_request_id).toBe('provider-request-fixture');
    expect(calls[2].data.prompt_sha256).toBe(SHA);
    expect(calls[2].data.prompt).toBeUndefined();
    expect(await page.evaluate(() => (globalThis as any).sendClicks)).toBe(1);
    await expect(physicalSend(page, durable)).rejects.toThrow('already_attempted');
    expect(await page.evaluate(() => (globalThis as any).sendClicks)).toBe(1);
  } finally {
    await context.close(); server.stop(true);
    [process.env.SENTRA_TURN_AUTHORITY_URL, process.env.SENTRA_TURN_AUTHORITY_TOKEN] = previous;
  }
});
for (const scenario of ['bad-ack', 'account-unknown', 'reload', 'approval', 'lost-sending-ack', 'bad-fingerprint', 'model-change']) {
  test(`${scenario} prevents physical Send, never retries or falls back`, async () => {
    const { page, context } = await pageFixture();
    const calls: any[] = [];
    let selections = 0;
    const durable = submission(authority(calls, (phase, data) => {
      if (scenario === 'bad-ack') return { ok: false };
      if (scenario === 'account-unknown') return { ...data, ok: true, state: 'READY', request_id: 'intent-request-fixture', account_verified: false };
      if (scenario === 'lost-sending-ack' && phase === 'sending') throw Error('ACK lost after fence');
      if (scenario === 'bad-fingerprint' && phase === 'sending') return { ...data, ok: true, state: 'SENDING', request_id: 'intent-request-fixture', prompt_sha256: '0'.repeat(64) };
    }));
    const verify = async () => {
      selections++;
      if (scenario === 'reload' && selections === 2) await page.reload();
      if (scenario === 'approval' && selections === 2) await page.evaluate(() => {
        const approval = document.createElement('div'); approval.dataset.testid = 'approval-card'; document.body.appendChild(approval);
      });
      if (scenario === 'model-change' && selections === 3) throw Error('model no longer high');
    };
    const worker = Object.create(ChatGptBrowserWorker.prototype);
    worker.activeComposer = async () => page.locator('#prompt-textarea');
    try {
      await expect(worker.sendAttachedPrompt(page, {}, undefined, undefined, undefined,
        { onSendActivated: () => durable.authorize(page, verify) }, undefined, undefined, durable)).rejects.toThrow();
      expect(await page.evaluate(() => (globalThis as any).sendClicks || 0)).toBe(0);
      await expect(durable.authorize(page, verify)).rejects.toThrow();
      expect(calls.filter(call => call.phase === 'sending').length).toBeLessThanOrEqual(1);
    } finally { await context.close(); }
  });
}
test('lost receipt ACK means one click and one receipt attempt, no fallback after reload/restart', async () => {
  const { page, context } = await pageFixture(); const calls: any[] = [];
  const durable = submission(authority(calls, phase => { if (phase === 'receipt') throw Error('ACK lost'); }));
  try {
    await expect(physicalSend(page, durable)).rejects.toThrow('ACK lost');
    await expect(durable.receipt(page)).rejects.toThrow('unconfirmed');
    await durable.failure();
    expect(calls.filter(call => call.phase === 'receipt')).toHaveLength(1);
    expect(calls.at(-1).data.may_have_sent).toBe(true);
    expect(await page.evaluate(() => (globalThis as any).sendClicks)).toBe(1);
  } finally { await context.close(); }
});
test('stale React branch, ambiguous request, old same-text message never prove a send', async () => {
  const { page, context } = await pageFixture(); const durable = submission(authority([]));
  try {
    await page.evaluate((prompt: string) => (globalThis as any).fixtureMessages.push({ id: 'old-message-fixture',
      author: { role: 'user' }, metadata: { request_id: 'old-request-fixture' }, content: { parts: [prompt] } }), PROMPT);
    await durable.authorize(page, async () => {});
    await expect(durable.receipt(page)).rejects.toThrow('message_unconfirmed');
    await page.locator('button').click();
    await page.evaluate(() => (globalThis as any).fixtureMessages.push({ id: 'duplicate-fixture', author: { role: 'user' },
      metadata: { request_id: 'provider-request-fixture' }, content: { parts: ['different'] } }));
    await expect(page.evaluate(readSentraPageEvidence)).rejects.toThrow('message_conflict');
  } finally { await context.close(); }
});
test('assistant streaming is tied to real message/parent, monotonic revisions and final ACK', async () => {
  const { page, context } = await pageFixture(); const calls: any[] = [];
  const durable = submission(authority(calls, (phase, data) => phase === 'answer'
    ? { ok: true, state: data.complete ? 'ANSWERED' : 'ANSWERING', job_id: data.request_id,
        answer_message_id: data.message_id, answer_revision: data.revision } : undefined));
  try {
    await physicalSend(page, durable);
    await expect(durable.answer(page, true)).rejects.toThrow('assistant_unconfirmed');
    await page.evaluate(() => (globalThis as any).fixtureMessages.push({ id: 'assistant-message-fixture',
      parent_id: 'message-fixture', author: { role: 'assistant' }, content: { parts: ['Partial'] } }));
    await durable.answer(page, false);
    await durable.answer(page, false); // unchanged body emits no duplicate frame
    await page.evaluate(() => (globalThis as any).fixtureMessages.at(-1).content.parts = ['Completed']);
    await durable.answer(page, false);
    await durable.answer(page, true);
    await durable.answer(page, true); // exact final locally observed; no second POST
    const frames = calls.filter(call => call.phase === 'answer');
    expect(frames.map(frame => frame.data.revision)).toEqual([1, 2, 3]);
    expect(frames.map(frame => frame.data.complete)).toEqual([false, false, true]);
    expect(frames[2].data.message_id).toBe('assistant-message-fixture');
    expect(frames[2].data.parent_user_message_id).toBe('message-fixture');
    expect(frames[2].data.observed_request_id).toBe('provider-request-fixture');
    await page.evaluate(() => (globalThis as any).fixtureMessages.at(-1).content.parts = ['Changed after complete']);
    await expect(durable.answer(page, true)).rejects.toThrow('changed_after_complete');
  } finally { await context.close(); }
});
test('wrong assistant ACK and cross-request message cannot declare ANSWERED', async () => {
  const { page, context } = await pageFixture();
  const durable = submission(authority([], phase => phase === 'answer' ? { ok: true, state: 'ANSWERED', job_id: 'other-intent' } : undefined));
  try {
    await physicalSend(page, durable);
    await page.evaluate(() => (globalThis as any).fixtureMessages.push({ id: 'assistant-message-fixture',
      author: { role: 'assistant' }, metadata: { request_id: 'another-provider-request' }, content: { parts: ['wrong account'] } }));
    await expect(durable.answer(page, true)).rejects.toThrow('assistant_unconfirmed');
    await page.evaluate(() => (globalThis as any).fixtureMessages.at(-1).metadata.request_id = 'provider-request-fixture');
    await expect(durable.answer(page, true)).rejects.toThrow('answer_ack_invalid');
  } finally { await context.close(); }
});
