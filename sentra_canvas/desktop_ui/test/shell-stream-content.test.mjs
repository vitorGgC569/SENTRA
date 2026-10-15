import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import { readStreamContent } from '../src/shell-stream-content.js';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const hash = value => createHash('sha256').update(value).digest('hex');
const scope = { project_id: 'project', space_id: 'space', conversation_id: 'conversation', owner: 'excluded', token: 'excluded' };
const body = '🦉é'.repeat(70000) + '\n[[texto legítimo]] <script>não executar</script> ha haha';
const chars = [...body];
function fixture(text = body) {
  const points = [...text];
  const reference = { reference_id: 'stream-' + 'a'.repeat(64), sha256: hash(text), total_chars: points.length,
    total_utf8_bytes: Buffer.byteLength(text), action: 'stream_content', page_max_chars: 65536, page_max_utf8_bytes: 262144 };
  const requests = [];
  const read = async fields => {
    requests.push(fields);
    const content = points.slice(fields.offset, fields.offset + fields.limit).join('');
    return { project_id: 'project', space_id: 'space', conversation_id: 'conversation', reference_id: reference.reference_id,
      sha256: reference.sha256, page_sha256: hash(content), content, offset: fields.offset,
      total_chars: reference.total_chars, total_utf8_bytes: reference.total_utf8_bytes,
      next_offset: fields.offset + [...content].length < points.length ? fields.offset + [...content].length : null,
      persisted: true, partial: true, authoritative: false, closes_trio: false, automatic_retry: false };
  };
  return { reference, read, requests };
}

test('reconstructs Unicode by server cursor and verifies all bytes without authority', async () => {
  const { reference, read, requests } = fixture();
  const result = await readStreamContent(read, scope, reference);
  assert.equal(result.items.map(page => page.content).join(''), body);
  assert.equal(result.total_chars, chars.length);
  assert.equal(result.authoritative, false); assert.equal(result.partial, true); assert.equal(result.closes_trio, false);
  assert.deepEqual(requests.map(request => request.offset), [0, 65536, 131072]);
  assert.ok(requests.every(request => Object.keys(request).sort().join(',') === 'conversation_id,limit,offset,project_id,reference_id,space_id'));
});

test('rejects altered page bytes, scope, authority and a cursor counted as UTF-16', async () => {
  for (const alter of [page => ({ ...page, content: 'changed' }), page => ({ ...page, conversation_id: 'other' }),
    page => ({ ...page, authoritative: true }), page => ({ ...page, next_offset: page.offset + page.content.length }),
    page => ({ ...page, sha256: 'b'.repeat(64) }), page => ({ ...page, page_sha256: 'b'.repeat(64) })]) {
    const { reference, read, requests } = fixture();
    await assert.rejects(() => readStreamContent(async fields => alter(await read(fields)), scope, reference));
    assert.equal(requests.length, 1);
  }
});

test('whole-body hash is mandatory even when each individual page has a valid hash', async () => {
  const { reference, read } = fixture();
  const changed = { ...reference, sha256: 'b'.repeat(64) };
  await assert.rejects(() => readStreamContent(async fields => ({ ...await read(fields), sha256: changed.sha256 }), scope, changed), /conferir/);
});

test('expired authorization or reference is never retried or converted into an effect', async () => {
  for (const status of [401, 403, 404, 503]) {
    const { reference, read, requests } = fixture();
    let calls = 0;
    await assert.rejects(() => readStreamContent(async fields => {
      calls++; if (calls === 2) throw Object.assign(Error('unavailable'), { status });
      return read(fields);
    }, scope, reference), error => error.status === status);
    assert.equal(calls, 2); assert.equal(requests.length, 1);
  }
});

test('cancelled and late observations cannot publish content or fetch another page', async () => {
  const { reference, read, requests } = fixture();
  const controller = new AbortController();
  await assert.rejects(() => readStreamContent(read, scope, reference, { signal: controller.signal,
    onProgress: () => controller.abort() }), error => error.name === 'AbortError');
  assert.equal(requests.length, 1);
  const late = new AbortController(); let resolve;
  const pending = readStreamContent(() => new Promise(done => { resolve = done; }), scope, reference, { signal: late.signal });
  late.abort(); resolve(await read({ offset: 0, limit: 65536 }));
  await assert.rejects(() => pending, error => error.name === 'AbortError');
});

test('invalid references and declared budgets fail before issuing any request', async () => {
  const { reference } = fixture();
  for (const altered of [{ ...reference, total_utf8_bytes: 8000001 }, { ...reference, total_chars: -1 },
    { ...reference, action: 'message_send' }, { ...reference, page_max_chars: 1000000 }]) {
    await assert.rejects(() => readStreamContent(() => { throw Error('should not fetch'); }, scope, altered), /inválida/);
  }
});
