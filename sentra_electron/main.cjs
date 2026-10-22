'use strict';
// Electron is a display of the authoritative Canvas broker, never a tool host.
const { app, BrowserWindow, screen } = require('electron');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {
  envelope, displayAddress, isAllowedResource, recoverBounds, instanceRole, readWindowState,
  dotIconCandidates, APP_USER_MODEL_ID,
} = require('./policy.cjs');
app.setAppUserModelId(APP_USER_MODEL_ID);
app.on('web-contents-created', (_event, contents) => {
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-attach-webview', event => event.preventDefault());
});
function bootstrap() {
  const argument = process.argv.find(value => value.startsWith('--sentra-ticket='));
  if (!argument || !/^--sentra-ticket=[0-9a-f]{32}$/.test(argument)) throw Error('missing display ticket');
  const ticket = argument.slice('--sentra-ticket='.length);
  const file = path.join(os.tmpdir(), 'sentra-electron-' + ticket + '.json');
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 60 || stat.size > 1024) throw Error('invalid ticket file');
  let raw;
  try { raw = fs.readFileSync(file, 'utf8'); }
  finally { fs.unlinkSync(file); }
  const value = JSON.parse(raw);
  const now = Date.now();
  if (!Number.isSafeInteger(value.expires_at) ||
      value.expires_at <= now || value.expires_at > now + 30000) throw Error('expired ticket');
  const surface = value.surface === 'shell-home' ? 'shell-home' : (value.surface === 'native' ? 'native' : 'desktop');
  return { address: envelope({ ...value, surface }), port: value.port, surface,
    ticket: { schema: 1, port: value.port, secret: value.secret, surface } };
}
function dotIcon() {
  for (const name of dotIconCandidates()) {
    const file = path.join(__dirname, name);
    if (fs.existsSync(file)) return file;
  }
  return undefined;
}
let handoff;
try { handoff = bootstrap(); }
catch { app.exit(2); }
const primary = Boolean(handoff) && instanceRole(app.requestSingleInstanceLock({ handoff: handoff.ticket })) === 'primary';
if (handoff && !primary) app.exit(0);
if (handoff && primary) {
  let windowRef = null;
  let presenceRef = null;
  const stateFile = () => path.join(app.getPath('userData'), 'sentra-window.json');
  app.on('second-instance', (_event, _argv, _directory, additional) => {
    try {
      const value = additional?.handoff;
      const address = envelope(value);
      // Only a consumed launcher ticket can rotate the display's local endpoint.
      if (address !== handoff.address) {
        handoff = { address, port: value.port, surface: value.surface, ticket: value };
        presenceRef?.setOwnerURL(displayAddress(address));
        if (windowRef && !windowRef.isDestroyed()) windowRef.loadURL(displayAddress(address)).catch(() => {});
      }
    } catch { /* A malformed second instance cannot replace the authenticated endpoint. */ }
    const win = windowRef;
    if (!win || win.isDestroyed()) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
  app.whenReady().then(() => {
    const savedBounds = readWindowState(stateFile());
    const savedDisplay = savedBounds && screen.getAllDisplays().find(display => {
      const area = display.workArea;
      return savedBounds.x >= area.x && savedBounds.x < area.x + area.width &&
        savedBounds.y >= area.y && savedBounds.y < area.y + area.height;
    });
    const bounds = recoverBounds(savedBounds, (savedDisplay || screen.getPrimaryDisplay()).workArea);
    const win = new BrowserWindow({
      title: 'SENTRA — Electron', x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
      minWidth: 1024, minHeight: 650, backgroundColor: '#18181a',
      icon: dotIcon(),
      autoHideMenuBar: true, show: false,
      webPreferences: { preload: path.join(__dirname, 'presence-preload.cjs'),
        backgroundThrottling: false, nodeIntegration: false, contextIsolation: true,
        sandbox: true, webSecurity: true, devTools: false,
        partition: 'sentra-display-' + require('node:crypto').randomBytes(16).toString('hex'),
        allowRunningInsecureContent: false },
    });
    windowRef = win;
    const presenceFile = path.join(app.getPath('userData'), 'sentra-presence.json');
    const diagnosticFile = path.join(app.getPath('userData'), 'sentra-display-status.json');
    let reported = 0;
    let lifecycle = null;
    const presence = require('./presence-window.cjs').installPresenceWindow(win, {
      ownerURL: displayAddress(handoff.address), saved: readWindowState(presenceFile) || {},
      onPreference: value => { try { fs.writeFileSync(presenceFile, JSON.stringify(value)); } catch {} },
      onState: value => {
        if (Date.now() - reported < 1000) return;
        reported = Date.now();
        try { fs.writeFileSync(diagnosticFile, JSON.stringify({ schema: 1, pid: process.pid,
          at: reported, preview: false, displayCount: screen.getAllDisplays().length,
          trayAvailable: lifecycle?.trayAvailable === true, ...value })); } catch {}
      },
    });
    presenceRef = presence;
    lifecycle = require('./desktop-lifecycle.cjs').installDesktopLifecycle(win, presence, dotIcon());
    win.on('close', () => {
      try {
        const current = win.getBounds();
        fs.writeFileSync(stateFile(), JSON.stringify({ ...current, isMinimized: win.isMinimized() }));
      } catch { /* Display memory is optional and never holds user work. */ }
    });
    const ses = win.webContents.session;
    ses.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    ses.setPermissionCheckHandler(() => false);
    ses.webRequest.onBeforeRequest({ urls: ['*://*/*'] }, (request, done) => {
      done({ cancel: !isAllowedResource(request.url, handoff.port) });
    });
    win.webContents.on('will-navigate', (event, url) => {
      if (!isAllowedResource(url, handoff.port)) event.preventDefault();
    });
    let recoveryTimer = null, failures = 0;
    const recover = () => {
      if (recoveryTimer || win.isDestroyed()) return;
      recoveryTimer = setTimeout(() => {
        recoveryTimer = null;
        if (!win.isDestroyed()) win.loadURL(displayAddress(handoff.address)).catch(recover);
      }, Math.min(30000, 1500 * 2 ** Math.min(failures++, 5)));
    };
    win.webContents.on('render-process-gone', recover);
    win.webContents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (mainFrame && code !== -3) recover();
    });
    win.webContents.on('did-finish-load', () => { failures = 0; });
    win.once('closed', () => clearTimeout(recoveryTimer));
    win.once('ready-to-show', () => { win.show(); if (bounds.restored) win.focus(); });
    win.loadURL(displayAddress(handoff.address))
      .catch(recover);
  }).catch(() => app.exit(3));
}
app.on('window-all-closed', () => app.quit());
