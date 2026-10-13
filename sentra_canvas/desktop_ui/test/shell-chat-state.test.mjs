import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeMessages } from '../src/shell-chat-state.js';

const local = { message_id: 'local-request-a', request_key: 'request-a', role: 'user',
  content: 'same text', status: 'sending', optimistic: true };
const canonical = { message_id: 'server-a', request_key: 'request-a', role: 'user',
  content: 'same text', status: 'queued' };
test('polling before acknowledgement reconciles by identity without a duplicate', () => {
  const rows = mergeMessages([local], [canonical]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].message_id, 'server-a');
  assert.equal(rows[0].optimistic, undefined);
  assert.deepEqual(mergeMessages(rows, [local]), rows);
});
test('identical text with distinct requests stays distinct; uncertain identity stays intact', () => {
  const uncertain = { ...local, status: 'uncertain' };
  const rows = mergeMessages([uncertain], [{ ...canonical, message_id: 'server-b', request_key: 'request-b' }]);
  assert.equal(rows.length, 2);
  assert.equal(rows.find(row => row.optimistic).status, 'uncertain');
  assert.equal(mergeMessages(rows, [canonical]).length, 2);
});
