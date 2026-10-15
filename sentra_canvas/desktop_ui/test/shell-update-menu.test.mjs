import {test} from 'node:test';
import assert from 'node:assert/strict';
import {closeUpdateMenuOnEscape} from '../src/shell-update-menu.js';

test('Escape closes an open update menu once and returns focus to the summary', () => {
  let focused = false;
  const menu = { open: true, querySelector: () => ({ focus() { focused = true; } }) };
  let prevented = false;
  const closed = closeUpdateMenuOnEscape({ key: 'Escape', preventDefault() { prevented = true; } }, menu);
  assert.equal(closed, true);
  assert.equal(menu.open, false);
  assert.equal(prevented, true);
  assert.equal(focused, true);
  assert.equal(closeUpdateMenuOnEscape({ key: 'Escape', preventDefault() {} }, menu), false);
  assert.equal(closeUpdateMenuOnEscape({ key: 'Enter', preventDefault() {} }, { open: true }), false);
});
