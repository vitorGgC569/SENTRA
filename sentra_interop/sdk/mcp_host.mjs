/** Original SENTRA client host for the pinned official TypeScript SDK.
 * No auto-fulfilment, tool retry, stdio sibling probe, or model sampling.
 * Every network fetch asks the enclosing Python central effect for a fence.
 */
import readline from 'node:readline';
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';

let client, transport, subscription;
let sequence = 0;
const pending = new Map();
const active = new Map();
const maxFrame = 65536;
function output(packet) {
  const line = JSON.stringify(packet);
  if (Buffer.byteLength(line) > maxFrame) throw new Error('frame limit');
  process.stdout.write(line + '\n');
}
async function hostRequest(method, params) {
  const id = 'host-' + (++sequence);
  return await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error('host deadline')); }, 120000);
    pending.set(id, { resolve, reject, timeout });
    output({ jsonrpc: '2.0', id, method, params });
  });
}
function notify(method, params = {}) { output({ jsonrpc: '2.0', method, params }); }
async function connect(config) {
  if (client) throw new Error('already connected');
  const url = new URL(config.endpoint);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.hash || url.search ||
      url.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) throw new Error('endpoint rejected');
  const mode = config.protocol_version === '2026-07-28' ? { pin: config.protocol_version } : 'legacy';
  if (!['2025-06-18', '2025-11-25', '2026-07-28'].includes(config.protocol_version)) throw new Error('revision rejected');
  client = new Client({ name: 'sentra-interop', version: '1.0.0' }, {
    versionNegotiation: { mode, probe: { maxRetries: 0, timeoutMs: 10000 } },
    supportedProtocolVersions: [config.protocol_version],
    inputRequired: { autoFulfill: false, maxRounds: 1 },
    capabilities: config.elicitation ? { elicitation: { form: {} } } : {}
  });
  for (const name of ['notifications/tools/list_changed', 'notifications/prompts/list_changed',
                       'notifications/resources/list_changed', 'notifications/resources/updated']) {
    client.setNotificationHandler(name, notification => { notify(name, notification.params); });
  }
  if (config.elicitation) client.setRequestHandler('elicitation/create', async request =>
    await hostRequest('elicitation/create', request.params));
  const fencedFetch = async (input, init = {}) => {
    const target = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
    if (target.origin !== url.origin || target.pathname !== url.pathname) throw new Error('destination changed');
    await hostRequest('sentra/checkpoint', {});
    return await fetch(input, { ...init, redirect: 'error' });
  };
  transport = new StreamableHTTPClientTransport(url, {
    fetch: fencedFetch,
    requestInit: config.token ? { headers: { Authorization: 'Bearer ' + config.token } } : undefined,
    sessionId: config.session_id || undefined,
    protocolVersion: config.session_id ? config.protocol_version : undefined,
    onInsufficientScope: 'throw',
    maxStepUpRetries: 0,
    reconnectionOptions: { maxRetries: 0, initialReconnectionDelay: 1000, maxReconnectionDelay: 1000, reconnectionDelayGrowFactor: 1 }
  });
  if (config.session_id) {
    if (config.protocol_version !== '2026-07-28' || !config.discovery) throw new Error('session reconciliation required');
    await client.connect(transport, { timeout: 15000, prior: { kind: 'modern', discover: config.discovery } });
  } else await client.connect(transport, { timeout: 15000 });
  return { protocolVersion: client.getNegotiatedProtocolVersion(), capabilities: client.getServerCapabilities() || {},
           era: client.getProtocolEra(), sessionId: transport.sessionId || null, discovery: client.getDiscoverResult() || null };
}
async function invoke(packet, signal) {
  const p = packet.params || {};
  const options = { timeout: 120000, signal, allowInputRequired: true };
  if (packet.method === 'sentra/connect') return await connect(p);
  if (!client) throw new Error('not connected');
  switch (packet.method) {
    case 'tools/list': return await client.listTools(p, options);
    case 'tools/call': return await client.callTool(p, options);
    case 'resources/list': return await client.listResources(p, options);
    case 'resources/templates/list': return await client.listResourceTemplates(p, options);
    case 'resources/read': return await client.readResource(p, options);
    case 'prompts/list': return await client.listPrompts(p, options);
    case 'prompts/get': return await client.getPrompt(p, options);
    case 'resources/subscribe': return await client.subscribeResource(p, options);
    case 'resources/unsubscribe': return await client.unsubscribeResource(p, options);
    case 'sentra/listen':
      if (subscription) throw new Error('already listening');
      subscription = await client.listen(p, options);
      subscription.closed.then(reason => { subscription = undefined; notify('notifications/subscription/closed', { reason }); });
      return { honoredFilter: subscription.honoredFilter };
    case 'sentra/unlisten':
      if (subscription) await subscription.close();
      subscription = undefined;
      return {};
    default: throw new Error('method rejected');
  }
}
const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on('line', line => {
  if (Buffer.byteLength(line) > maxFrame) { process.exitCode = 1; lines.close(); return; }
  let packet;
  try { packet = JSON.parse(line); } catch { process.exitCode = 1; lines.close(); return; }
  if (packet.jsonrpc !== '2.0') { process.exitCode = 1; lines.close(); return; }
  if (pending.has(packet.id) && !packet.method) {
    const waiter = pending.get(packet.id); clearTimeout(waiter.timeout); pending.delete(packet.id);
    packet.error ? waiter.reject(new Error('host rejected')) : waiter.resolve(packet.result);
    return;
  }
  if (packet.method === 'notifications/cancelled') { active.get(packet.params?.requestId)?.abort(); return; }
  if (!Object.hasOwn(packet, 'id')) return;
  const controller = new AbortController(); active.set(packet.id, controller);
  invoke(packet, controller.signal).then(result => output({ jsonrpc: '2.0', id: packet.id, result }),
    () => output({ jsonrpc: '2.0', id: packet.id, error: { code: -32000, message: 'SDK request failed; reconcile before retry' } }))
    .finally(() => active.delete(packet.id));
});
lines.on('close', async () => {
  for (const controller of active.values()) controller.abort();
  for (const waiter of pending.values()) { clearTimeout(waiter.timeout); waiter.reject(new Error('host closed')); }
  try { await client?.close(); } finally { process.exit(); }
});
