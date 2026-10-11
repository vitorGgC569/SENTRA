'use strict';
// Electron is a display of the authoritative Canvas broker, never a tool host.
const { app, BrowserWindow } = require('electron');
const { envelope, isAllowedResource } = require('./policy.cjs');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
app.setAppUserModelId('SENTRA.Desktop.Electron');
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
  return { address: envelope(value), port: value.port };
}
let handoff;
try { handoff = bootstrap(); }
catch { app.exit(2); }
if (handoff) app.whenReady().then(() => {
  const win = new BrowserWindow({
    title: 'SENTRA — Electron', width: 1440, height: 900,
    minWidth: 1024, minHeight: 650, backgroundColor: '#18181a',
    icon: fs.existsSync(path.join(__dirname, 'SENTRA.ico')) ? path.join(__dirname, 'SENTRA.ico') : undefined,
    autoHideMenuBar: true, show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true,
      sandbox: true, webSecurity: true, devTools: false,
      partition: 'sentra-display-' + require('node:crypto').randomBytes(16).toString('hex'),
      allowRunningInsecureContent: false },
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
  win.once('ready-to-show', () => win.show());
  win.loadURL(handoff.address.replace('/desktop.html#', '/desktop.html?surface=electron#'))
    .catch(() => app.quit());
}).catch(() => app.exit(3));
app.on('window-all-closed', () => app.quit());
