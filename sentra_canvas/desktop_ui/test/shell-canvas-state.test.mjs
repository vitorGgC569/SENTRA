import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PHASES, canvasPhase, taskPresentation, summarizePhases} from '../src/shell-canvas-state.js';

test('canvas exposes the seven phases and the unsafe states refuse a resend', () => {
  assert.deepEqual(PHASES.map(item => item.id), ['planning', 'executing', 'waiting', 'review', 'completed', 'failed', 'uncertain']);
  const copy = id => PHASES.find(item => item.id === id).safeNext;
  assert.match(copy('planning'), /reenviado/);
  assert.match(copy('executing'), /Não inicie a mesma/);
  assert.match(copy('waiting'), /Não reenvie/);
  assert.match(copy('review'), /Revise o recibo/);
  assert.match(copy('completed'), /Não há repetição/);
  assert.match(copy('failed'), /não é reenviada/);
  assert.match(copy('uncertain'), /Não reenvie/);
});

test('uncertain wins, then review, then terminal states', () => {
  assert.equal(canvasPhase({operationState: 'UNCERTAIN', workItemState: 'FAILED', taskStatus: 'running'}), 'uncertain');
  assert.equal(canvasPhase({taskStatus: 'unconfirmed'}), 'uncertain');
  assert.equal(canvasPhase({workItemState: 'IN_REVIEW', operationState: 'SUCCEEDED'}), 'review');
  assert.equal(canvasPhase({operationState: 'FAILED'}), 'failed');
  assert.equal(canvasPhase({workItemState: 'SUCCEEDED'}), 'completed');
  assert.equal(canvasPhase({taskStatus: 'waiting_approval'}), 'waiting');
  assert.equal(canvasPhase({operationState: 'PENDING'}), 'executing');
  assert.equal(canvasPhase({}), 'planning');
});

test('a task shows owner, dependency, progress and receipt without resend', () => {
  const view = taskPresentation({
    status: 'running', agent_id: 'agent-1', depends_on: 'task-0', progress: '2/4', work_item_id: 'wi-1',
  }, {owner: 'Atlas'});
  assert.equal(view.phase, 'executing');
  assert.equal(view.owner, 'Atlas');
  assert.equal(view.dependency, 'task-0');
  assert.equal(view.progress, '2/4');
  assert.equal(view.receipt, 'wi-1');
  assert.equal(view.resend, false);
});

test('phase counts include tasks and receipts as separate signals', () => {
  const counts = Object.fromEntries(summarizePhases(
    [{status: 'running'}, {status: 'uncertain'}],
    [{work_item_state: 'IN_REVIEW', operation_state: 'SUCCEEDED'}],
  ).map(item => [item.id, item.count]));
  assert.equal(counts.executing, 1);
  assert.equal(counts.uncertain, 1);
  assert.equal(counts.review, 1);
  assert.equal(counts.planning, 0);
});
