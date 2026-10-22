import { test } from 'node:test';
import assert from 'node:assert/strict';
import { closestEventTarget } from '../src/shell-event-target.js';
test('shell event targets tolerate Document and text nodes while preserving modal guards', () => {
  const modal = {}, element = { closest: selector => selector === '[role=dialog]' ? modal : null };
  assert.equal(closestEventTarget({ target: element }, '[role=dialog]'), modal);
  assert.equal(closestEventTarget({ target: { parentElement: element } }, '[role=dialog]'), modal);
  assert.equal(closestEventTarget({ target: {} }, '[role=dialog]'), null);
  assert.equal(closestEventTarget({}, '[role=dialog]'), null);
});
