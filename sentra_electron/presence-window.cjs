'use strict';
// Read-only display of the main authenticated renderer's existing observation.
// The island has no broker token, network access, approval API or tool executor.
const { BrowserWindow, ipcMain, screen } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const TONES = new Set(['work', 'wait', 'error', 'done', 'review', 'idle']);
const ACTIONS = new Set(['show', 'conversation', 'canvas', 'decisions', 'hub', 'hide']);
const text = (value, max = 120) => typeof value === 'string' ? value.replace(/[\x00-\x1f\x7f]/g, ' ').trim().slice(0, max) : '';
function islandBounds(area, expanded = false) {
  // Original Coucou panel; the animated shape inside is 288×32 / 640×160.
  const width = Math.max(1, Math.min(720, area.width));
  const height = Math.max(1, Math.min(320, area.height));
  return { x: Math.round(area.x + (area.width - width) / 2),
    y: area.y, width, height };
}
function projection(value) {
  if (!value || value.schema !== 1 || !Array.isArray(value.sessions) || value.sessions.length > 64 ||
      !Array.isArray(value.events) || value.events.length > 12) return null;
  return { schema: 1, enabled: value.enabled === true, projectId: text(value.projectId, 200),
    projectName: text(value.projectName, 80), connected: value.connected === true,
    observedAt: Number.isSafeInteger(value.observedAt) ? Math.min(Date.now(), value.observedAt) : 0,
    decisions: Number.isInteger(value.decisions) ? Math.max(0, Math.min(999, value.decisions)) : 0,
    sessions: value.sessions.map(row => ({ dotId: text(row?.dotId, 200), name: text(row?.name, 60),
      mascot: text(row?.mascot, 32), tone: TONES.has(row?.tone) ? row.tone : 'idle',
      label: text(row?.label, 48), detail: text(row?.detail, 120),
      workingValidated: row?.workingValidated === true,
      conversationId: text(row?.conversationId, 200), spaceId: text(row?.spaceId, 200),
    })).filter(row => row.dotId),
    events: value.events.map(row => ({ id: text(row?.id, 200), label: text(row?.label, 100),
      dotId: text(row?.dotId, 200), time: text(row?.time, 12) })),
  };
}
function installPresenceWindow(owner, { preview = false, ownerURL = null, onReady, onState, saved = {}, onPreference } = {}) {
  let island = null, snapshot = null, expanded = false, hidden = false, disposed = false;
  let displayId = saved.displayId ?? null, visiblePreference = saved.visible !== false;
  let rendererReady = false, pendingAction = null, recoverAt = 0;
  let hit = { width: 288, height: 32 }, cursorTimer = null;
  const file = path.join(__dirname, 'island', 'island.html');
  const url = pathToFileURL(file).href;
  const sameFrame = (event, window) => window && !window.isDestroyed() &&
    event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame;
  const fromIsland = event => sameFrame(event, island) && event.senderFrame.url === url;
  const fromOwner = event => {
    if (!sameFrame(event, owner)) return false;
    if (!ownerURL) return preview;
    try {
      const expected = new URL(ownerURL), actual = new URL(event.senderFrame.url);
      return expected.origin === actual.origin && expected.pathname === actual.pathname;
    } catch { return false; }
  };
  function bounds() {
    const selected = screen.getAllDisplays().find(display => display.id === displayId);
    const value = islandBounds((selected || screen.getDisplayMatching(owner.getBounds())).workArea, expanded);
    if (hit.height < .1) value.height = Math.min(6, value.height);
    return value;
  }
  const preference = () => onPreference?.({ visible: visiblePreference, displayId });
  function report() {
    onState?.({ connected: snapshot?.connected === true, observedAt: snapshot?.observedAt || 0,
      dotCount: snapshot?.sessions.length || 0, decisions: snapshot?.decisions || 0,
      visible: Boolean(island && !island.isDestroyed() && island.isVisible()),
      displayId, expanded });
  }
  function send() {
    if (island && !island.isDestroyed() && snapshot) island.webContents.send('sentra:presence:snapshot', { ...snapshot, preview, expanded });
  }
  function create() {
    if (disposed || island || Date.now() < recoverAt || !fs.existsSync(file)) return;
    island = new BrowserWindow({ ...bounds(), title: 'SENTRA · Atividade dos Dots', frame: false,
      transparent: true, backgroundColor: '#00000000', show: false, resizable: false,
      maximizable: false, minimizable: false, skipTaskbar: true, alwaysOnTop: true, hasShadow: false,
      webPreferences: { preload: path.join(__dirname, 'island-preload.cjs'), nodeIntegration: false,
        contextIsolation: true, sandbox: true, webSecurity: true, devTools: false,
        backgroundThrottling: false, partition: 'sentra-presence-' + require('node:crypto').randomUUID() },
    });
    island.setMenu(null);
    island.setAlwaysOnTop(true, 'floating');
    const updateInput = () => {
      if (!island || island.isDestroyed() || !island.isVisible() || !screen.getCursorScreenPoint) return;
      const cursor = screen.getCursorScreenPoint(), box = island.getBounds();
      const w = hit.height < .1 ? Math.min(240, box.width) : hit.width, h = hit.height < .1 ? 6 : hit.height;
      const left = box.x + (box.width - w) / 2;
      const inside = cursor.x >= left && cursor.x <= left + w && cursor.y >= box.y && cursor.y <= box.y + h;
      island.setIgnoreMouseEvents(!inside, { forward: true });
    };
    if (screen.getCursorScreenPoint) cursorTimer = setInterval(updateInput, 16);
    island.on('closed', () => { clearInterval(cursorTimer); cursorTimer = null; });
    const ses = island.webContents.session;
    ses.setPermissionRequestHandler((_c, _p, done) => done(false));
    ses.setPermissionCheckHandler(() => false);
    ses.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'ws://*/*', 'wss://*/*'] }, (_request, done) => done({ cancel: true }));
    island.webContents.on('will-navigate', (event, target) => { if (target !== url) event.preventDefault(); });
    island.webContents.on('will-redirect', event => event.preventDefault());
    island.on('closed', () => { island = null; });
    island.webContents.on('render-process-gone', () => { recoverAt = Date.now() + 3000; island?.destroy(); report(); });
    island.once('ready-to-show', () => { send(); if (!hidden && visiblePreference && snapshot?.enabled) island.showInactive(); report(); onReady?.(island); });
    island.loadFile(file).catch(() => { recoverAt = Date.now() + 3000; island?.destroy(); report(); });
  }
  function update(value) {
    const next = projection(value);
    if (!next || disposed) return;
    // A user can hide it for this run; toggling the preference on re-enables it.
    if (next.enabled && snapshot?.enabled === false) { hidden = false; visiblePreference = true; preference(); }
    snapshot = next;
    if (rendererReady && pendingAction && next.connected) {
      if (pendingAction.projectId === next.projectId) owner.webContents.send('sentra:presence:action', pendingAction);
      pendingAction = null;
    }
    if (!next.enabled) { island?.hide(); report(); return; }
    create(); send();
    if (island && !hidden && visiblePreference && !island.webContents.isLoading()) island.showInactive();
    report();
  }
  const publish = (event, value) => { if (fromOwner(event)) update(value); };
  const ready = event => { if (fromIsland(event)) send(); };
  const expand = (event, value) => {
    if (!fromIsland(event) || typeof value !== 'boolean') return;
    expanded = value; island.setBounds(bounds(), false); send();
  };
  const geometry = (event, value) => {
    if (!fromIsland(event) || !Number.isFinite(value?.width) || !Number.isFinite(value?.height) ||
        value.width < 0 || value.width > 720 || value.height < 0 || value.height > 320) return;
    const collapsedChanged = (hit.height < .1) !== (value.height < .1);
    hit = { width: value.width, height: value.height };
    if (collapsedChanged) island.setBounds(bounds(), false);
  };
  function request(value) {
    if (!ACTIONS.has(value?.action)) return;
    if (value.action === 'hide') {
      if (preview) { owner.close(); return; }
      hidden = true; visiblePreference = false; island?.hide(); preference(); report();
      if (!owner.isDestroyed()) owner.webContents.send('sentra:presence:action', { action: 'hide', projectId: snapshot?.projectId });
      return;
    }
    if (preview) return;
    const row = snapshot?.sessions.find(row => row.dotId === value.dotId) ||
      (!value.dotId ? snapshot?.sessions[0] : null);
    if (['conversation', 'canvas'].includes(value.action) && !row) return;
    if (owner.isDestroyed()) return;
    if (owner.isMinimized()) owner.restore();
    owner.show(); owner.focus();
    const action = { action: value.action,
      projectId: snapshot?.projectId, dotId: row?.dotId, conversationId: row?.conversationId, spaceId: row?.spaceId };
    if (rendererReady) owner.webContents.send('sentra:presence:action', action);
    else pendingAction = action;
  }
  const activate = (event, value) => { if (fromIsland(event)) request(value); };
  const reposition = () => { if (island && !island.isDestroyed()) island.setBounds(bounds(), false); };
  function show() {
    hidden = false; visiblePreference = true; preference();
    hit = { width: 288, height: 32 };
    if (snapshot) snapshot = { ...snapshot, enabled: true };
    create(); reposition(); send();
    if (island && !island.webContents.isLoading()) island.showInactive();
    if (!owner.isDestroyed()) owner.webContents.send('sentra:presence:action', { action: 'enable', projectId: snapshot?.projectId });
    report();
  }
  function selectDisplay(id) {
    if (id !== null && !screen.getAllDisplays().some(display => display.id === id)) return;
    displayId = id; preference(); reposition(); report();
  }
  const ownerReady = event => {
    if (!fromOwner(event)) return;
    rendererReady = true;
    // Wait for a new scoped publication: the listener can mount before Home.
  };
  const ownerLoading = () => { rendererReady = false; };
  const toggle = event => {
    if (!fromOwner(event)) return;
    show(); expanded = !expanded;
    if (island) { island.setBounds(bounds(), false); send(); island.showInactive(); }
  };
  ipcMain.on('sentra:presence:publish', publish);
  ipcMain.on('sentra:presence:ready', ready);
  ipcMain.on('sentra:presence:expand', expand);
  ipcMain.on('sentra:presence:geometry', geometry);
  ipcMain.on('sentra:presence:activate', activate);
  ipcMain.on('sentra:presence:toggle', toggle);
  ipcMain.on('sentra:presence:owner-ready', ownerReady);
  owner.webContents.on('did-start-loading', ownerLoading);
  screen.on('display-metrics-changed', reposition);
  screen.on('display-removed', reposition);
  screen.on('display-added', reposition);
  owner.on('move', reposition);
  function dispose() {
    disposed = true;
    clearInterval(cursorTimer);
    for (const [name, listener] of [['publish', publish], ['ready', ready], ['expand', expand], ['geometry', geometry], ['activate', activate], ['toggle', toggle], ['owner-ready', ownerReady]])
      ipcMain.removeListener('sentra:presence:' + name, listener);
    screen.removeListener('display-metrics-changed', reposition); screen.removeListener('display-removed', reposition);
    screen.removeListener('display-added', reposition);
    owner.webContents.removeListener('did-start-loading', ownerLoading);
    owner.removeListener('move', reposition); island?.destroy(); island = null;
  }
  owner.once('closed', dispose);
  return { update, dispose, show, request, selectDisplay, setOwnerURL(value) {
    ownerURL = value; rendererReady = false; pendingAction = null;
    if (snapshot) { snapshot = { ...snapshot, connected: false, observedAt: 0 }; send(); report(); }
  } };
}
module.exports = { installPresenceWindow, projection, islandBounds };
