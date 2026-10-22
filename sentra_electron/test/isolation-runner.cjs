'use strict';
// Runs only in a disposable Electron process with a synthetic loopback Canvas.
const { app, BrowserWindow, session } = require('electron');
const assert = require('node:assert/strict');
const profileArgument = process.argv.find(value => value.startsWith('--user-data-dir='));
assert.ok(profileArgument, 'disposable test profile required');
app.setPath('userData', profileArgument.slice('--user-data-dir='.length));
BrowserWindow.prototype.show = function () {}; // keep the QA window hidden
const timer = setTimeout(() => { console.error('isolated Electron timed out'); app.exit(5); }, 20000);
app.on('web-contents-created', (_event, contents) => {
  contents.once('did-finish-load', async () => {
    try {
      const prefs = contents.getLastWebPreferences();
      assert.equal(prefs.nodeIntegration, false);
      assert.equal(prefs.contextIsolation, true);
      assert.equal(prefs.sandbox, true);
      assert.equal(prefs.webSecurity, true);
      assert.equal(contents.session.isPersistent(), false);
      assert.notEqual(contents.session, session.defaultSession);
      assert.equal(await contents.executeJavaScript('typeof require'), 'undefined');
      assert.equal(await contents.executeJavaScript('typeof process'), 'undefined');
      const windows = BrowserWindow.getAllWindows().length;
      await contents.executeJavaScript('window.open("https://example.invalid", "_blank"); true');
      assert.equal(BrowserWindow.getAllWindows().length, windows);
      require('node:fs').writeFileSync(require('node:path').join(app.getPath('userData'), 'isolation-result.json'),
        JSON.stringify({ isolated: true, popupBlocked: true }));
      clearTimeout(timer); app.exit(0); // This disposable probe never leaves a tray process running.
    } catch (error) { console.error(error.message); clearTimeout(timer); app.exit(6); }
  });
});
require('../main.cjs'); // exact production bootstrap, ticket/policy/session/BrowserWindow
