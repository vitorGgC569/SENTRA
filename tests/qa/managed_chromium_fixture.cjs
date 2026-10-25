// Hidden real Chromium; HTTPS is intercepted locally. Never uses a user account.
'use strict';
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { app, BrowserWindow, session } = require('electron');
const [fixtureRoot, packagedApp] = process.argv.slice(2);
app.setPath('userData', path.join(fixtureRoot, 'profile'));
app.commandLine.appendSwitch('disable-gpu');
app.whenReady().then(async () => {
  const { command } = require(path.join(packagedApp, 'electron/sentra-setup-host.cjs'));
  const partition = 'persist:codex-web-gpt-chatgpt'; // Private userData above; no real account profile.
  const browserSession = session.fromPartition(partition);
  let requests = 0;
  let loginRedirect = true;
  await browserSession.protocol.handle('https', request => {
    requests++;
    if (loginRedirect && request.url.includes('/settings/organization/tunnels')) {
      loginRedirect = false;
      return Response.redirect('https://platform.openai.com/login', 302);
    }
    return new Response('<!doctype html><html><body><dialog open><label>Name<input id="name"></label></dialog><code>tunnel_fixture12345678</code></body></html>',
      { headers: { 'content-type': 'text/html' } });
  });
  const native = new BrowserWindow({ show: false, width: 900, height: 700,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  native.show = () => {}; native.focus = () => {};
  const { BrowserHost } = require(path.join(packagedApp, 'electron/browser-host.cjs'));
  const host = new BrowserHost({ window: native, partition,
    descriptorPath: path.join(fixtureRoot, 'descriptor.json'), cdpPort: 0,
    helper: { executable: process.execPath, script: path.join(fixtureRoot, 'unused-helper.cjs') },
    loginWithPasskey: async () => { throw Error('fixture cannot perform a real login'); },
    logger: { info() {}, warn() {}, error() {} }, getConnectorName: () => 'SENTRA', getUseSavedChats: () => true });
  await host.ready();
  const call = body => command(host, { action: 'setup', ...body });
  const tab = await call({ operation: 'open' });
  assert.ok(host.sentraSetupView.getBounds().width >= native.getContentSize()[0], 'setup must fill the window before a browser panel was mounted');
  await call({ operation: 'navigate', tab, url: 'https://platform.openai.com/settings/organization/tunnels' });
  assert.equal(await call({ operation: 'url', tab }), 'https://platform.openai.com/login');
  await assert.rejects(call({ operation: 'dom', tab, dom_action: 'count', steps: [] }), /bridge_origin_changed/);
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
  const report = { ok: true, packaged_module_loaded: String(packagedApp).endsWith('.asar'), real_chromium: true,
    full_browser_host: true, setup_fills_window: true,
    network_intercepted: true, fixture_requests: requests, profile_retained: true,
    platform_extraction: true, platform_login_redirect: true, auth_page_dom_denied: true,
    chatgpt_form_filled: true, foreign_origin_denied: true,
    stale_session_denied: true, visible_windows: BrowserWindow.getAllWindows().filter(w => w.isVisible()).length,
    provider_login_tested: false, product_installation_modified: false };
  assert.equal(report.visible_windows, 0);
  fs.writeFileSync(path.join(fixtureRoot, 'result.json'), JSON.stringify(report, null, 2));
  host.destroy(); native.destroy(); app.exit(0);
}).catch(error => {
  fs.writeFileSync(path.join(fixtureRoot, 'failure.txt'), error.stack || String(error));
  app.exit(2);
});
