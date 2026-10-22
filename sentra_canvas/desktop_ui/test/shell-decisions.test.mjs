import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DECISION_PREVIEW_LIMITS, decisionExpiry, decisionFingerprint, formatRemaining, limitPreview, summarizeDecision,
} from '../src/shell-decisions.js';

const baseItem = {
  approval_id: 'coordinator-abc',
  capability: 'canvas.coordinator.dot_create',
  conversation_id: 'conversation-1',
  space_id: 'space-1',
  activity: 'active',
  summary: { kind: 'create_dot', name: 'Terminal_Teste' },
  automatic_execution: false,
};

test('decisionFingerprint is stable, bounded and free of secrets', () => {
  const value = decisionFingerprint(baseItem);
  assert.equal(value, 'coordinator-abc|canvas.coordinator.dot_create|create_dot|conversation-1');
  assert.equal(decisionFingerprint({ ...baseItem, summary: { ...baseItem.summary } }), value);
  assert.equal(decisionFingerprint({ ...baseItem, summary: undefined }), decisionFingerprint({ ...baseItem, summary: {} }));
  assert.notEqual(decisionFingerprint({ ...baseItem, capability: 'canvas.coordinator.handoff' }), value);
  assert.notEqual(decisionFingerprint({ ...baseItem, conversation_id: 'conversation-2' }), value);
  assert.equal(decisionFingerprint({}).split('|').length, 4);
  const noisy = decisionFingerprint({ ...baseItem, token: 'super-secret', secret: 'hidden', authorization: 'Bearer live' });
  assert.equal(noisy, value);
  assert.equal(noisy.includes('super-secret'), false);
  assert.doesNotMatch(noisy, /token|secret|authorization/i);
  const long = decisionFingerprint({ ...baseItem, approval_id: 'a'.repeat(500), capability: 'b'.repeat(500) });
  assert.ok(long.length <= 4 * 160 + 3);
});

test('decisionExpiry accepts seconds, milliseconds and inactive turns', () => {
  const seconds = { ...baseItem, expires_at: 1800000300 };
  assert.deepEqual(decisionExpiry(seconds, 1800000000000),
    { expiresAt: 1800000300000, remainingMs: 300000, expired: false });
  const millis = { ...baseItem, expires_at: 1800000300000 };
  assert.deepEqual(decisionExpiry(millis, 1800000000000),
    { expiresAt: 1800000300000, remainingMs: 300000, expired: false });
  assert.deepEqual(decisionExpiry({ ...baseItem, expires_at: '1800000300' }, 1800000400000),
    { expiresAt: 1800000300000, remainingMs: 0, expired: true });
  const inactive = { ...baseItem, activity: 'expired', expires_at: 1800000300 };
  assert.deepEqual(decisionExpiry(inactive, 1800000000000),
    { expiresAt: 1800000300000, remainingMs: 300000, expired: true });
  assert.deepEqual(decisionExpiry({ ...baseItem, activity: undefined }, 1800000000000),
    { expiresAt: null, remainingMs: null, expired: true });
  assert.deepEqual(decisionExpiry({ ...baseItem, activity: 'active', expires_at: 0 }, 1800000000000),
    { expiresAt: null, remainingMs: null, expired: false });
  // The helper never reads the clock: equal inputs must stay equal across calls.
  assert.deepEqual(decisionExpiry(seconds, 1800000000000), decisionExpiry(seconds, 1800000000000));
});

test('formatRemaining stays human and never reports negative time', () => {
  assert.equal(formatRemaining(300000), 'expira em 5:00');
  assert.equal(formatRemaining(59000), 'expira em 59 s');
  assert.equal(formatRemaining(0), 'tempo esgotado');
  assert.equal(formatRemaining(-4000), 'tempo esgotado');
  assert.equal(formatRemaining(null), '');
  assert.equal(formatRemaining(Number.NaN), '');
});

test('summarizeDecision never leaks credential fields or values', () => {
  const item = {
    ...baseItem,
    token: 'tok-9d21',
    secret: 'shh-9912',
    authorization: 'Bearer live-4451',
    api_key: 'key-7712',
    summary: {
      ...baseItem.summary,
      command: 'curl -H "Authorization: Bearer live-4451" --token tok-9d21 https://example.invalid',
      secret: 'shh-9912',
      diff: 'const token = "tok-9d21";\n+password: hunter2',
    },
  };
  const model = summarizeDecision(item);
  const serialized = JSON.stringify(model);
  for (const secret of ['tok-9d21', 'shh-9912', 'live-4451', 'key-7712', 'hunter2']) {
    assert.equal(serialized.includes(secret), false, secret);
  }
  assert.match(model.command, /Authorization: •••/);
  assert.match(model.command, /--token •••/);
  assert.match(model.diff, /token = •••/);
  assert.match(model.diff, /\+password: •••/);
  assert.equal(Object.hasOwn(model, 'token'), false);
  assert.equal(Object.hasOwn(model, 'secret'), false);
  assert.equal(Object.hasOwn(model, 'authorization'), false);
});

test('summarizeDecision bounds diff and command previews to 12 lines and 1200 chars', () => {
  const manyLines = Array.from({ length: 20 }, (_, index) => '+linha ' + (index + 1)).join('\n');
  const model = summarizeDecision({ ...baseItem, summary: { ...baseItem.summary, diff: manyLines } });
  assert.equal(model.diff.split('\n').length, DECISION_PREVIEW_LIMITS.lines);
  assert.equal(model.diffTruncated, true);
  assert.equal(model.diffHiddenLines, 8);
  assert.equal(model.diff.includes('linha 13'), false);
  const longLine = summarizeDecision({ ...baseItem, summary: { ...baseItem.summary, diff: 'x'.repeat(4000) } });
  assert.ok(longLine.diff.length <= DECISION_PREVIEW_LIMITS.chars);
  assert.equal(longLine.diffTruncated, true);
  const windows = summarizeDecision({ ...baseItem, summary: { ...baseItem.summary, command: 'a\r\nb\r\nc' } });
  assert.equal(windows.command, 'a\nb\nc');
  assert.equal(windows.commandTruncated, false);
  assert.deepEqual(limitPreview('a\nb\nc'), { text: 'a\nb\nc', truncated: false, totalLines: 3, hiddenLines: 0 });
});

test('summarizeDecision reports host fields without inventing activity', () => {
  const model = summarizeDecision({ ...baseItem, expires_at: 1800000300, created_at: 1800000000, mascot: 'oxta' });
  assert.equal(model.title, 'Terminal_Teste');
  assert.equal(model.kind, 'create_dot');
  assert.equal(model.capability, 'canvas.coordinator.dot_create');
  assert.equal(model.capabilityLabel, 'criar Dot');
  assert.equal(model.conversationId, 'conversation-1');
  assert.equal(model.spaceId, 'space-1');
  assert.equal(model.expiresAt, 1800000300000);
  assert.equal(model.createdAt, 1800000000000);
  assert.equal(model.active, true);
  assert.equal(model.automaticExecution, false);
  assert.equal(model.mascot, 'oxta');
  assert.equal(model.fingerprint, decisionFingerprint(baseItem));
  assert.equal(summarizeDecision({ ...baseItem, activity: 'expired' }).active, false);
  assert.equal(summarizeDecision({}).title, 'Ação do Dot');
  assert.equal(summarizeDecision({}).active, false);
  assert.equal(summarizeDecision({ ...baseItem, summary: { kind: 'handoff' } }).title, 'Enviar uma instrução');
  const fromArguments = summarizeDecision({ ...baseItem, arguments: { diff: '+arquivo novo' } });
  assert.equal(fromArguments.diff, '+arquivo novo');
});
