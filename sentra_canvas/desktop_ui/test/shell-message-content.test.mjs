import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, webcrypto } from 'node:crypto';
import { completeMessage } from '../src/shell-message-content.js';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const body = 'Mensagem completa [[wiki]] 🦉';
const sha256 = createHash('sha256').update(body).digest('hex');
const message = {message_id:'message-one', content:'prévia', content_truncated:true,
  content_ref:{action:'message_content',message_id:'message-one',revision:3,sha256,total_chars:[...body].length}};
const page = {revision:3,sha256,total_chars:[...body].length,offset:0,content:body,next_offset:null};

test('canonical original is reconstructed and verified without changing its receipt', async () => {
  const result = await completeMessage({...message, receipt_id:'existing-receipt'}, async () => page, {});
  assert.equal(result.content, body); assert.equal(result.content_truncated, false);
  assert.equal(result.receipt_id, 'existing-receipt');
});

test('late canonical page cannot survive lost access or start another page', async () => {
  for (const next_offset of [null, 10]) {
    let active = true, requests = 0;
    await assert.rejects(completeMessage(message, async () => {
      requests++; active = false; return {...page,next_offset};
    }, {}, () => active), /interrompida/);
    assert.equal(requests, 1);
  }
});

test('lost access during final digest cannot return canonical body', async () => {
  let active = true;
  const digest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle);
  const patched = mock.method(globalThis.crypto.subtle, 'digest', async (...args) => {
    const result = await digest(...args); active = false; return result;
  });
  try { await assert.rejects(completeMessage(message, async () => page, {}, () => active), /interrompida/); }
  finally { patched.mock.restore(); }
});
