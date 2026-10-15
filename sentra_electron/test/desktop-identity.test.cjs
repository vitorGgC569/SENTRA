'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  recoverBounds, instanceRole, readWindowState, dotIconCandidates, shortcutSpec,
  APP_USER_MODEL_ID, DOT_APP_USER_MODEL_ID,
} = require('../policy.cjs');

const area = {x: 10, y: 20, width: 1600, height: 1000};

test('Dot window and Electron display keep distinct taskbar identities', () => {
  assert.equal(DOT_APP_USER_MODEL_ID, 'SENTRA.Desktop');
  assert.equal(APP_USER_MODEL_ID, 'SENTRA.Desktop.Electron');
  assert.deepEqual(dotIconCandidates(), ['SENTRA-DOT.ico', 'SENTRA.ico']);
  assert.equal(fs.existsSync(path.join(__dirname, '..', 'SENTRA-DOT.ico')), true);
  const dot = shortcutSpec({target: 'C:\\Apps\\SENTRA\\SENTRA-Desktop.cmd', icon: 'C:\\Apps\\SENTRA\\SENTRA-DOT.ico'});
  assert.equal(dot.kind, 'dot-window');
  assert.equal(dot.appUserModelId, 'SENTRA.Desktop');
  assert.equal(dot.singleInstance, true);
  assert.equal(dot.dataRefresh, false);
  assert.equal(dot.codeReload, false);
  assert.equal(dot.description, 'SENTRA');
  const display = shortcutSpec({
    target: 'C:\\Apps\\SENTRA\\electron.exe', icon: 'SENTRA.ico', appUserModelId: 'SENTRA.Desktop.Electron',
  });
  assert.equal(display.kind, 'electron-display');
  assert.throws(() => shortcutSpec({target: 'C:\\Users\\a\\.sentra\\bin\\SENTRA.exe', icon: 'SENTRA-DOT.ico'}));
  assert.throws(() => shortcutSpec({target: 'C:\\Apps\\SENTRA.exe', icon: 'SENTRA.png'}));
  assert.throws(() => instanceRole('yes'));
  assert.equal(instanceRole(true), 'primary');
  assert.equal(instanceRole(false), 'secondary');
});

test('a missing, minimized or off-screen window is brought back inside the work area', () => {
  const fresh = recoverBounds(null, area);
  assert.equal(fresh.width <= area.width && fresh.height <= area.height, true);
  assert.equal(fresh.x >= area.x && fresh.y >= area.y, true);
  const parked = recoverBounds({x: -4000, y: 20, width: 1440, height: 900, isMinimized: true}, area);
  assert.equal(parked.wasMinimized, true);
  assert.equal(parked.restored, true);
  assert.ok(parked.x + parked.width <= area.x + area.width);
  assert.ok(parked.y >= area.y);
  const file = path.join(os.tmpdir(), 'sentra-window-state-' + process.pid + '.json');
  fs.writeFileSync(file, JSON.stringify({x: 40, y: 50, width: 1200, height: 800, isMinimized: false}));
  try {
    const saved = recoverBounds(readWindowState(file), area);
    assert.equal(saved.x, 40);
    assert.equal(saved.wasMinimized, false);
  } finally { fs.unlinkSync(file); }
  assert.equal(readWindowState(file + '.missing'), null);
});
