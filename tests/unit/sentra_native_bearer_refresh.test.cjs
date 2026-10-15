'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../../sentra_canvas/desktop_ui/src/api.js'), 'utf8');
let serial = 0;
async function setup({ fetchImpl, native = null }) {
  const stored = new Map();
  globalThis.location = { hash: '#token=old-window-token', pathname: '/desktop.html', search: '' };
  globalThis.history = { replaceState: () => {} };
  globalThis.sessionStorage = {
    getItem: key => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value),
  };
  globalThis.window = { pywebview: native ? { api: native } : null };
  globalThis.fetch = fetchImpl;
  serial += 1;
  const mod = await import('data:text/javascript;charset=utf-8,' + encodeURIComponent(source) + '#case' + serial);
  return { mod, stored };
}

test('401 from rotated local bearer requests native reauth but NEVER replays a mutation', async () => {
  const sent = [];
  const navigations = [];
  const { mod } = await setup({
    fetchImpl: async (url, options) => {
      sent.push({ url, options });
      return { ok: false, status: 401, json: async () => ({ error: 'local bearer token required' }) };
    },
    native: { reauthorize: async () => { navigations.push('requested'); return { status: 'native_window_reloaded' }; } },
  });
  await assert.rejects(
    mod.api('/api/shell/bridge', { action: 'dot_vm_execute', arguments: { action: 'start' } }),
    /nenhuma operação foi reenviada/,
  );
  await Promise.resolve();
  assert.equal(sent.length, 1, 'must not retry or duplicate a side-effecting operation');
  assert.deepEqual(navigations, ['requested']);
  assert.equal(sent[0].options.headers.Authorization, 'Bearer old-window-token');
});

test('401 without native trusted bridge fails closed and does not retry', async () => {
  let calls = 0;
  const { mod } = await setup({
    fetchImpl: async () => { calls += 1; return { ok: false, status: 401, json: async () => ({ error: 'local bearer token required' }) }; },
  });
  await assert.rejects(mod.api('/api/workspaces'), /Reabra o aplicativo SENTRA atualizado/);
  assert.equal(calls, 1);
});

test('fresh fragment overwrites stale session credential when native window navigates', async () => {
  let header = '';
  const { mod, stored } = await setup({
    fetchImpl: async (url, options) => {
      header = options.headers.Authorization;
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
  });
  const result = await mod.api('/api/health');
  assert.equal(result.ok, true);
  assert.equal(header, 'Bearer old-window-token');
  assert.equal(stored.get('sentra_native_token'), 'old-window-token');
});
