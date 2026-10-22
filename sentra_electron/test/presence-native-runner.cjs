'use strict';
// Disposable native integration fixture. No installed profile, broker or account.
const { app, BrowserWindow, screen } = require('electron');
const http = require('node:http'), path = require('node:path'), fs = require('node:fs');
const assert = require('node:assert/strict');
const argument = process.argv.find(v => v.startsWith('--user-data-dir='));
assert.ok(argument);
const directory = argument.slice('--user-data-dir='.length);
app.setPath('userData', directory);
const output = path.join(directory, 'presence-result.json');
const deadline = setTimeout(() => { fs.writeFileSync(output, JSON.stringify({ error: 'native probe timeout' })); app.exit(5); }, 20000);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn) {
  for (let i = 0; i < 40; i++) { const value = await fn(); if (value) return value; await delay(50); }
  throw Error('native condition did not become true');
}
app.whenReady().then(async () => {
  const server = http.createServer((_req, res) => { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end('<!doctype html><title>SENTRA disposable presence validation</title><p>Local fixture only</p>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let owner, presence;
  try {
    const url = 'http://127.0.0.1:' + server.address().port + '/fixture';
    owner = new BrowserWindow({ show: false, webPreferences: {
      preload: path.join(__dirname, '../presence-preload.cjs'), nodeIntegration: false,
      contextIsolation: true, sandbox: true, partition: 'presence-test-' + process.pid,
    } });
    let island;
    presence = require('../presence-window.cjs').installPresenceWindow(owner, { ownerURL: url,
      onReady: window => { island = window; },
    });
    await owner.loadURL(url);
    await owner.webContents.executeJavaScript('window.seenActions=[];window.sentraDesktopPresence.onAction(value=>window.seenActions.push(value));true');
    const snapshot = { schema: 1, enabled: true, projectId: 'native-validation', projectName: 'Validação local · dados fictícios',
      connected: true, observedAt: Date.now(), decisions: 1,
      sessions: [{ dotId: 'qa-dot', name: 'Dot de validação', mascot: 'oxta', tone: 'idle', conversationId: 'qa-conversation' }], events: [] };
    presence.update(snapshot);
    await until(() => island && !island.webContents.isLoading());
    await until(() => island.webContents.executeJavaScript('!!document.querySelector(".di-capsule")'));
    await until(() => island.webContents.executeJavaScript('Math.abs(document.querySelector("#island").getBoundingClientRect().width-288)<.2 && Math.abs(document.querySelector("#island").getBoundingClientRect().height-32)<.2'));
    await island.webContents.executeJavaScript('document.querySelector(".di-capsule").click();true');
    await until(() => island.webContents.executeJavaScript('Math.abs(document.querySelector("#island").getBoundingClientRect().width-640)<.2 && Math.abs(document.querySelector("#island").getBoundingClientRect().height-160)<.2'));
    const originalGeometry = await island.webContents.executeJavaScript(`(() => {
      const shape=document.querySelector('#island'), style=getComputedStyle(shape);
      return {width:Math.round(shape.getBoundingClientRect().width),height:Math.round(shape.getBoundingClientRect().height),
        black:style.backgroundColor==='rgb(0, 0, 0)', topCorners:style.borderTopLeftRadius==='0px',
        cards:document.querySelectorAll('.overview .card').length, iconTabs:document.querySelectorAll('#header .tab').length};
    })()`);
    assert.equal(originalGeometry.black, true); assert.equal(originalGeometry.topCorners, true);
    assert.equal(originalGeometry.cards, 2); assert.equal(originalGeometry.iconTabs, 3);
    await island.webContents.executeJavaScript('window.sentraIsland.expand(false);true');
    await until(() => island.webContents.executeJavaScript('!!document.querySelector(".di-capsule")'));
    assert.equal(island.isAlwaysOnTop(), true);
    assert.equal(island.isVisible(), true);
    const monitors = [];
    for (const display of screen.getAllDisplays()) {
      presence.selectDisplay(display.id); await delay(80);
      const b = island.getBounds(), a = display.workArea;
      assert.ok(b.x >= a.x && b.y >= a.y && b.x + b.width <= a.x + a.width && b.y + b.height <= a.y + a.height);
      monitors.push({ width: a.width, height: a.height, scaleFactor: display.scaleFactor, contained: true });
    }
    owner.hide(); assert.equal(island.isVisible(), true);
    for (const action of ['conversation', 'canvas', 'decisions']) {
      await island.webContents.executeJavaScript(`window.sentraIsland.activate(${JSON.stringify(action)}, 'qa-dot');true`);
      await until(() => owner.webContents.executeJavaScript(`window.seenActions.some(value=>value.action===${JSON.stringify(action)})`));
    }
    await island.webContents.executeJavaScript('window.sentraIsland.activate("hide");true');
    await until(() => !island.isVisible());
    presence.show(); await until(() => island.isVisible());
    assert.equal(BrowserWindow.getAllWindows().length, 2);
    presence.update({ ...snapshot, connected: false, observedAt: 0 });
    await until(() => island.webContents.executeJavaScript('document.querySelector(".desktop-island")?.dataset.live === "false"'));
    presence.update({ ...snapshot, observedAt: Date.now() });
    await until(() => island.webContents.executeJavaScript('document.querySelector(".desktop-island")?.dataset.live === "true"'));
    assert.equal(BrowserWindow.getAllWindows().length, 2);
    const result = { schema: 1, fixture: true, native: true, monitors, originalGeometry,
      hideReopen: true, ownerHiddenBarVisible: true, conversationShortcut: true,
      canvasShortcut: true, approvalsShortcut: true, reconnectNoDuplicateWindows: true,
      styled: await island.webContents.executeJavaScript('getComputedStyle(document.querySelector(".desktop-island")).borderRadius !== "0px" && getComputedStyle(document.querySelector(".di-capsule")).display === "flex"') };
    fs.writeFileSync(output, JSON.stringify(result));
    presence.dispose(); owner.destroy(); server.close(); clearTimeout(deadline); app.exit(0);
  } catch (error) {
    fs.writeFileSync(output, JSON.stringify({ error: error.message }));
    presence?.dispose(); owner?.destroy(); server.close(); clearTimeout(deadline); app.exit(6);
  }
});
