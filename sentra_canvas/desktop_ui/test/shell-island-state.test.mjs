import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  islandBadge, islandGreeting, islandSessions, islandShouldShow, islandStatusLabel,
  islandSummary, islandTicker, islandTone,
} from '../src/shell-island-state.js';

const NOW = Date.parse('2026-10-22T15:30:00.000Z');

test('an unverified completion is never presented as success', () => {
  assert.equal(islandTone('completed'), 'review');
  assert.equal(islandTone('succeeded'), 'review');
  assert.equal(islandTone('completed', { verified: true }), 'done');
  assert.equal(islandTone('completed', { verified: false }), 'review');
  assert.equal(islandTone('waiting_approval'), 'wait');
  assert.equal(islandTone('uncertain'), 'wait');
  assert.equal(islandTone('failed'), 'error');
  assert.equal(islandTone('running'), 'work');
  assert.equal(islandTone('idle'), 'idle');
  assert.equal(islandStatusLabel('completed'), 'Resultado registrado');
  assert.equal(islandStatusLabel('completed', { verified: true }), 'Concluído e verificado');
});

test('validated host execution wins over a bare status', () => {
  assert.equal(islandTone('idle', { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' }), 'work');
  assert.equal(islandTone('idle', { validated: false, workItemState: 'RUNNING' }), 'idle');
});

test('sessions put owner attention first and use the latest conversation detail', () => {
  const dots = [
    { dot_id: 'd1', name: 'Ocioso', status: 'idle' },
    { dot_id: 'd2', name: 'Oxta', status: 'waiting_approval', mascot: 'oxta' },
    { dot_id: 'd3', name: 'Build', status: 'running' },
  ];
  const conversations = [
    { conversation_id: 'c3', dot_id: 'd3', title: 'Rodando testes', updated_at: '2026-10-22T14:00:00Z' },
    { conversation_id: 'c2', dot_id: 'd2', title: 'Publicar release', updated_at: '2026-10-22T13:00:00Z' },
  ];
  const sessions = islandSessions({ dots, conversations, events: [] });
  assert.deepEqual(sessions.map(row => row.dotId), ['d2', 'd3', 'd1']);
  assert.equal(sessions[0].conversationId, 'c2');
  assert.equal(sessions[0].detail, 'Publicar release');
  assert.equal(sessions[0].label, 'Aguardando você');
  assert.equal(sessions[1].detail, 'Rodando testes');
});

test('session detail prefers the most recent observed event for the Dot', () => {
  const sessions = islandSessions({
    dots: [{ dot_id: 'd1', name: 'Oxta', status: 'running' }],
    conversations: [{ conversation_id: 'c1', dot_id: 'd1', title: 'Conversa' }],
    events: [{ event_id: 'e1', payload: { dot_id: 'd1', summary: 'Terminal aberto' }, created_at: '2026-10-22T15:00:00Z' }],
  });
  assert.equal(sessions[0].detail, 'Terminal aberto');
});

test('an event from another turn cannot contradict the current Dot state', () => {
  const sessions = islandSessions({
    dots: [{ dot_id: 'd1', name: 'Lume', status: 'failed' }],
    conversations: [{ conversation_id: 'c1', dot_id: 'd1', title: 'Build do instalador' }],
    events: [{ event_id: 'e1', payload: { dot_id: 'd1', status: 'verified', summary: 'Recibo conferido' }, created_at: '2026-10-22T15:00:00Z' }],
  });
  assert.equal(sessions[0].detail, 'Build do instalador');
  assert.equal(sessions[0].tone, 'error');
});

test('summary and badge separate work from owner attention', () => {
  const sessions = [
    { tone: 'work' }, { tone: 'wait' }, { tone: 'error' }, { tone: 'idle' }, { tone: 'done' },
  ];
  assert.deepEqual(islandSummary(sessions, [{}, {}]), {
    active: 3, working: 1, waiting: 2, decisions: 2, total: 5,
  });
  assert.deepEqual(islandSummary(sessions, 2), {
    active: 3, working: 1, waiting: 2, decisions: 2, total: 5,
  });
  assert.equal(islandBadge(sessions, [{}, {}]), 4);
  assert.equal(islandBadge(sessions, 2), 4);
  assert.equal(islandBadge([], []), 0);
  assert.equal(islandShouldShow({ enabled: true, hideWhenIdle: true, sessions: [], decisions: 1 }), true);
});

test('the ticker is bounded, recent and ordered', () => {
  const events = [
    { event_id: 'old', kind: 'old', created_at: '2026-10-22T12:00:00Z', payload: { summary: 'Antigo' } },
    { event_id: 'a', kind: 'terminal', created_at: '2026-10-22T15:20:00Z', payload: { summary: 'Primeiro' } },
    { event_id: 'b', kind: 'approval', created_at: '2026-10-22T15:25:00Z', payload: { summary: 'Segundo', status: 'waiting_approval' } },
    { event_id: 'c', kind: 'receipt', created_at: '2026-10-22T15:26:00Z', payload: { summary: 'Terceiro' } },
    { event_id: 'd', kind: 'no-date', payload: { summary: 'Sem data' } },
  ];
  const rows = islandTicker(events, { limit: 3, now: NOW, maxAgeMs: 15 * 60 * 1000 });
  assert.deepEqual(rows.map(row => row.id), ['c', 'b', 'a']);
  assert.equal(rows[1].tone, 'wait');
  assert.ok(rows.every(row => row.time));
});

test('greeting follows the local day period', () => {
  const at = hour => new Date(2026, 9, 22, hour, 0, 0).getTime();
  assert.equal(islandGreeting(at(3)), 'Boa noite');
  assert.equal(islandGreeting(at(8)), 'Bom dia');
  assert.equal(islandGreeting(at(14)), 'Boa tarde');
  assert.equal(islandGreeting(at(21)), 'Boa noite');
});

test('visibility is driven by the explicit preference, not by work existing', () => {
  assert.equal(islandShouldShow({ enabled: false, sessions: [{ tone: 'work' }] }), false);
  assert.equal(islandShouldShow({ enabled: true, sessions: [] }), true);
  assert.equal(islandShouldShow({ enabled: true, sessions: [], hideWhenIdle: true }), false);
  assert.equal(islandShouldShow({ enabled: true, sessions: [{ tone: 'work' }], hideWhenIdle: true }), true);
});
