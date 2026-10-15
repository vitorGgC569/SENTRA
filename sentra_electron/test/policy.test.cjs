'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { envelope, displayAddress, isAllowedResource, safeOrigin } = require('../policy.cjs');
const secret = 'a'.repeat(48);
test('handoff accepts a single loopback port and strong secret', () => {
  const url = envelope({ schema: 1, port: 12345, secret });
  assert.equal(url, 'http://127.0.0.1:12345/desktop.html#token=' + secret);
  assert.equal(safeOrigin('http://127.0.0.1:12345/desktop.html'), true);
});
test('rejects invalid tokens, ports and foreign origins', () => {
  for (const obj of [{schema:1,port:0,secret},{schema:1,port:1,secret:'x'},
    {schema:1,port:65536,secret},{schema:2,port:444,secret}]) assert.throws(() => envelope(obj));
  for (const url of ['https://chatgpt.com/', 'http://localhost:12345/api/',
    'http://127.0.0.2:12345/api/', 'file:///c:/x']) {
    assert.equal(isAllowedResource(url, 12345), false);
  }
  assert.equal(isAllowedResource('ws://127.0.0.1:12345/events',12345), true);
});
test('display query never becomes part of the bearer token on any surface', () => {
  for (const surface of ['desktop', 'shell-home', 'native']) {
    const address = displayAddress(envelope({ schema: 1, port: 12345, secret, surface }));
    const url = new URL(address);
    const credential = new URLSearchParams(url.hash.slice(1)).get('token');
    assert.equal(credential, secret);
    assert.equal(url.pathname, '/' + surface + '.html');
    assert.equal(url.searchParams.get('surface'), surface === 'desktop' ? 'electron' : 'electron-shell');
    assert.ok(address.indexOf('?surface=') < address.indexOf('#token='));
  }
});
