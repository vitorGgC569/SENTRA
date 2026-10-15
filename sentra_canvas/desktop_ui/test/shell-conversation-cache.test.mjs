import test from 'node:test';
import assert from 'node:assert/strict';
import { createConversationCache } from '../src/shell-conversation-cache.js';

const scope = id => ({ project_id: 'project', space_id: 'space', conversation_id: id });
const message = (id, content = 'Olá 🦉') => ({ ...scope(id), message_id: 'message-' + id, role: 'assistant', content,
  status: 'succeeded', request_key: 'private-request', receipt_id: 'receipt', operation_id: 'operation',
  grant: 'grant', token: 'token', attachments: [{ url: 'private' }], content_ref: { path: 'private' } });

test('cache is scoped, cloned and contains only inert presentation fields', () => {
  const cache = createConversationCache();
  assert.equal(cache.set(scope('one'), [message('one')]), true);
  const cached = cache.get(scope('one'));
  assert.equal(cached.items[0].content, 'Olá 🦉');
  assert.equal(cached.items[0].cached_visual, true);
  for (const field of ['status', 'request_key', 'receipt_id', 'operation_id', 'grant', 'token', 'attachments', 'content_ref']) {
    assert.equal(field in cached.items[0], false, field);
  }
  cached.items[0].content = 'changed by renderer';
  assert.equal(cache.get(scope('one')).items[0].content, 'Olá 🦉');
  assert.equal(cache.get({ ...scope('one'), space_id: 'other' }), null);
  assert.equal(cache.get({ ...scope('one'), project_id: 'other' }), null);
  assert.equal(cache.set(scope('two'), [message('one')]), false);
  assert.equal(cache.set(scope('two'), [{ ...message('two'), optimistic: true }]), false);
  assert.equal(cache.set(scope('two'), [null]), false);
  assert.equal(cache.set({ ...scope('two'), space_id: '../outside' }, []), false);
});

test('LRU entry bound and TTL stay bounded without read extending expiration', () => {
  let time = 1000;
  const cache = createConversationCache({ maxEntries: 2, ttlMs: 100, now: () => time });
  cache.set(scope('one'), [message('one')]);
  cache.set(scope('two'), [message('two')]);
  cache.get(scope('one'));
  cache.set(scope('three'), [message('three')]);
  assert.equal(cache.get(scope('two')), null);
  time = 1099; assert.ok(cache.get(scope('one')));
  time = 1100; assert.equal(cache.get(scope('one')), null);
  assert.equal(cache.stats().entries, 0);
});

test('UTF-8 byte quota evicts and refuses oversized content without truncation', () => {
  const baseline = createConversationCache();
  baseline.set(scope('one'), [message('one', '🦉'.repeat(10))]);
  const oneSize = baseline.stats().bytes;
  assert.equal(oneSize, new TextEncoder().encode(JSON.stringify(baseline.get(scope('one')))).byteLength);
  const cache = createConversationCache({ maxBytes: oneSize + 10 });
  cache.set(scope('one'), [message('one', '🦉'.repeat(10))]);
  cache.set(scope('two'), [message('two', '🦉'.repeat(10))]);
  assert.equal(cache.get(scope('one')), null);
  assert.equal(cache.get(scope('two')).items[0].content, '🦉'.repeat(10));
  assert.equal(cache.set(scope('two'), [message('two', '🦉'.repeat(1000))]), false);
  assert.equal(cache.get(scope('two')), null);
  assert.equal(cache.stats().bytes, 0);
});

test('keeps at most 50 complete messages and supports explicit invalidation', () => {
  const cache = createConversationCache();
  cache.set(scope('one'), Array.from({ length: 123 }, (_, i) => ({ ...message('one'), message_id: 'm-' + i, content: String(i) })));
  const items = cache.get(scope('one')).items;
  assert.equal(items.length, 50); assert.equal(items[0].content, '73'); assert.equal(items.at(-1).content, '122');
  cache.forget(scope('one')); assert.equal(cache.get(scope('one')), null);
  cache.set(scope('one'), [message('one')]); cache.clear(); assert.equal(cache.stats().bytes, 0);
});
