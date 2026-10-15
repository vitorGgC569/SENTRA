import {test} from 'node:test';
import assert from 'node:assert/strict';
import {BUNDLE_VERSION, classifyUpdate, versionDecision} from '../src/shell-updates.js';

test('data refresh, local compile and installed version are different operations', () => {
  const data = classifyUpdate('data');
  const code = classifyUpdate('code');
  const version = classifyUpdate('version');
  assert.equal(BUNDLE_VERSION, '0.1.0');
  assert.deepEqual([data.reloadsWindow, data.installsBits, data.compilesCode, data.touchesUserData], [false, false, false, false]);
  assert.deepEqual([code.reloadsWindow, code.installsBits, code.compilesCode, code.touchesUserData], [true, false, true, false]);
  assert.deepEqual([version.reloadsWindow, version.installsBits, version.compilesCode, version.touchesUserData], [false, true, false, false]);
  assert.notEqual(data.notice, code.notice);
  assert.notEqual(code.notice, version.notice);
  assert.throws(() => classifyUpdate('refresh'));
});

test('the same installed version and a data refresh never apply bits', () => {
  assert.equal(versionDecision({installed: '0.1.0', available: '0.1.0'}).apply, false);
  assert.equal(versionDecision({installed: '0.1.0', available: '0.2.0', dataRefresh: true}).apply, false);
  assert.equal(versionDecision({installed: null, available: '0.2.0'}).apply, false);
  const changed = versionDecision({installed: '0.1.0', available: '0.2.0', dataRefresh: false});
  assert.equal(changed.apply, true);
  assert.match(changed.reason, /não apaga dados/i);
});
