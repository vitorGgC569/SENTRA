import {test} from 'node:test';
import assert from 'node:assert/strict';
import {explainFailure} from '../src/shell-failure.js';

test('every failure explains what happened and refuses a resend', () => {
  const samples = [
    'A operação permanece incerta.',
    {message: 'sem confirmação do recibo', uncertain: true},
    'Esta ação não foi autorizada neste projeto.',
    'Selecione um projeto para continuar.',
    'Failed to fetch',
    'O Canvas recusou o pedido.',
    '',
  ];
  for (const sample of samples) {
    const copy = explainFailure(sample);
    assert.equal(copy.resend, false);
    assert.ok(copy.headline);
    assert.ok(copy.safeNext);
    assert.match(copy.safeNext, /não|Não|Consulte|Selecione|Leia/);
  }
});

test('uncertain, authorization, project and network failures stay distinct', () => {
  assert.equal(explainFailure('estado UNCERTAIN').headline, 'A operação não foi confirmada');
  assert.equal(explainFailure('Grant ausente').headline, 'Sem autorização para esta ação');
  assert.equal(explainFailure('O shell retornou outro projeto.').headline, 'O projeto desta janela não confere');
  assert.equal(explainFailure('ECONNREFUSED').headline, 'A consulta não chegou ao Canvas');
});
