import test from 'node:test';
import assert from 'node:assert/strict';
import { readRecentMessagePage, recentPageDisposition } from '../src/shell-message-pages.js';
const scope = { project_id: 'project', space_id: 'space', conversation_id: 'conversation', token: 'excluded', request_key: 'excluded' };
const items = n => Array.from({ length: n }, (_, message_id) => ({ message_id }));

test('new backend opens last 50 messages with one scoped observation and older cursor', async () => {
  const calls = [];
  const result = await readRecentMessagePage(async request => { calls.push(request); return { items: items(50), page: { tail: true, offset: 73, total: 123 } }; }, scope);
  assert.deepEqual(calls, [{ action: 'message_list', project_id: 'project', space_id: 'space', conversation_id: 'conversation', tail: true, limit: 50 }]);
  assert.equal(result.page.previous_offset, 23);
});

test('old backend ignoring tail reads last page and reconstructs omitted legacy offset', async () => {
  const calls = [];
  const result = await readRecentMessagePage(async request => { calls.push(request); return { items: items(50), page: { total: 123 } }; }, scope);
  assert.equal(calls.length, 2); assert.equal(calls[1].offset, 73);
  assert.equal(result.page.offset, 73); assert.equal(result.page.previous_offset, 23);
});

test('unsupported tail fallback only repeats a read; auth failures never retry', async () => {
  const calls = [];
  const result = await readRecentMessagePage(async request => { calls.push(request); if (request.tail) throw Object.assign(Error('unsupported'), { status: 400 }); return { items: items(3), page: { total: 3 } }; }, scope);
  assert.equal(result.page.previous_offset, null); assert.equal(calls.length, 2);
  assert.ok(calls.every(request => request.action === 'message_list' && !request.request_key));
  let attempts = 0;
  await assert.rejects(() => readRecentMessagePage(async () => { attempts++; throw Object.assign(Error('revoked'), { status: 403 }); }, scope), /revoked/);
  assert.equal(attempts, 1);
});

test('incomplete or invalid tails fail visibly instead of hiding a missing range', async () => {
  for (const page of [{ tail: true, offset: 0, total: 123 }, { tail: true, offset: -1, total: 49 }, { tail: true, offset: 73, total: '123' }]) {
    await assert.rejects(() => readRecentMessagePage(async () => ({ items: items(50), page }), scope), /message page/);
  }
});

test('range continuity preserves older reading until explicit adoption of a disjoint tail', () => {
  assert.equal(recentPageDisposition(null, { offset: 73, total: 123 }, true), 'replace');
  assert.equal(recentPageDisposition({ offset: 23, total: 123 }, { offset: 100, total: 150 }, false), 'merge');
  assert.equal(recentPageDisposition({ offset: 23, total: 123 }, { offset: 123, total: 173 }, false), 'merge');
  assert.equal(recentPageDisposition({ offset: 23, total: 123 }, { offset: 124, total: 174 }, false), 'defer');
  assert.equal(recentPageDisposition({ offset: 23, total: 123 }, { offset: 124, total: 174 }, true), 'replace');
  assert.equal(recentPageDisposition({ offset: 23, total: 123 }, { offset: 0, total: 10 }, false), 'replace');
});
