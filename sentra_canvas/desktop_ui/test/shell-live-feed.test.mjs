import {test} from 'node:test';
import assert from 'node:assert/strict';
import {keepLivePreview, presentLive, previewStillVisible, reconcileLivePreview} from '../src/shell-live-feed.js';

test('the feed stays partial and never promotes an exit or a gate', () => {
  const view = presentLive({
    authoritative: true,
    partial: false,
    closes_trio: true,
    status: 'generating',
    activity: 'Coordenando',
    content: 'parcial',
    unit_gate: {passed: true},
    process_exit: 0,
  });
  assert.equal(view.authoritative, false);
  assert.equal(view.partial, true);
  assert.equal(view.closes_trio, false);
  assert.equal(view.promotes, false);
  assert.equal(view.resend, false);
  assert.equal(view.success, false);
  assert.equal(view.activity, 'Coordenando');
  assert.equal(view.content, 'parcial');
  assert.equal(view.unit_gate, undefined);
  assert.equal(view.process_exit, undefined);
});

test('an interrupted draft stays visible and is not a completed answer', () => {
  const preview = {
    status: 'interrupted',
    activity: 'Entrega incerta. Não reenvie.',
    content: 'texto longo preservado',
    persisted: true,
    authoritative: true,
    closes_trio: true,
  };
  const view = presentLive(preview);
  assert.equal(view.status, 'interrupted');
  assert.equal(view.content, 'texto longo preservado');
  assert.equal(view.uncertain, true);
  assert.equal(view.success, false);
  assert.equal(view.resend, false);
  assert.equal(view.authoritative, false);
  assert.equal(keepLivePreview(preview), preview);
  assert.equal(keepLivePreview({status: 'idle', content: 'sumiu'}), null);
  assert.equal(previewStillVisible(preview, [{role: 'assistant', operation_id: undefined}]), true);
  assert.equal(previewStillVisible({...preview, operation_id: 'op-1'}, [
    {role: 'assistant', operation_id: 'op-1', content: 'confirmada'},
  ]), false);
});

test('failed read, empty provider frame and confirmation keep same operation text', () => {
  const first = {operation_id: 'op-a', status: 'generating', activity: 'Recebendo resposta', content: 'texto parcial'};
  const failed = reconcileLivePreview(null, first, {readFailed: true});
  assert.equal(failed.content, first.content);
  assert.equal(failed.activity, 'Reconectando conexão');
  const waiting = reconcileLivePreview({operation_id: 'op-a', status: 'generating', activity: 'Aguardando ChatGPT', content: ''}, failed);
  assert.equal(waiting.content, first.content);
  const confirming = reconcileLivePreview({operation_id: 'op-a', status: 'confirming', activity: 'Confirmando entrega', content: ''}, waiting);
  assert.equal(presentLive(confirming).status, 'confirming');
  assert.equal(confirming.content, first.content);
  const idle = reconcileLivePreview({status: 'idle'}, confirming);
  assert.equal(idle.content, first.content);
  assert.equal(idle.status, 'confirming');
  assert.equal(previewStillVisible(idle, [{role: 'assistant', operation_id: 'op-a'}]), false);
  assert.equal(previewStillVisible(idle, [{role: 'assistant', operation_id: 'op-b'}]), true);
});

test('new generation within the same operation can replace earlier text', () => {
  const previous = {operation_id: 'op-a', status: 'generating', content_revision: 0, content: 'primeira resposta longa'};
  const next = reconcileLivePreview({operation_id: 'op-a', status: 'generating', content_revision: 1, content: 'resumo'}, previous);
  assert.equal(next.content, 'resumo');
  assert.equal(next.content_revision, 1);
});

test('legacy preview without revision does not hide the next nonempty model round', () => {
  const before = {status: 'generating', activity: 'Aguardando ChatGPT', operation_id: 'op', content: 'Resposta antiga mais longa'};
  const after = reconcileLivePreview({status: 'generating', activity: 'Recebendo resposta', operation_id: 'op', content: 'Nova'}, before);
  assert.equal(after.content, 'Nova');
});

test('different operation never borrows a previous operation text', () => {
  const stale = {status: 'generating', operation_id: 'op-old', content: 'segredo anterior'};
  const next = reconcileLivePreview({status: 'generating', operation_id: 'op-new', content: ''}, stale);
  assert.equal(next.content, '');
  assert.equal(next.operation_id, 'op-new');
  assert.equal(reconcileLivePreview(null, {status: 'generating', content: 'sem identidade'}), null);
});

test('shifted Unicode windows retain their own text and immutable reference', () => {
  const previous = {operation_id: 'op-a', status: 'generating', content_revision: 1,
    content: '🦉'.repeat(20), content_offset: 50, truncated: true, content_ref: {reference_id: 'old'}};
  const incoming = {...previous, content: 'novo'.repeat(6), content_offset: 51, content_ref: {reference_id: 'new'}};
  const next = reconcileLivePreview(incoming, previous);
  assert.deepEqual(next, {...incoming, reconnecting: false});
  const revisedReference = {...incoming, content_offset: 50};
  assert.equal(reconcileLivePreview(revisedReference, previous).content, incoming.content);
});

test('status-only frames preserve text together with its matching reference and offset', () => {
  const previous = {operation_id: 'op-a', status: 'generating', content_revision: 1,
    content: 'último trecho 🦉', content_offset: 120000, truncated: true, content_ref: {reference_id: 'saved'}};
  const next = reconcileLivePreview({operation_id: 'op-a', status: 'confirming', activity: 'Confirmando entrega', content: ''}, previous);
  assert.equal(next.content, previous.content);
  assert.equal(next.content_ref, previous.content_ref);
  assert.equal(next.content_offset, previous.content_offset);
  assert.equal(next.truncated, true);
  assert.equal(next.status, 'confirming');
  const unavailable = reconcileLivePreview({operation_id: 'op-a', status: 'preview_unavailable',
    content: '', content_error: 'stream_content_budget_exceeded'}, previous);
  assert.equal(unavailable.content_ref, undefined);
});

test('uncertain delivery stops and a tool dump stays unlabeled', () => {
  const uncertain = presentLive({activity: 'Entrega incerta. Não reenvie.', status: 'idle', content: ''});
  assert.equal(uncertain.uncertain, true);
  assert.equal(uncertain.resend, false);
  assert.equal(uncertain.status, 'idle');
  assert.equal(uncertain.success, false);
  const tool = presentLive({activity: 'unit_gate READY_FOR_PROMOTION C:\\secret grant-1', status: 'idle'});
  assert.equal(tool.activity, 'ferramenta');
  const done = presentLive({activity: 'Confirmando entrega', status: 'idle', content: 'texto'});
  assert.equal(done.closes_trio, false);
  assert.equal(done.promotes, false);
});
