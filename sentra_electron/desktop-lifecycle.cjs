'use strict';
// Own the display lifetime only. Quitting never shuts down the Canvas broker.
const { app, Tray, Menu, screen } = require('electron');
function installDesktopLifecycle(win, presence, icon) {
  let tray = null, quitting = false;
  const quitNow = () => { quitting = true; app.quit(); };
  const show = () => {
    if (win.isDestroyed()) return;
    if (win.isMinimized()) win.restore();
    win.show(); win.focus();
  };
  function menu() {
    tray?.setContextMenu(Menu.buildFromTemplate([
      { label: 'Abrir SENTRA', click: show },
      { label: 'Mostrar barra dos Dots', click: () => presence.show() },
      { label: 'Ocultar barra dos Dots', click: () => presence.request({ action: 'hide' }) },
      { type: 'separator' },
      ...[['conversation', 'Abrir conversa'], ['canvas', 'Abrir Canvas'], ['decisions', 'Ver aprovações']]
        .map(([action, label]) => ({ label, click: () => presence.request({ action }) })),
      { label: 'Monitor da barra', submenu: [
        { label: 'Acompanhar a janela do SENTRA', click: () => presence.selectDisplay(null) },
        ...screen.getAllDisplays().map((display, index) => ({
          label: `${display.label || 'Monitor ' + (index + 1)} · ${display.bounds.width} × ${display.bounds.height}`,
          click: () => presence.selectDisplay(display.id),
        })),
      ] },
      { type: 'separator' },
      { label: 'Sair da interface do SENTRA', click: quitNow },
    ]));
  }
  try {
    if (icon) { tray = new Tray(icon); tray.setToolTip('SENTRA · Dots e atividade'); tray.on('double-click', show); menu(); }
  } catch { tray?.destroy(); tray = null; }
  const close = event => { if (tray && !quitting) { event.preventDefault(); win.hide(); } };
  const quit = () => { quitting = true; };
  win.on('close', close);
  app.on('before-quit', quit);
  screen.on('display-added', menu); screen.on('display-removed', menu);
  const dispose = () => {
    screen.removeListener('display-added', menu); screen.removeListener('display-removed', menu);
    app.removeListener('before-quit', quit); win.removeListener('close', close);
    tray?.destroy(); tray = null;
  };
  win.once('closed', dispose);
  return { show, dispose, get trayAvailable() { return Boolean(tray); } };
}
module.exports = { installDesktopLifecycle };
