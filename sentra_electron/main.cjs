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
  return { address: envelope({ ...value, surface }), port: value.port, surface };
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
const primary = Boolean(handoff) && instanceRole(app.requestSingleInstanceLock()) === 'primary';
if (handoff && !primary) app.exit(0);
if (handoff && primary) {
  let windowRef = null;
  const stateFile = () => path.join(app.getPath('userData'), 'sentra-window.json');
  app.on('second-instance', () => {
    const win = windowRef;
    if (!win || win.isDestroyed()) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
  app.whenReady().then(() => {
    const bounds = recoverBounds(readWindowState(stateFile()), screen.getPrimaryDisplay().workArea);
    const win = new BrowserWindow({
      title: 'SENTRA — Electron', x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
      minWidth: 1024, minHeight: 650, backgroundColor: '#18181a',
      icon: dotIcon(),
      autoHideMenuBar: true, show: false,
      webPreferences: { nodeIntegration: false, contextIsolation: true,
        sandbox: true, webSecurity: true, devTools: false,
        partition: 'sentra-display-' + require('node:crypto').randomBytes(16).toString('hex'),
        allowRunningInsecureContent: false },
    });
    windowRef = win;
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
    win.once('ready-to-show', () => { win.show(); if (bounds.restored) win.focus(); });
    win.loadURL(displayAddress(handoff.address))
      .catch(() => app.quit());
  }).catch(() => app.exit(3));
}
app.on('window-all-closed', () => app.quit());
