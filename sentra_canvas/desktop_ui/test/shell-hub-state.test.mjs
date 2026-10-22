import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  activityRecap,
  dotObservation,
  eventVerification,
  formatBytes,
  hubSections,
  instantOf,
} from '../src/shell-hub-state.js';

function localDate(day, hour = 12) {
  return new Date(2026, 9, day, hour, 0, 0);
}

function epochSeconds(date) {
  return Math.floor(date.getTime() / 1000);
}

test('hub vazio não inventa sucesso nem dados ausentes', () => {
  const hub = hubSections({});

  assert.deepEqual(hub.tabs.map(tab => tab.id), ['overview', 'companions', 'activity', 'integrations', 'about']);
  for (const name of ['overview', 'companions', 'activity', 'integrations', 'about']) {
    assert.ok(Array.isArray(hub[name]), name + ' deve ser uma lista');
  }

  const overview = Object.fromEntries(hub.overview.map(item => [item.id, item]));
  assert.equal(overview.project.value, 'Não informado nesta leitura');
  assert.equal(overview.run.value, 'aguardando leitura');
  assert.equal(overview.run.tone, 'unknown');
  assert.equal(overview.run.verified, false);
  assert.equal(overview.approvals.value, 'nenhuma nesta leitura');
  assert.ok(hub.overview.every(item => item.verified === false));

  assert.equal(hub.companions.length, 1);
  assert.equal(hub.companions[0].id, 'companion:none');
  assert.equal(hub.counts.dots, 0);
  assert.equal(hub.counts.approvals, 0);
  assert.equal(hub.counts.verifiedEvents, 0);
  assert.equal(hub.counts.verifiedDots, 0);
  assert.equal(hub.recap.total, 0);
  assert.equal(hub.activity.find(item => item.id === 'verified').value, 'nenhum nesta janela');

  assert.equal(
    hub.about.find(item => item.id === 'attribution').value,
    'Visual inspirado no Coucou (MIT); personagens originais do SENTRA',
  );
  assert.ok(hub.about.every(item => item.verified === false));
});

test('resultado concluído só é verificado com recibo ou estado verificado', () => {
  assert.deepEqual(
    eventVerification({ kind: 'task.completed', payload: { status: 'completed' } }),
    { verified: false, reason: 'sem recibo verificado' },
  );
  assert.deepEqual(
    eventVerification({ kind: 'hook.stop', payload: { status: 'completed' } }),
    { verified: false, reason: 'observação, não conclusão' },
  );
  assert.deepEqual(
    eventVerification({ kind: 'task.completed', payload: { status: 'completed', verified: true } }),
    { verified: true, reason: 'recibo verificado' },
  );
  assert.deepEqual(
    eventVerification({ kind: 'task.completed', payload: { status: 'verified' } }),
    { verified: true, reason: 'estado verificado' },
  );
  assert.deepEqual(
    eventVerification({ kind: 'task.completed', payload: { status: 'completed' }, execution: { verified: true } }),
    { verified: true, reason: 'recibo verificado' },
  );
  assert.deepEqual(
    eventVerification({ kind: 'task.completed', payload: { status: 'completed', receipt_id: 'r-1' } }),
    { verified: false, reason: 'sem recibo verificado' },
  );
  assert.deepEqual(
    eventVerification({ kind: 'task.completed', payload: { status: 'uncertain', verified: true } }),
    { verified: false, reason: 'estado refutado' },
  );
});

test('Dot concluído sem execution.verified continua sendo resultado registrado', () => {
  const observed = dotObservation({ status: 'completed' });
  assert.equal(observed.verified, false);
  assert.match(observed.label, /resultado registrado/);

  const verified = dotObservation({ status: 'completed', execution: { verified: true } });
  assert.equal(verified.verified, true);
  assert.equal(verified.label, 'concluído · recibo verificado');
  assert.equal(dotObservation({ status: 'verified' }).verified, true);

  assert.equal(dotObservation({ status: 'uncertain' }).tone, 'uncertain');

  const hub = hubSections({
    dots: [
      { dot_id: 'd1', name: 'Pudim', status: 'completed' },
      { dot_id: 'd2', name: 'Nuvem', status: 'completed', execution: { verified: true } },
    ],
  });
  assert.equal(hub.counts.verifiedDots, 1);
  assert.match(hub.companions[0].value, /resultado registrado · sem recibo verificado/);
  assert.match(hub.companions[1].value, /concluído · recibo verificado/);
});

test('recap agrupa por dia local, ordena, limita a janela e separa eventos sem data', () => {
  const now = localDate(22);
  const events = [
    {
      event_id: '1',
      kind: 'task.completed',
      payload: { status: 'completed', verified: true },
      created_at: epochSeconds(localDate(22, 9)),
    },
    {
      event_id: '2',
      kind: 'message.sent',
      payload: { status: 'running' },
      created_at: epochSeconds(localDate(22, 8)),
    },
    {
      event_id: '3',
      kind: 'hook.stop',
      payload: { status: 'completed' },
      created_at: localDate(21, 18).toISOString(),
    },
    {
      event_id: '4',
      kind: 'approval.requested',
      payload: { status: 'waiting_approval' },
      timestamp: localDate(20, 10).getTime(),
    },
    { event_id: '5', kind: 'sem.data', payload: {} },
    {
      event_id: '6',
      kind: 'task.completed',
      payload: { status: 'completed' },
      created_at: epochSeconds(localDate(1, 10)),
    },
  ];

  const recap = activityRecap(events, { now, days: 7 });

  assert.equal(recap.days.length, 7);
  assert.deepEqual(recap.days.map(day => day.key), [
    '2026-10-22', '2026-10-21', '2026-10-20', '2026-10-19',
    '2026-10-18', '2026-10-17', '2026-10-16',
  ]);
  assert.equal(recap.days[0].count, 2);
  assert.equal(recap.days[0].verified, 1);
  assert.equal(recap.days[1].count, 1);
  assert.equal(recap.days[1].verified, 0);
  assert.equal(recap.days[2].count, 1);
  assert.equal(recap.undated.count, 1);
  assert.equal(recap.undated.verified, 0);
  assert.equal(recap.total, 5);
  assert.equal(recap.byKind['task.completed'], 1);
  assert.equal(recap.byKind['message.sent'], 1);
  assert.equal(recap.byKind['sem.data'], 1);
  assert.equal(recap.verified, 1);
  assert.deepEqual(recap.window, { days: 7, from: '2026-10-16', to: '2026-10-22' });

  const oneDay = activityRecap([], { now, days: 0 });
  assert.equal(oneDay.days.length, 1);
  assert.equal(oneDay.days[0].key, '2026-10-22');

  const manyDays = activityRecap([], { now, days: 99 });
  assert.equal(manyDays.days.length, 31);
});

test('evento sem created_at ou timestamp cai em sem data, não em um dia inventado', () => {
  const recap = activityRecap([
    { event_id: 'a', kind: 'task.completed', payload: { status: 'completed' } },
    { event_id: 'b', kind: 'message.sent' },
  ], { now: localDate(22), days: 7 });

  assert.equal(recap.undated.count, 2);
  assert.equal(recap.total, 2);
  assert.equal(recap.days.reduce((sum, day) => sum + day.count, 0), 0);
  assert.equal(recap.byKind['task.completed'], 1);
  assert.equal(recap.byKind['message.sent'], 1);
});

test('cartão de atividade não promove completed a verificado', () => {
  const hub = hubSections({
    events: [{
      event_id: 'e1',
      kind: 'task.completed',
      payload: { status: 'completed' },
      created_at: epochSeconds(localDate(22, 9)),
    }],
  });

  assert.equal(hub.counts.verifiedEvents, 0);
  const verifiedCard = hub.activity.find(item => item.id === 'verified');
  assert.equal(verifiedCard.value, 'nenhum nesta janela');
  assert.equal(verifiedCard.verified, false);
});

test('aprovações pendentes são observadas sem decidir por ninguém', () => {
  const hub = hubSections({
    events: [{
      event_id: 'e1',
      kind: 'approval.requested',
      payload: { status: 'waiting_approval', summary: 'Rodar os testes' },
    }],
  });

  assert.equal(hub.counts.approvals, 1);
  assert.equal(hub.approvals.length, 1);
  assert.equal(hub.approvals[0].title, 'Rodar os testes');
  assert.equal(hub.approvals[0].label, 'aguardando decisão');
  assert.equal(hub.approvals[0].tone, 'waiting');
  assert.equal(hub.overview.find(item => item.id === 'approvals').value, '1');
});

test('integrações derivam provedores sem prometer conexão', () => {
  const hub = hubSections({
    models: [
      'openai/gpt-5',
      'anthropic/claude',
      { id: 'local/model', provider: 'local', available: false },
    ],
  });

  assert.equal(hub.models.length, 3);
  assert.deepEqual(hub.providers.map(item => item.id), ['anthropic', 'local', 'openai']);
  assert.equal(hub.integrations.find(item => item.id === 'providers').value, 'anthropic · local · openai');
  assert.match(
    hub.integrations.find(item => item.id === 'providers').detail,
    /não é uma conexão verificada/,
  );
});

test('formatBytes é honesto com tamanho ausente e usa unidade legível', () => {
  assert.equal(formatBytes(undefined), 'tamanho não informado');
  assert.equal(formatBytes(-1), 'tamanho não informado');
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1024), '1 KB');
  assert.equal(formatBytes(1536), '1,5 KB');
  assert.equal(formatBytes(10 * 1024), '10 KB');
  assert.equal(formatBytes(5 * 1024 * 1024), '5 MB');
});

test('instantOf entende segundos, milissegundos, ISO e Date', () => {
  const date = localDate(22, 9);
  assert.equal(instantOf(epochSeconds(date)), date.getTime());
  assert.equal(instantOf(date.getTime()), date.getTime());
  assert.equal(instantOf(date.toISOString()), date.getTime());
  assert.equal(instantOf(date), date.getTime());
  assert.ok(Number.isNaN(instantOf('')));
  assert.ok(Number.isNaN(instantOf('não é uma data')));
});


test('delivery is not task completion and stale success cannot override current failure', () => {
  assert.equal(eventVerification({ payload: { status: 'delivered', receipt_id: 'r-1', task_completion_verified: false } }).verified, false);
  for (const status of ['failed', 'cancelled', 'uncertain', 'running']) {
    assert.equal(dotObservation({ status, execution: { verified: true } }).verified, false);
    assert.equal(eventVerification({ payload: { status, execution: { verified: true } } }).verified, false);
  }
});
