import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatConversationDate, formatConversationDateTime } from '../src/shell-dates.js';

test('Unix seconds no longer display as 1970', () => {
  assert.equal(formatConversationDate(1791835295), '12/10/2026');
  assert.equal(formatConversationDate('1791835295'), '12/10/2026');
});
test('milliseconds and ISO timestamps retain the correct date', () => {
  assert.equal(formatConversationDate(1791835295000), '12/10/2026');
  assert.equal(formatConversationDate('2026-10-12T17:21:35Z'), '12/10/2026');
});
test('expanded home rows keep the UTC day and add the time', () => {
  const stamp = formatConversationDateTime('2026-10-12T17:21:35Z');
  assert.equal(stamp.includes('12/10/2026'), true);
  assert.equal(stamp.includes('17:21'), true);
  assert.equal(formatConversationDateTime(''), '');
});
test('missing or invalid date does not display a misleading epoch', () => {
  assert.equal(formatConversationDate(undefined), '');
  assert.equal(formatConversationDate(''), '');
  assert.equal(formatConversationDate('unknown'), '');
});
