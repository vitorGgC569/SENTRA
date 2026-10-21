'use strict';
// Setup runs the exact production display against two disposable loopback servers.
// No user account, existing profile, external URL or installed Canvas is accessed.
const { app, BrowserWindow, session } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const assert = require('node:assert/strict');
const argument = process.argv.find(value => /^--sentra-ticket=[0-9a-f]{32}$/.test(value));
if (!argument) app.exit(2);
const ticket = path.join(os.tmpdir(), 'sentra-electron-' + argument.slice(16) + '.json');
const stat = fs.lstatSync(ticket);
assert.ok(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 1024);
const handoff = JSON.parse(fs.readFileSync(ticket, 'utf8'));
assert.match(handoff.probe_nonce, /^[0-9a-f]{32}$/);
const directory = path.resolve(handoff.probe_directory);
assert.equal(path.dirname(directory).toLowerCase(), path.resolve(os.tmpdir()).toLowerCase());
assert.match(path.basename(directory), /^sentra-display-probe-[A-Za-z0-9_-]+$/);
assert.ok(fs.lstatSync(directory).isDirectory() && !fs.lstatSync(directory).isSymbolicLink());
assert.ok(Number.isInteger(handoff.probe_foreign_port) && handoff.probe_foreign_port > 0 &&
  handoff.probe_foreign_port <= 65535 && handoff.probe_foreign_port !== handoff.port);
BrowserWindow.prototype.show = function () {}; // Keep only this disposable probe hidden.
const timer = setTimeout(() => app.exit(5), 20000);
let checking = false;
app.on('web-contents-created', (_event, contents) => {
  contents.once('did-finish-load', async () => {
    if (checking) return;
    checking = true;
    try {
      const prefs = contents.getLastWebPreferences();
      const location = new URL(contents.getURL());
      assert.equal(location.origin, 'http://127.0.0.1:' + handoff.port);
      assert.equal(location.pathname, '/desktop.html');
      const observed = await contents.executeJavaScript(`(() => ({
        nonce: document.querySelector('meta[name="sentra-display-probe"]')?.content,
        node: typeof require === 'undefined' && typeof process === 'undefined'
      }))()`);
      assert.equal(observed.nonce, handoff.probe_nonce);
      const windows = BrowserWindow.getAllWindows().length;
      await contents.executeJavaScript('window.open("about:blank", "_blank"); true');
      await new Promise(resolve => setImmediate(resolve));
      const escaped = await contents.executeJavaScript(
        `fetch('http://127.0.0.1:${handoff.probe_foreign_port}/probe').then(() => true, () => false)`);
      const checks = {
        renderer_loaded: true, node_isolated: observed.node === true,
        context_isolated: prefs.contextIsolation === true, sandbox: prefs.sandbox === true,
        web_security: prefs.webSecurity === true,
        ephemeral_session: !contents.session.isPersistent() && contents.session !== session.defaultSession,
        popup_blocked: BrowserWindow.getAllWindows().length === windows,
        network_fenced: escaped === false,
      };
      assert.ok(Object.values(checks).every(value => value === true));
      assert.equal(fs.existsSync(ticket), false); // Production bootstrap consumed it.
      const pending = path.join(directory, 'result.tmp');
      const handle = fs.openSync(pending, 'wx');
      try {
        fs.writeFileSync(handle, JSON.stringify({schema: 1, nonce: handoff.probe_nonce, ...checks}));
        fs.fsyncSync(handle);
      } finally { fs.closeSync(handle); }
      fs.renameSync(pending, path.join(directory, 'result.json'));
      clearTimeout(timer);
      app.quit();
    } catch { clearTimeout(timer); app.exit(6); }
  });
});
require('./main.cjs');
