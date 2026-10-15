import {test} from 'node:test';
import assert from 'node:assert/strict';
import {dotPhase, dotContextLine, groupHomeConversations, homeBoard, unconfirmedWorkLabel, workSupportLine} from '../src/shell-home-board.js';

const home = {
  space: {space_id: 's1'},
  run: {state: 'RUNNING'},
  dots: [{dot_id: 'd1', name: 'Atlas', status: 'ready'}, {dot_id: 'd2', name: 'Nara', status: 'idle'}],
  conversations: [
    {conversation_id: 'c1', dot_id: 'd2', space_id: 's1', title: 'Revisão do mapa', status: 'waiting_approval'},
    {conversation_id: 'c2', dot_id: 'd1', space_id: 's1', title: 'Entrega do relatório', status: 'completed'},
    {conversation_id: 'c3', dot_id: 'd1', space_id: 's1', title: 'Cópia interrompida', status: 'uncertain'},
  ],
  spaces: [
    {space_id: 's1', project_id: 'p1', name: 'Mapa', description: 'em curso'},
    {space_id: 's2', project_id: 'p1', name: 'Arquivo', description: 'parado'},
  ],
  activity: {items: [
    {event_id: 'e1', kind: 'operation_failed', payload: {status: 'uncertain', summary: 'Cópia não confirmada'}},
    {event_id: 'e2', kind: 'receipt', payload: {status: 'succeeded', summary: 'Recibo do terminal'}},
    {event_id: 'e3', kind: 'approval_requested', payload: {summary: 'Aprovar publicação'}},
  ]},
};

test('an empty project explains that there is nothing to continue', () => {
  const board = homeBoard({});
  assert.equal(board.empty, true);
  assert.deepEqual(board.recentDots, []);
  assert.deepEqual(board.inProgress, []);
  assert.deepEqual(board.approvals, []);
  assert.deepEqual(board.deliveries, []);
  assert.deepEqual(board.failures, []);
});

test('home lists recent dots, the running project, approvals, deliveries and failures', () => {
  const board = homeBoard(home, {
    pending: [{request_key: 'req-1', action: 'conversation_create'}],
    surface: {view: 'canvas', project_id: 'p1', space_id: 's1', dot_id: 'd1', conversation_id: null},
  });
  assert.deepEqual(board.recentDots.map(row => row.dot_id), ['d2', 'd1']);
  assert.equal(board.surface.label, 'Canvas');
  assert.deepEqual(board.inProgress.map(row => row.space_id), ['s1']);
  assert.equal(board.projects.find(row => row.space_id === 's1').project_id, 'p1');
  assert.ok(board.approvals.some(item => item.conversation_id === 'c1' && item.kind === 'conversation'));
  assert.ok(board.approvals.some(item => item.kind === 'event'));
  assert.ok(board.approvals.some(item => item.kind === 'pending'));
  assert.ok(board.deliveries.some(item => item.id === 'conversation-delivery:c2'));
  assert.ok(board.deliveries.some(item => item.id === 'delivery:e2'));
  assert.ok(board.failures.some(item => item.status === 'uncertain'));
  assert.ok(board.failures.some(item => item.id === 'conversation-failure:c3'));
});

test('raw active is Ativo and Trabalhando needs a validated execution', () => {
  assert.deepEqual(dotPhase('active'), {id: 'active', label: 'Ativo', color: '#c5c8ce'});
  assert.notEqual(dotPhase('running').label, 'Trabalhando');
  assert.equal(dotPhase('running', {validated: true, work_item_state: 'RUNNING'}).label, 'Trabalhando');
  assert.deepEqual(dotPhase('waiting_approval'), {id: 'waiting', label: 'Espera', color: '#e2b15a'});
  assert.equal(dotPhase('completed').label, 'Concluído');
  const board = homeBoard({dots: [{dot_id: 'd', name: 'Nara', status: 'active'}], spaces: [{space_id: 's', name: 'Oxta'}], space: {space_id: 's'}});
  assert.equal(board.recentDots[0].fact, 'Ativo');
  assert.equal(board.recentDots[0].status, 'active');
  assert.equal(board.recentDots[0].execution, undefined);
  assert.equal(Object.hasOwn(board.recentDots[0], 'executionValidated'), false);
  assert.equal(board.recentDots[0].fact.includes('active'), false);
  const proof = {validated: true, work_item_state: 'RUNNING', operation_state: 'RUNNING'};
  const proven = homeBoard({dots: [{dot_id: 'd', name: 'Nara', status: 'active', execution: proof}], spaces: [{space_id: 's', name: 'Oxta'}], space: {space_id: 's'}});
  assert.equal(proven.recentDots[0].execution, proof);
  assert.equal(proven.recentDots[0].status, 'active');
  assert.equal(board.focus.name, 'Oxta');
  assert.equal(board.recordsQuiet, true);
});

test('uncertain records stay one panel of registros and a confirmed failure is not an unconfirmed send', () => {
  const items = Array.from({ length: 32 }, (_, index) => ({
    event_id: 'ev-' + (index + 1), seq: index + 1, kind: 'message.uncertain',
    payload: { status: 'uncertain' },
  }));
  const many = homeBoard({
    dots: [{ dot_id: 'd', name: 'Sentra Aqrt', status: 'active' }],
    spaces: [{ space_id: 's', name: 'Oxta' }], space: { space_id: 's' },
    conversations: [], activity: { items },
  });
  assert.equal(many.recordsQuiet, false);
  assert.equal(many.failures.length, 32);
  assert.equal(many.failureCount, 32);
  assert.equal(many.failurePanels.length, 1);
  const panel = many.failurePanels[0];
  assert.equal(panel.title, 'Envios não confirmados');
  assert.equal(panel.countLabel, '32 registros');
  assert.equal(panel.note, 'Consulte o estado. Não repita o envio.');
  assert.equal(panel.groups.length, 1);
  assert.equal(panel.groups[0].title, 'Mensagens não confirmadas');
  assert.equal(panel.groups[0].items.length, 32);
  assert.equal(panel.groups[0].items[0].label, 'Registro ev-1');
  assert.equal(panel.pageSize, 6);
  const visible = [panel.title, panel.countLabel, panel.note, panel.groups[0].title,
    ...panel.groups[0].items.map(item => item.label)].join('\n');
  assert.equal(visible.includes('message.uncertain'), false);
  assert.equal(visible.includes('Nenhum virou sucesso'), false);
  assert.equal(visible.includes('resultados'), false);

  const distinct = homeBoard({
    conversations: Array.from({ length: 8 }, (_, index) => ({
      conversation_id: 'c' + index, title: 'Conversa ' + index, status: 'active',
    })),
    activity: { items: Array.from({ length: 8 }, (_, index) => ({
      event_id: 'd' + index, seq: index, kind: 'message.uncertain',
      payload: { status: 'uncertain', conversation_id: 'c' + index },
    })) },
  });
  assert.equal(distinct.failurePanels.length, 1);
  assert.equal(distinct.failurePanels[0].groups.length, 8);
  assert.equal(distinct.failurePanels[0].groups.every(group => group.note == null), true);
  assert.equal(distinct.failurePanels[0].countLabel, '8 registros');

  const failed = homeBoard({ activity: { items: [
    { event_id: 'f1', kind: 'operation_failed', payload: { status: 'failed', operation_id: 'op-1' } },
    { event_id: 'f3', kind: 'operation_failed', payload: { status: 'failed' } },
    { event_id: 'f2', kind: 'operation_failed', payload: { status: 'uncertain' } },
  ] } });
  const failedGroups = failed.failurePanels.find(item => item.id === 'failed').groups;
  assert.deepEqual(failedGroups.map(group => group.title), ['Operação op-1', 'Falha']);
  assert.equal(failed.failurePanels.find(item => item.id === 'uncertain').groups[0].title, 'Envio não confirmado');
  assert.equal(failed.failures.length, 3);
  const failedCopy = JSON.stringify(failed.failurePanels);
  assert.equal(failedCopy.includes('Falha não confirmada'), false);
  assert.equal(failedCopy.includes('Nenhum virou sucesso'), false);
});

test('known names group records without treating the count as distinct operations', () => {
  const board = homeBoard({
    dots: [{ dot_id: 'dot-a', name: 'Atlas', status: 'active' }],
    conversations: [{ conversation_id: 'conv-1', title: 'Mapa do rio', status: 'active', dot_id: 'dot-a' }],
    activity: { items: [
      { event_id: 'a', seq: 1, kind: 'message.uncertain', payload: { status: 'uncertain', conversation_id: 'conv-1' } },
      { event_id: 'b', seq: 2, kind: 'message.uncertain', payload: { status: 'uncertain', conversation_id: 'conv-1' } },
      { event_id: 'c', seq: 3, kind: 'message.uncertain', payload: { status: 'uncertain', operation_id: 'op-9' } },
      { event_id: 'd', seq: 4, kind: 'message.uncertain', payload: { status: 'uncertain', dot_id: 'dot-a' } },
    ] },
  });
  const groups = board.failurePanels[0].groups;
  assert.equal(board.failurePanels[0].countLabel, '4 registros');
  assert.deepEqual(groups.map(group => group.title), ['Mapa do rio', 'Operação op-9', 'Atlas']);
  assert.equal(groups[0].count, 2);
  assert.equal(board.failurePanels.every(panel => panel.success === false), true);
});

test('send count stays in one id domain and a failed record is not an unconfirmed send', () => {
  const mixedDomains = [
    { status: 'uncertain', message_id: 'M' },
    { status: 'uncertain', request_key: 'R' },
  ];
  assert.equal(unconfirmedWorkLabel(mixedDomains), '2 registros de envio não confirmado');
  const sameRequest = [
    { status: 'uncertain', message_id: 'M', request_key: 'R' },
    { status: 'uncertain', request_key: 'R' },
  ];
  assert.equal(unconfirmedWorkLabel(sameRequest), '1 envio não confirmado');
  const byMessage = [
    { status: 'uncertain', message_id: 'M', request_key: 'R1' },
    { status: 'uncertain', message_id: 'M', request_key: 'R2' },
  ];
  assert.equal(unconfirmedWorkLabel(byMessage), '1 envio não confirmado');
  const byRequest = [
    { status: 'unconfirmed', request_key: 'R' },
    { status: 'unconfirmed', request_key: 'R' },
    { status: 'unconfirmed', request_key: 'S' },
  ];
  assert.equal(unconfirmedWorkLabel(byRequest), '2 envios não confirmados');
  const fortyFive = Array.from({ length: 45 }, (_, index) => ({
    event_id: 'ev-' + index, status: 'uncertain', kind: 'message.uncertain',
  }));
  assert.equal(unconfirmedWorkLabel(fortyFive), '45 registros de envio não confirmado');
  assert.equal(unconfirmedWorkLabel(fortyFive).includes('envio não confirmado') && unconfirmedWorkLabel(fortyFive).startsWith('45 envio'), false);

  const dot = { dot_id: 'dot-a', name: 'Sentra Aqrt', status: 'active' };
  const conversations = [
    { conversation_id: 'c1', dot_id: 'dot-a', title: 'Conversa com Sentra Aqrt', updated_at: 1791835295 },
    { conversation_id: 'c2', dot_id: 'dot-a', title: 'Conversa com Sentra Aqrt', updated_at: '2026-10-13T12:00:00Z' },
  ];
  assert.equal(dotContextLine(dot, conversations, [
    { status: 'failed', dot_id: 'dot-a', kind: 'operation_failed' },
    { status: 'failed', conversation_id: 'c1', kind: 'message.uncertain' },
  ]), '2 conversas · 13/10/2026');
  assert.equal(dotContextLine(dot, conversations, [
    { status: 'uncertain', dot_id: 'dot-a', kind: 'message.uncertain' },
    { status: 'uncertain', conversation_id: 'c1', kind: 'message.uncertain' },
    { status: 'failed', dot_id: 'dot-a', kind: 'operation_failed' },
  ]), '2 registros de envio não confirmado');
  assert.equal(dotContextLine({ dot_id: 'dot-z', status: 'active' }, [], []), '');
  const board = homeBoard({
    dots: [dot],
    conversations,
    spaces: [{ space_id: 's', name: 'Oxta' }],
    space: { space_id: 's' },
    activity: { items: fortyFive.map(item => ({ ...item, payload: { status: 'uncertain' } })) },
  });
  assert.equal(board.workSupport, '45 registros de envio não confirmado');
  assert.equal(workSupportLine(fortyFive), '45 registros de envio não confirmado');
  assert.equal(workSupportLine(fortyFive).includes(', em '), false);
  const sameMessage = fortyFive.map(item => ({ ...item, message_id: 'M' }));
  assert.equal(workSupportLine(sameMessage), '1 envio não confirmado, em 45 registros');
  assert.equal(workSupportLine(mixedDomains), '2 registros de envio não confirmado');
  assert.equal(workSupportLine(sameRequest), '1 envio não confirmado, em 2 registros');
  const sameBoard = homeBoard({
    dots: [dot],
    conversations,
    spaces: [{ space_id: 's', name: 'Oxta' }],
    space: { space_id: 's' },
    activity: { items: sameMessage.map(item => ({ ...item, payload: { status: 'uncertain', message_id: 'M' } })) },
  });
  assert.equal(sameBoard.workSupport, '1 envio não confirmado, em 45 registros');
  assert.equal(sameBoard.recentDots[0].context, '2 conversas · 13/10/2026');
  const named = groupHomeConversations([
    { conversation_id: 'g1', dot_id: 'dot-a', title: 'testegpt6', updated_at: '2026-10-12T12:00:00Z' },
    { conversation_id: 'g2', dot_id: 'dot-a', title: 'testegpt6', updated_at: '2026-10-12T18:00:00Z' },
  ], [{ dot_id: 'dot-a', name: 'testegpt6' }]);
  assert.equal(named[0].dotLabel, '');
  assert.equal(named[0].detail, '2 conversas · 12/10/2026');
  const titled = groupHomeConversations(
    Array.from({ length: 7 }, (_, index) => ({
      conversation_id: 'aq-' + index, dot_id: 'dot-a', title: 'Conversa com Sentra Aqrt', updated_at: '2026-10-13T12:00:00Z',
    })),
    [dot],
  );
  assert.equal(titled[0].dotLabel, 'Sentra Aqrt');
  assert.equal(titled[0].detail, 'Sentra Aqrt · 7 conversas · 13/10/2026');
  const unnamed = groupHomeConversations([
    { conversation_id: 'u1', dot_id: 'missing', title: 'Sem nome', updated_at: '2026-10-11T00:00:00Z' },
  ], []);
  assert.equal(unnamed[0].dotLabel, '');
  assert.equal(unnamed[0].detail.includes('Dot'), false);
  assert.equal(board.recentDots[0].fact, 'Ativo');
  assert.equal(board.recentDots[0].status, 'active');
  assert.equal(board.recentDots[0].execution, undefined);
  assert.equal(board.recentDots[0].context, '2 conversas · 13/10/2026');
  assert.equal(dotContextLine(dot, [], fortyFive.map(item => ({ ...item, dot_id: 'dot-a' }))), '45 registros de envio não confirmado');
  assert.equal(board.failurePanels[0].countLabel, '45 registros');
  const groups = groupHomeConversations(conversations, [dot]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].count, 2);
  assert.deepEqual(groups[0].items.map(item => item.conversation_id), ['c2', 'c1']);
  assert.equal(groups[0].items[0].dotName, 'Sentra Aqrt');
  assert.equal(groups[0].items[0].whenLabel.includes('13/10/2026'), true);
  assert.equal(groups[0].items[0].whenLabel.includes(':'), true);
  assert.equal(groups[0].latestLabel, '13/10/2026');
});

test('search narrows every column and does not invent a resend', () => {
  const board = homeBoard(home, {query: 'nara'});
  assert.deepEqual(board.recentDots.map(row => row.name), ['Nara']);
  assert.equal(board.projects.length, 0);
  assert.equal(board.approvals.length, 0);
  const missed = homeBoard(home, {query: 'não existe'});
  assert.equal(missed.recentDots.length + missed.projects.length + missed.approvals.length
    + missed.deliveries.length + missed.failures.length, 0);
});
