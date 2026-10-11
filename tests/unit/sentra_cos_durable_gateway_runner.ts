// Real production Worker + isolated Chromium + real temporary Gateway HTTP.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const config = JSON.parse(readFileSync(process.env.SENTRA_GATEWAY_QA_CONFIG!, 'utf8'));
const { SentraWebSubmission, ChatGptBrowserWorker } = await import(resolve(config.tree, 'src/adapters/chatgpt-web/browser-worker.ts'));
const { chromium } = await import(resolve(config.tree, 'node_modules/playwright-core/index.mjs'));
process.env.SENTRA_TURN_AUTHORITY_URL = config.endpoint;
process.env.SENTRA_TURN_AUTHORITY_TOKEN = config.token;
const browser = await chromium.launch({ headless: true, executablePath: config.chromium });
let hostServer: any, hostTab: any;
try {
  const context = await browser.newContext();
  await context.route('**/*', route => route.fulfill({ contentType: 'text/html', body:
    '<form><div id="prompt-textarea" contenteditable="true"></div><button data-testid="send-button">Send</button></form><section data-message-id="anchor"></section>' }));
  const page = await context.newPage();
  await page.goto('https://chatgpt.com/c/conversation-fixture');
  await page.evaluate((config: any) => {
    (globalThis as any).__SENTRA_WEB_DOCUMENT__ = config.identity;
    const root: any = { tag: 3, stateNode: {}, memoizedProps: {} }; root.stateNode.current = root;
    const messages: any[] = [];
    const fiber: any = { memoizedProps: { conversationId: 'conversation-fixture', messages }, return: root }; root.child = fiber;
    (document.querySelector('section') as any).__reactFiber$fixture = fiber;
    (globalThis as any).messages = messages;
    (globalThis as any).clicks = 0;
    document.querySelector('button')!.addEventListener('click', event => {
      event.preventDefault(); (globalThis as any).clicks++;
      messages.push({ id: 'message-fixture', author: { role: 'user' }, metadata: { request_id: 'provider-request-fixture' }, content: { parts: [config.prompt] } });
    });
  }, config);
  if (config.independent_host) {
    // Actual Host/control-server/reader. Only the Electron WebContents interface
    // is bridged to this isolated Chromium page; no caller body/IDs enter reader.
    const req = createRequire(resolve(config.tree, 'launcher/package.json'));
    const { BrowserHost, collectSentraCommittedMessages, collectSentraUiIdentity } = req('./electron/browser-host.cjs');
    const { BrowserControlServer } = req('./electron/control-server.cjs');
    const hash = (f: any) => createHash('sha256').update(f.toString()).digest('hex');
    hostTab = { id: 'tab-one', traceId: 'trace-fixture', surfaceId: config.identity.surface_id,
      status: 'running', interactionMode: 'automatic', sentraDocument: config.identity,
      view: { webContents: { isDestroyed: () => page.isClosed(), getURL: () => page.url(),
        executeJavaScript: (source: string) => page.evaluate(source) } } };
    const host = Object.assign(Object.create(BrowserHost.prototype), { turnTabs: new Map([[hostTab.id, hostTab]]),
      profile: 'development', partition: 'isolated-chromium-qa', authenticationRevision: config.host_authentication_revision });
    hostServer = new BrowserControlServer({ logger: { info() {}, warn() {}, error() {} },
      getBrowserHost: () => host, getPreferences: () => ({}) });
    await hostServer.start();
    const physical = JSON.parse(readFileSync(config.browser_descriptor_path, 'utf8'));
    const cdp = await context.newCDPSession(page);
    const { targetInfo } = await cdp.send('Target.getTargetInfo'); await cdp.detach();
    physical.pid = process.pid;
    physical.control = hostServer.descriptor();
    physical.sentraMessageCollector = { id: 'sentra-committed-message-v1', sha256: hash(collectSentraCommittedMessages) };
    physical.sentraIdentityCollector = { id: 'sentra-committed-account-menu-v1', sha256: hash(collectSentraUiIdentity), verified: false };
    physical.surfaceTargets[config.identity.surface_id] = targetInfo.targetId;
    Object.assign(physical.sentraTabs[0], { documentId: config.identity.document_id,
      identityEpoch: config.identity.identity_epoch, interactionMode: 'automatic', lastHeartbeatAt: Date.now() });
    // Private descriptor stays in pytest's disposable directory; never print bearer.
    writeFileSync(config.browser_descriptor_path, JSON.stringify(physical), { mode: 0o600 });
    const start = await fetch(config.endpoint + '/internal/turn/browser-start', { method: 'POST',
      headers: { authorization: 'Bearer ' + config.token, 'content-type': 'application/json' },
      body: JSON.stringify({ capability: config.capability, traceId: 'trace-fixture' }) });
    if (start.status !== 200) throw Error('isolated physical browser-start rejected ' + start.status);
  }
  const durable = new SentraWebSubmission({ sentraCapability: config.capability, traceId: 'trace-fixture' },
    0, config.prompt, 'gpt-6', 'high', config.identity.surface_id, 0);
  const worker = Object.create(ChatGptBrowserWorker.prototype);
  worker.activeComposer = async () => page.locator('#prompt-textarea');
  worker.waitForSubmissionAcceptedWithRecovery = async () => 'observed-user-fixture';
  await worker.sendAttachedPrompt(page, {}, undefined, undefined, undefined,
    { onSendActivated: () => durable.authorize(page, async () => {}) }, undefined, undefined, durable);
  if (await page.evaluate(() => (globalThis as any).clicks) !== 1) throw Error('physical send count differs');
  await page.evaluate(() => { (globalThis as any).messages.push({ id: 'assistant-fixture', author: { role: 'assistant' },
    parent_id: 'message-fixture', metadata: { revision: 4 }, status: 'in_progress', content: { parts: ['Partial synthetic answer'] } }); });
  await durable.answer(page, false);
  await page.evaluate(() => { const m = (globalThis as any).messages[1]; m.content.parts = ['Final synthetic answer'];
    m.metadata.revision = 5; m.status = 'finished_successfully'; });
  await durable.answer(page, true);
  if (config.independent_host) {
    const observations = [...hostTab.sentraMessageObservations.values()] as any[];
    if (observations.length !== 2 || !observations.some(m => m.role === 'user' && m.revision === 1)
      || !observations.some(m => m.role === 'assistant' && m.revision === 2 && m.parent === 'message-fixture')) {
      throw Error('independent Host did not observe exact user and final assistant revisions');
    }
    console.log('SENTRA_WORKER_GATEWAY_HOST_QA_ANSWERED');
  }
  console.log('SENTRA_WORKER_GATEWAY_QA_ANSWERED');
  await context.close();
} finally { await hostServer?.close(); await browser.close(); }
