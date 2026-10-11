'use strict';
const { URL } = require('node:url');
function safeOrigin(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' && u.hostname === '127.0.0.1' &&
      /^\d+$/.test(u.port) && Number(u.port) >= 1 && Number(u.port) <= 65535 &&
      !u.username && !u.password && !u.search && !u.hash && u.pathname === '/desktop.html';
  } catch { return false; }
}
function envelope(value) {
  if (!value || value.schema !== 1 || !Number.isInteger(value.port) ||
      value.port < 1 || value.port > 65535 || typeof value.secret !== 'string' ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(value.secret)) throw Error('Invalid SENTRA display handoff');
  return 'http://127.0.0.1:' + value.port + '/desktop.html#token=' + encodeURIComponent(value.secret);
}
function isAllowedResource(value, port) {
  try {
    const u = new URL(value);
    return ((u.protocol === 'http:' || u.protocol === 'ws:') &&
      u.hostname === '127.0.0.1' && Number(u.port) === port &&
      !u.username && !u.password);
  } catch { return false; }
}
module.exports = { envelope, isAllowedResource, safeOrigin };
