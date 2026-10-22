'use strict';
// Explicitly marked visual example. No broker credentials or execution services.
const { app, BrowserWindow } = require('electron');
const path = require('node:path'), os = require('node:os');
app.setPath('userData', path.join(os.tmpdir(), 'sentra-presence-preview-' + process.pid));
app.on('web-contents-created', (_event, contents) => {
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-attach-webview', event => event.preventDefault());
});
app.whenReady().then(() => {
  const owner = new BrowserWindow({ show: false, webPreferences: { nodeIntegration: false, sandbox: true, contextIsolation: true } });
  const controller = require('./presence-window.cjs').installPresenceWindow(owner, { preview: true,
    onReady: island => {
      const statusDirectory = path.join(__dirname, '..', '.tmp');
      require('node:fs').mkdirSync(statusDirectory, { recursive: true });
      require('node:fs').writeFileSync(path.join(statusDirectory, 'desktop-presence-preview.json'), JSON.stringify({
        schema: 1, pid: process.pid, ready: true, alwaysOnTop: island.isAlwaysOnTop(),
        visible: island.isVisible(), preview: true, brokerConnected: false, at: new Date().toISOString(),
      }));
    },
  });
  const update = () => controller.update({ schema: 1, enabled: true, connected: true, observedAt: Date.now(),
    projectId: 'visual-example', projectName: 'Seu workspace · demonstração visual', decisions: 1,
    sessions: [
      { dotId: 'example-oxta', name: 'Oxta', mascot: 'oxta', tone: 'work', workingValidated: true, detail: 'Coordenando a revisão de login', label: 'Trabalhando' },
      { dotId: 'example-ada', name: 'Ada', mascot: 'ada', tone: 'work', workingValidated: true, detail: 'Analisando alterações nos arquivos', label: 'Trabalhando' },
      { dotId: 'example-broto', name: 'Broto', mascot: 'mint', tone: 'wait', detail: 'Precisa de uma decisão para continuar', label: 'Precisa de você' },
    ], events: [{ id: 'example-1', label: 'Coordenando trabalho', time: 'Agora' },
      { id: 'example-2', label: 'Trabalhando com arquivos', time: 'Agora' }],
  });
  update(); const timer = setInterval(update, 4000);
  owner.once('closed', () => clearInterval(timer));
}).catch(() => app.exit(1));
app.on('window-all-closed', () => app.quit());
