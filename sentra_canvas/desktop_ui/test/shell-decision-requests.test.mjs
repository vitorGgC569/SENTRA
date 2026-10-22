import { test } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { DecisionRequests } from '../src/shell-decision-requests.js';
import { WorkspaceRequestJournal } from '../src/workspace/request-journal.js';
import { testLocks } from './lock-harness.mjs';

const item = { approval_id: 'approval-1', space_id: 'space-1', conversation_id: 'conversation-1' };
function fixture() {
  const data = new Map(), locks = testLocks();
  let effects = 0, fail = true, resolved = true;
  const calls = [];
  const bridge = async request => {
    calls.push(request);
    if (request.action === 'coordinator_approval_reply') {
      effects += 1;
      if (fail) throw Error('lost ACK');
      return { state: 'approved' };
    }
    return { resolved, automatic_retry: false, request_key: request.selector.request_key };
  };
  const journal = () => new WorkspaceRequestJournal('decision-center:project-1', {
    storage: { getItem: key => data.get(key), setItem: (key, value) => data.set(key, value) }, locks, crypto: webcrypto,
  });
  const client = () => new DecisionRequests('project-1', { journal: journal(), bridge, crypto: webcrypto });
  return { data, calls, client, effects: () => effects, setFail: value => { fail = value; }, setResolved: value => { resolved = value; } };
}
test('lost approval ACK survives reopening and consultation never sends again', async () => {
  const f = fixture(), first = f.client();
  await assert.rejects(first.send(item, 'approve'), /lost ACK/);
  assert.equal(f.effects(), 1);
  const reopened = f.client();
  assert.equal(reopened.pending().length, 1);
  await assert.rejects(reopened.send(item, 'reject'), /pendente/);
  await reopened.inspect(item.approval_id);
  assert.equal(f.effects(), 1);
  assert.equal(reopened.pending().length, 0);
  assert.deepEqual(f.calls.map(call => call.action), ['coordinator_approval_reply', 'conversation_permission_status']);
  assert.equal(f.calls[1].conversation_id, item.conversation_id);
  assert.equal(f.calls[1].space_id, item.space_id);
  assert.equal([...f.data.values()].join('').includes('approve'), false);
});
test('unresolved inspection retains the original selector', async () => {
  const f = fixture();
  await assert.rejects(f.client().send(item, 'approve'));
  const original = f.client().pending()[0];
  f.setResolved(false);
  await f.client().inspect(item.approval_id);
  assert.equal(f.client().pending()[0].request_key, original.request_key);
  assert.equal(f.effects(), 1);
});
test('competing windows dispatch a decision at most once', async () => {
  const f = fixture(); f.setFail(false);
  const a = f.client(), b = f.client();
  await Promise.allSettled([a.send(item, 'approve'), b.send(item, 'reject')]);
  assert.equal(f.effects(), 1);
});
test('confirmed reply still requires a matching host inspection before clearing', async () => {
  const f = fixture(); f.setFail(false); f.setResolved(false);
  await f.client().send(item, 'approve');
  assert.equal(f.client().pending().length, 1);
  f.setResolved(true); await f.client().inspect(item.approval_id);
  assert.equal(f.client().pending().length, 0);
});
test('malformed scope or unavailable persistence cannot dispatch an approval', async () => {
  const f = fixture();
  await assert.rejects(f.client().send({ ...item, space_id: '' }, 'approve'));
  f.data.set('sentra-workspace-intents-v1:decision-center:project-1', 'invalid');
  await assert.rejects(f.client().send(item, 'approve'));
  assert.equal(f.effects(), 0);
});
