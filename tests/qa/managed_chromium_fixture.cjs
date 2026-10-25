// Hidden real Chromium; HTTPS is intercepted locally. Never uses a user account.
'use strict';
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { app, BrowserWindow, session } = require('electron');
const [fixtureRoot, packagedApp] = process.argv.slice(2);
app.setPath('userData', path.join(fixtureRoot, 'profile'));
app.commandLine.appendSwitch('disable-gpu');
app.whenReady().then(async () => {
  const { command } = require(path.join(packagedApp, 'electron/sentra-setup-host.cjs'));
  const partition = 'persist:sentra-setup-fixture';
  const browserSession = session.fromPartition(partition);
  let requests = 0;
  await browserSession.protocol.handle('https', () => {
    requests++;
    return new Response('<!doctype html><html><body><dialog open><label>Name<input id="name"></label></dialog><code>tunnel_fixture12345678</code></body></html>',
      { headers: { 'content-type': 'text/html' } });
  });
  const native = new BrowserWindow({ show: false, width: 900, height: 700,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  const window = new EventEmitter();
  Object.assign(window, { contentView: native.contentView, isVisible: () => false,
    isDestroyed: () => native.isDestroyed(), show() {}, focus() {}, hide() {} });
  const host = { window, partition, turnTabs: new Map(), ready: async () => {},
    currentOperation() { return this.manualOperation; }, show() {}, hide() {},
    syncViewVisibility() { if (this.sentraSetupView) {
      this.sentraSetupView.setBounds({ x: 0, y: 0, width: 900, height: 650 });
      this.sentraSetupView.setVisible(true);
    } } };
  const call = body => command(host, { action: 'setup', ...body });
  const tab = await call({ operation: 'open' });
  await call({ operation: 'navigate', tab, url: 'https://platform.openai.com/settings/organization/tunnels' });
  const tunnels = await call({ operation: 'extract', tab, kind: 'tunnels' });
  assert.ok(tunnels.includes('tunnel_fixture12345678'));
  const steps = [{ kind: 'css', selector: '#name' }];
  await call({ operation: 'dom', tab, dom_action: 'fill', steps, value: 'SENTRA fixture' });
  await browserSession.cookies.set({ url: 'https://chatgpt.com', name: 'sentra-fixture', value: 'synthetic-only' });
  await call({ operation: 'close', tab });
  await assert.rejects(call({ operation: 'url', tab }), /setup_session_unavailable/);
  const next = await call({ operation: 'open' });
  await call({ operation: 'navigate', tab: next, url: 'https://chatgpt.com/plugins' });
  await call({ operation: 'dom', tab: next, dom_action: 'fill', steps, value: 'SENTRA' });
  assert.equal(await call({ operation: 'dom', tab: next, dom_action: 'input_value', steps }), 'SENTRA');
  await assert.rejects(call({ operation: 'navigate', tab: next, url: 'https://example.com/' }), /setup_origin_denied/);
  assert.equal((await browserSession.cookies.get({ name: 'sentra-fixture' }))[0].value, 'synthetic-only');
  await call({ operation: 'close', tab: next });
  const report = { ok: true, packaged_module_loaded: true, real_chromium: true,
    network_intercepted: true, fixture_requests: requests, profile_retained: true,
    platform_extraction: true, chatgpt_form_filled: true, foreign_origin_denied: true,
    stale_session_denied: true, visible_windows: BrowserWindow.getAllWindows().filter(w => w.isVisible()).length,
    provider_login_tested: false, product_installation_modified: false };
  assert.equal(report.visible_windows, 0);
  fs.writeFileSync(path.join(fixtureRoot, 'result.json'), JSON.stringify(report, null, 2));
  native.destroy(); app.exit(0);
}).catch(error => {
  fs.writeFileSync(path.join(fixtureRoot, 'failure.txt'), error.stack || String(error));
  app.exit(2);
});
