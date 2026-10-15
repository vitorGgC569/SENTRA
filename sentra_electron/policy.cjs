'use strict';
const { URL } = require('node:url');
function safeOrigin(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' && u.hostname === '127.0.0.1' &&
      /^\d+$/.test(u.port) && Number(u.port) >= 1 && Number(u.port) <= 65535 &&
      !u.username && !u.password && !u.search && !u.hash &&
      (u.pathname === '/desktop.html' || u.pathname === '/shell-home.html' || u.pathname === '/native.html');
  } catch { return false; }
}
function envelope(value) {
  if (!value || value.schema !== 1 || !Number.isInteger(value.port) ||
      value.port < 1 || value.port > 65535 || typeof value.secret !== 'string' ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(value.secret)) throw Error('Invalid SENTRA display handoff');
  const surface = (value.surface === 'shell-home' || value.surface === 'native') ? value.surface : 'desktop';
  return 'http://127.0.0.1:' + value.port + '/' + surface + '.html#token=' + encodeURIComponent(value.secret);
}
function isAllowedResource(value, port) {
  try {
    const u = new URL(value);
    return ((u.protocol === 'http:' || u.protocol === 'ws:') &&
      u.hostname === '127.0.0.1' && Number(u.port) === port &&
      !u.username && !u.password);
  } catch { return false; }
}
function displayAddress(address) {
  const url = new URL(address);
  url.searchParams.set('surface', url.pathname === '/desktop.html' ? 'electron' : 'electron-shell');
  return url.toString();
}
const APP_USER_MODEL_ID = 'SENTRA.Desktop.Electron';
const DOT_APP_USER_MODEL_ID = 'SENTRA.Desktop';

function recoverBounds(saved, workArea) {
  const area = workArea && workArea.width > 0 && workArea.height > 0
    ? workArea : { x: 0, y: 0, width: 1440, height: 900 };
  const preferredW = Number(saved?.width);
  const preferredH = Number(saved?.height);
  const width = Math.round(Math.min(area.width, Math.max(Math.min(1024, area.width),
    Number.isFinite(preferredW) && preferredW > 0 ? preferredW : Math.min(1440, area.width))));
  const height = Math.round(Math.min(area.height, Math.max(Math.min(650, area.height),
    Number.isFinite(preferredH) && preferredH > 0 ? preferredH : Math.min(900, area.height))));
  let x = Number.isFinite(saved?.x) ? saved.x : area.x;
  let y = Number.isFinite(saved?.y) ? saved.y : area.y;
  const visibleX = x < area.x + area.width - 48 && x + width > area.x + 48;
  const visibleY = y < area.y + area.height - 48 && y + 48 > area.y;
  const offscreen = !visibleX || !visibleY;
  if (offscreen || !Number.isFinite(saved?.x)) x = area.x + Math.max(0, Math.floor((area.width - width) / 2));
  if (offscreen || !Number.isFinite(saved?.y)) y = area.y + Math.max(0, Math.floor((area.height - height) / 2));
  x = Math.min(Math.max(area.x, x), area.x + Math.max(0, area.width - width));
  y = Math.min(Math.max(area.y, y), area.y + Math.max(0, area.height - height));
  return { x, y, width, height, wasMinimized: Boolean(saved?.isMinimized), restored: offscreen || Boolean(saved?.isMinimized) };
}

function instanceRole(gotLock) {
  if (typeof gotLock !== 'boolean') throw new Error('single instance lock must be boolean');
  return gotLock ? 'primary' : 'secondary';
}

function readWindowState(file) {
  try {
    const value = JSON.parse(require('node:fs').readFileSync(file, 'utf8'));
    return value && typeof value === 'object' ? value : null;
  } catch { return null; }
}

function dotIconCandidates() {
  return ['SENTRA-DOT.ico', 'SENTRA.ico'];
}

function shortcutSpec({ target, icon, appUserModelId } = {}) {
  if (typeof target !== 'string' || !target.trim()) throw new Error('shortcut target required');
  if (typeof icon !== 'string' || !/\.ico$/i.test(icon)) throw new Error('shortcut icon must be an ico');
  const id = appUserModelId || DOT_APP_USER_MODEL_ID;
  if (id !== DOT_APP_USER_MODEL_ID && id !== APP_USER_MODEL_ID) throw new Error('unsupported AppUserModelID');
  const lowered = target.replace(/\//g, '\\').toLowerCase();
  if (lowered.includes('\\.sentra\\') || lowered.endsWith('\\.sentra')) throw new Error('shortcut must not target user data');
  return {
    kind: id === APP_USER_MODEL_ID ? 'electron-display' : 'dot-window',
    appUserModelId: id, target, icon, description: 'SENTRA', singleInstance: true,
    dataRefresh: false, codeReload: false,
  };
}

module.exports = {
  envelope, displayAddress, isAllowedResource, safeOrigin, recoverBounds, instanceRole, readWindowState,
  dotIconCandidates, shortcutSpec, APP_USER_MODEL_ID, DOT_APP_USER_MODEL_ID,
};
