'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const { EventEmitter } = require('node:events');
function fixture() {
  const windows = [], ipcMain = new EventEmitter(), screen = new EventEmitter(), app = new EventEmitter();
  let displays = [{ id: 1, label: 'Primary', bounds: { x: 0, y: 0, width: 1920, height: 1080 }, workArea: { x: 0, y: 30, width: 1920, height: 1010 } },
    { id: 2, label: 'Left', bounds: { x: -1280, y: -200, width: 1280, height: 800 }, workArea: { x: -1280, y: -200, width: 1280, height: 760 } }];
  screen.getAllDisplays = () => displays;
  screen.getDisplayMatching = box => displays.find(d => box.x >= d.workArea.x && box.x < d.workArea.x + d.workArea.width) || displays[0];
  class Window extends EventEmitter {
    constructor(options = {}) {
      super(); this.options = options; this.visible = false; this.box = { x: 100, y: 100, width: 1024, height: 800, ...options };
      this.webContents = new EventEmitter();
      this.webContents.mainFrame = { url: 'http://127.0.0.1:1234/desktop.html' };
      this.webContents.sent = []; this.webContents.send = (channel, value) => this.webContents.sent.push({ channel, value });
      this.webContents.isLoading = () => false;
      this.webContents.session = { setPermissionRequestHandler() {}, setPermissionCheckHandler() {}, webRequest: { onBeforeRequest: (_filter, fn) => this.fence = fn } };
      windows.push(this);
    }
    getBounds() { return this.box; } setBounds(box) { this.box = box; }
    isDestroyed() { return !!this.destroyed; } isVisible() { return this.visible; }
    isMinimized() { return !!this.minimized; } restore() { this.minimized = false; }
    show() { this.visible = true; } showInactive() { this.show(); } hide() { this.visible = false; } focus() {}
    setMenu() {} setAlwaysOnTop() {}
    loadFile() { queueMicrotask(() => this.emit('ready-to-show')); return Promise.resolve(); }
    destroy() { this.destroyed = true; this.emit('closed'); }
    close() { const e = { preventDefault: () => e.prevented = true }; this.emit('close', e); if (!e.prevented) this.destroy(); }
  }
  class Tray extends EventEmitter { setToolTip() {} setContextMenu(menu) { this.menu = menu; } destroy() {} }
  const electron = { BrowserWindow: Window, ipcMain, screen, app, Tray, Menu: { buildFromTemplate: x => x } };
  const load = name => {
    const filename = path.join(__dirname, '..', name), module = { exports: {} };
    vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { require: n => n === 'electron' ? electron : require(n),
      module, exports: module.exports, __dirname: path.dirname(filename), URL, Date, queueMicrotask, setInterval, clearInterval });
    return module.exports;
  };
  const owner = new Window();
  const sender = win => ({ sender: win.webContents, senderFrame: win.webContents.mainFrame });
  return { ...load('presence-window.cjs'), lifecycle: load('desktop-lifecycle.cjs'), owner, windows, screen, app,
    ipcMain, sender, removeSecondary() { displays = displays.slice(0, 1); screen.emit('display-removed'); } };
}
const sample = () => ({ schema: 1, enabled: true, connected: true, observedAt: Date.now(), projectId: 'p',
  sessions: [{ dotId: 'dot', name: 'Real Dot', tone: 'work', workingValidated: true, conversationId: 'chat' }], events: [], decisions: 1 });
test('bar stays inside negative-coordinate, scaled, tiny and portrait work areas', () => {
  const { islandBounds } = fixture();
  for (const area of [{ x: -1920, y: -200, width: 1920, height: 1040 }, { x: 0, y: 0, width: 800, height: 1280 },
    { x: 2000, y: 100, width: 640, height: 360 }, { x: 0, y: 0, width: 100, height: 8 }]) for (const expanded of [true, false]) {
    const b = islandBounds(area, expanded);
    assert.ok(b.x >= area.x && b.y >= area.y && b.x + b.width <= area.x + area.width && b.y + b.height <= area.y + area.height);
  }
});
test('projection bounds data and drops secrets, prompts and commands', () => {
  const { projection } = fixture();
  const projected = projection({ ...sample(), secret: 'do-not-forward', sessions: [{ dotId: 'dot', name: 'x'.repeat(100), command: 'danger', tone: 'bogus' }], observedAt: Date.now() + 50000 });
  assert.equal(projected.sessions[0].name.length, 60);
  assert.equal(projected.sessions[0].tone, 'idle');
  assert.ok(projected.observedAt <= Date.now());
  assert.ok(!JSON.stringify(projected).includes('danger') && !JSON.stringify(projected).includes('do-not-forward'));
  assert.equal(projection({ ...sample(), sessions: Array(65).fill({}) }), null);
});
test('minimize, hide and reopen preserve one native bar and one owner', async () => {
  const f = fixture(), prefs = [];
  const p = f.installPresenceWindow(f.owner, { ownerURL: f.owner.webContents.mainFrame.url, onPreference: x => prefs.push(x) });
  p.update(sample()); await Promise.resolve();
  const island = f.windows[1];
  assert.ok(island.visible); assert.equal(island.options.parent, undefined);
  f.owner.minimized = true; assert.ok(island.visible);
  p.request({ action: 'hide' }); assert.equal(island.visible, false);
  p.update(sample()); assert.equal(island.visible, false);
  p.show(); assert.equal(island.visible, true); assert.equal(f.windows.length, 2);
  assert.equal(prefs.at(-1).visible, true);
  p.dispose(); assert.equal(f.ipcMain.listenerCount('sentra:presence:publish'), 0);
});
test('monitor selection and unplug reposition existing bar without creating processes', async () => {
  const f = fixture(), p = f.installPresenceWindow(f.owner, { ownerURL: f.owner.webContents.mainFrame.url });
  p.update(sample()); await Promise.resolve();
  const island = f.windows[1]; p.selectDisplay(2); assert.ok(island.box.x < 0);
  f.removeSecondary(); assert.ok(island.box.x >= 0); assert.equal(f.windows.length, 2);
  p.dispose();
});
test('only same authenticated frame can publish or activate; reconnect is observation only', async () => {
  const f = fixture(), url = f.owner.webContents.mainFrame.url;
  const p = f.installPresenceWindow(f.owner, { ownerURL: url });
  const forged = { sender: {}, senderFrame: { url } };
  f.ipcMain.emit('sentra:presence:publish', forged, sample()); assert.equal(f.windows.length, 1);
  f.ipcMain.emit('sentra:presence:publish', f.sender(f.owner), sample()); await Promise.resolve();
  const island = f.windows[1];
  island.webContents.mainFrame.url = require('node:url').pathToFileURL(path.join(__dirname, '../island/island.html')).href;
  f.ipcMain.emit('sentra:presence:owner-ready', f.sender(f.owner));
  for (const action of ['conversation', 'canvas', 'decisions']) {
    f.ipcMain.emit('sentra:presence:activate', f.sender(island), { action, dotId: 'dot' });
    assert.equal(f.owner.webContents.sent.at(-1).value.action, action);
  }
  const count = f.owner.webContents.sent.length;
  f.ipcMain.emit('sentra:presence:activate', forged, { action: 'canvas', dotId: 'dot' });
  f.ipcMain.emit('sentra:presence:activate', f.sender(island), { action: 'approve', dotId: 'dot' });
  f.ipcMain.emit('sentra:presence:activate', f.sender(island), { action: 'canvas', dotId: 'other' });
  assert.equal(f.owner.webContents.sent.length, count);
  p.update({ ...sample(), connected: false }); p.update(sample());
  assert.equal(f.owner.webContents.sent.length, count); assert.equal(f.windows.length, 2);
  let blocked; island.fence({}, result => blocked = result.cancel); assert.equal(blocked, true);
  p.dispose();
});
test('close-to-tray keeps display alive; explicit quit allows close', () => {
  const f = fixture(), p = f.installPresenceWindow(f.owner, { ownerURL: f.owner.webContents.mainFrame.url });
  const lifecycle = f.lifecycle.installDesktopLifecycle(f.owner, p, 'SENTRA-DOT.ico');
  assert.ok(lifecycle.trayAvailable); f.owner.close(); assert.equal(f.owner.isDestroyed(), false);
  lifecycle.show(); assert.ok(f.owner.visible);
  f.app.emit('before-quit'); f.owner.close(); assert.equal(f.owner.isDestroyed(), true);
});
