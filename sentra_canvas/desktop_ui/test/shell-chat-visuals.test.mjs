import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CHAT_PRESENCE_STATES, chatEventPillFor, chatPresenceModel, deriveChatTicker, hasCompletionEvidence,
} from '../src/shell-chat-visuals.js';

const stamp = minute => `2026-10-22T12:${String(minute).padStart(2, '0')}:00.000Z`;

test('presença trabalha apenas com execução validada e não declara conclusão', () => {
  const model = chatPresenceModel({
    dot: { status: 'idle', execution: { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' } },
    messages: [],
  });
  assert.equal(model.state, 'working');
  assert.equal(model.label, 'Trabalhando');
  assert.equal(model.verified, false);

  const bareStatus = chatPresenceModel({ dot: { status: 'running', execution: { workItemState: 'RUNNING' } } });
  assert.notEqual(bareStatus.state, 'working');
  assert.equal(bareStatus.verified, false);

  const thinkingTurn = chatPresenceModel({
    dot: { status: 'idle', execution: { verified: true, workItemState: 'SUCCEEDED' } },
    messages: [{ role: 'assistant', status: 'thinking', message_id: 'thinking-1' }],
  });
  assert.equal(thinkingTurn.state, 'thinking');
  assert.equal(thinkingTurn.verified, false);
});

test('presença aguarda aprovação, resposta ou resultado incerto', () => {
  const approval = chatPresenceModel({
    messages: [{ role: 'user', status: 'waiting_approval', operation_id: 'op-approval' }],
  });
  assert.equal(approval.state, 'waiting');
  assert.equal(approval.verified, false);
  assert.match(approval.detail, /Aprovação/i);
  assert.match(approval.lastAction, /Aguardando aprovação/);

  const needsInput = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'needs_input', operation_id: 'op-input' }],
  });
  assert.equal(needsInput.state, 'waiting');
  assert.match(needsInput.detail, /resposta/i);

  const chatgpt = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'waiting_chatgpt_user_approval' }],
  });
  assert.equal(chatgpt.state, 'waiting');
  assert.match(chatgpt.detail, /ChatGPT/);

  const uncertain = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'uncertain', operation_id: 'op-uncertain' }],
  });
  assert.equal(uncertain.state, 'waiting');
  assert.equal(uncertain.verified, false);
  assert.match(uncertain.detail, /não confirmado/i);
  assert.equal(hasCompletionEvidence({ status: 'uncertain', receipt_id: 'receipt-1' }), false);
});

test('presença sinaliza falha e expiração sem promover sucesso', () => {
  const failed = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'failed', operation_id: 'op-failed', reason: 'permissão negada' }],
  });
  assert.equal(failed.state, 'error');
  assert.equal(failed.verified, false);
  assert.match(failed.detail, /permissão negada/);

  const expired = chatPresenceModel({ dot: { status: 'expired' } });
  assert.equal(expired.state, 'error');
  assert.match(expired.detail, /expirada/i);
});

test('done exige recibo ou verificação explícita', () => {
  const withReceipt = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'completed', task_completion_verified: true, receipt_id: 'receipt-42', operation_id: 'op-42' }],
  });
  assert.equal(withReceipt.state, 'done');
  assert.equal(withReceipt.verified, true);
  assert.match(withReceipt.detail, /receipt-42/);

  const verifiedExecution = chatPresenceModel({
    dot: { status: 'completed', execution: { verified: true, workItemState: 'SUCCEEDED' } },
  });
  assert.equal(verifiedExecution.state, 'done');
  assert.equal(verifiedExecution.verified, true);

  const statusOnly = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'completed', operation_id: 'op-without-receipt' }],
  });
  assert.notEqual(statusOnly.state, 'done');
  assert.equal(statusOnly.verified, false);

  const dotOnly = chatPresenceModel({ dot: { status: 'completed' } });
  assert.notEqual(dotOnly.state, 'done');

  assert.equal(hasCompletionEvidence({ status: 'completed', verification: { verified: false } }), false);
  assert.equal(hasCompletionEvidence({ status: 'completed', task_verification: {} }), false);
  assert.equal(hasCompletionEvidence({ status: 'completed', task_verification: { files: [] } }), false);
  assert.equal(hasCompletionEvidence({ status: 'completed', task_verification: { files: [] },
    verification: { verified: true } }), true);
  assert.equal(hasCompletionEvidence({ status: 'completed',
    task_verification: { files: [{ path: 'src/app.js' }] } }), false);
});

test('stop e fim de stream nunca são inferidos como done', () => {
  for (const status of ['stop', 'stopped', 'cancelled', 'idle']) {
    const model = chatPresenceModel({
      messages: [{ role: 'assistant', status, operation_id: 'op-' + status }],
      connectionState: 'connected',
    });
    assert.notEqual(model.state, 'done');
    assert.equal(model.verified, false);
    assert.equal(hasCompletionEvidence({ status, receipt_id: 'receipt-does-not-count' }), false);
  }

  const stoppedWithVerifiedDot = chatPresenceModel({
    messages: [{ role: 'assistant', status: 'stopped', message_id: 'stopped-1' }],
    dot: { status: 'completed', execution: { verified: true, workItemState: 'SUCCEEDED' } },
  });
  assert.notEqual(stoppedWithVerifiedDot.state, 'done');
  assert.equal(stoppedWithVerifiedDot.verified, false);

  const closedStream = chatPresenceModel({
    livePreview: { status: 'closed', content: 'fim do stream', activity: 'Encerrado' },
    connectionState: 'connected',
  });
  assert.notEqual(closedStream.state, 'done');
  assert.equal(closedStream.verified, false);

  const undefinedStatus = chatPresenceModel({ connectionState: 'connected' });
  assert.equal(undefinedStatus.state, 'idle');
  assert.equal(undefinedStatus.verified, false);
});

test('presença ociosa e ouvindo usam apenas sinais explícitos', () => {
  const idle = chatPresenceModel({});
  assert.equal(idle.state, 'idle');
  assert.equal(idle.verified, false);
  assert.equal(idle.label, 'Presente');
  assert.equal(idle.detail, '');

  const listening = chatPresenceModel({ dot: { status: 'listening' } });
  assert.equal(listening.state, 'listening');
  assert.equal(listening.label, 'Ouvindo');

  assert.ok(CHAT_PRESENCE_STATES.includes(idle.state));
  assert.ok(CHAT_PRESENCE_STATES.includes(listening.state));
});

test('ticker limita a quatro passos e preserva a ordem cronológica', () => {
  const messages = [
    { message_id: 'a1', role: 'user', status: 'sent', operation_id: 'op-1', created_at: stamp(1) },
    { message_id: 'a2', role: 'assistant', status: 'running', operation_id: 'op-2', created_at: stamp(2) },
    { message_id: 'a3', role: 'assistant', status: 'completed', task_completion_verified: true, operation_id: 'op-3', receipt_id: 'receipt-3', created_at: stamp(3) },
    { message_id: 'a4', role: 'assistant', status: 'failed', operation_id: 'op-4', created_at: stamp(4) },
    { message_id: 'a5', role: 'assistant', status: 'completed', task_completion_verified: true, operation_id: 'op-5', receipt_id: 'receipt-5', created_at: stamp(5) },
    { message_id: 'a6', role: 'assistant', status: 'completed', task_completion_verified: true, operation_id: 'op-6', receipt_id: 'receipt-6', created_at: stamp(6) },
  ];
  const items = deriveChatTicker({ messages, limit: 4 });
  assert.equal(items.length, 4);
  assert.deepEqual(items.map(item => item.at), [stamp(3), stamp(4), stamp(5), stamp(6)]);
  assert.deepEqual(items.map(item => item.kind), ['done', 'error', 'done', 'done']);
  assert.deepEqual(items.map(item => item.id), ['receipt:receipt-3', 'operation:op-4', 'receipt:receipt-5', 'receipt:receipt-6']);
});

test('ticker não duplica a mesma operação nem recibo', () => {
  const messages = [
    { message_id: 'user-1', role: 'user', status: 'sent', operation_id: 'op-shared', created_at: stamp(1) },
    { message_id: 'assistant-1', role: 'assistant', status: 'completed', task_completion_verified: true, operation_id: 'op-shared', receipt_id: 'receipt-shared', created_at: stamp(2) },
    { message_id: 'assistant-2', role: 'assistant', status: 'completed', task_completion_verified: true, operation_id: 'op-shared', receipt_id: 'receipt-shared', created_at: stamp(3) },
  ];
  const items = deriveChatTicker({ messages, limit: 4 });
  assert.equal(items.length, 1);
  assert.equal(items[0].step, 'Concluído e verificado');
  assert.equal(items[0].detail, 'receipt-shared');
  assert.equal(new Set(items.map(item => item.id)).size, items.length);
});

test('ticker ignora otimista e não transforma incerto em done', () => {
  const messages = [
    { message_id: 'local-1', role: 'user', status: 'sending', optimistic: true, created_at: stamp(1) },
    { message_id: 'assistant-1', role: 'assistant', status: 'uncertain', operation_id: 'op-uncertain', created_at: stamp(2) },
  ];
  const items = deriveChatTicker({ messages, limit: 4 });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, 'uncertain');
  assert.equal(items[0].step, 'Resultado não confirmado');
  assert.ok(!items.some(item => item.step === 'Enviando mensagem'));
  assert.ok(!items.some(item => item.kind === 'done'));
});

test('ticker usa a prévia uma vez e não a duplica após a mensagem confirmada', () => {
  const preview = { status: 'generating', activity: 'Recebendo resposta', content: 'texto parcial',
    operation_id: 'op-live', received_at_ms: 1761139200000 };
  const onlyPreview = deriveChatTicker({ messages: [], livePreview: preview });
  assert.equal(onlyPreview.length, 1);
  assert.equal(onlyPreview[0].kind, 'working');
  assert.equal(onlyPreview[0].step, 'Recebendo resposta');
  assert.equal(onlyPreview[0].at, 1761139200000);

  const confirmed = deriveChatTicker({ messages: [
    { message_id: 'assistant-live', role: 'assistant', status: 'completed', task_completion_verified: true, operation_id: 'op-live',
      receipt_id: 'receipt-live', created_at: stamp(5) },
  ], livePreview: preview });
  assert.equal(confirmed.length, 1);
  assert.equal(confirmed[0].kind, 'done');
  assert.equal(confirmed[0].detail, 'receipt-live');
});

test('ticker vazio não inventa atividade e sempre respeita o teto de quatro', () => {
  assert.deepEqual(deriveChatTicker({}), []);
  assert.deepEqual(deriveChatTicker({ messages: [{ role: 'assistant', content: 'sem status' }] }), []);
  assert.deepEqual(deriveChatTicker({ messages: [{ role: 'assistant', status: 'idle' }] }), []);
  assert.deepEqual(deriveChatTicker({ livePreview: { status: 'closed', content: 'fim do stream',
    activity: 'Encerrado' } }), []);

  const messages = Array.from({ length: 9 }, (_, index) => ({
    message_id: 'm' + index, role: 'assistant', status: index === 8 ? 'failed' : 'running',
    operation_id: 'op-' + index, created_at: stamp(index),
  }));
  assert.equal(deriveChatTicker({ messages, limit: 99 }).length, 4);
  assert.equal(deriveChatTicker({ messages, limit: 4 }).at(-1).kind, 'error');
});

test('pill de evento só aparece com status, operação ou recibo', () => {
  assert.equal(chatEventPillFor({ role: 'assistant', content: 'sem metadados' }), null);
  assert.deepEqual(chatEventPillFor({ status: 'waiting_approval' }), {
    kind: 'approval', label: 'Aguardando aprovação', detail: '',
  });
  assert.equal(chatEventPillFor({ status: 'uncertain', operation_id: 'op-1' }).kind, 'uncertain');
  assert.equal(chatEventPillFor({ status: 'failed' }).kind, 'error');
  assert.equal(chatEventPillFor({ status: 'completed', task_completion_verified: true, receipt_id: 'receipt-1' }).kind, 'done');
  assert.deepEqual(chatEventPillFor({ status: 'completed' }), {
    kind: 'tool', label: 'Resultado registrado', detail: 'Sem verificação explícita',
  });
});


test('delivery receipts, arbitrary verification text and contradictory states never complete tasks', () => {
  for (const value of [
    { status: 'completed', receipt_id: 'delivery-only' },
    { status: 'completed', task_completion_verified: false, receipt_id: 'delivery-only' },
    { status: 'completed', task_verification: 'please trust me' },
    { status: 'completed', execution: { verified: 'true' } },
    { status: 'failed', verified: true },
    { status: 'cancelled', execution: { verified: true } },
    { status: 'completed', execution: { verified: true, workItemState: 'RUNNING' } },
  ]) assert.equal(hasCompletionEvidence(value), false, JSON.stringify(value));
  assert.notEqual(chatPresenceModel({ dot: { status: 'cancelled', execution: { verified: true } } }).state, 'done');
  const previous = { status: 'completed', execution: { verified: true, operation_id: 'previous-turn' } };
  assert.notEqual(chatPresenceModel({ dot: previous,
    messages: [{ role: 'user', status: 'sent', operation_id: 'new-turn' }] }).state, 'done');
  assert.notEqual(chatPresenceModel({ dot: previous,
    messages: [{ role: 'assistant', status: 'completed', operation_id: 'new-turn' }] }).state, 'done');
});
