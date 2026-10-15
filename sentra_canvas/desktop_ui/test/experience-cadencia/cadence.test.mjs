import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MOTION, SurfaceMotion, transitionUsesOnlyTransformAndOpacity, feedMotion, workMotion, homeFrame, HOME_LOADING, watchReducedMotion, setChevron } from '../../src/experience/cadencia/index.js';

const css = readFileSync(new URL('../../src/experience/cadencia/cadence.css', import.meta.url), 'utf8');

test('MOTION is 200ms without bounce', () => {
  assert.equal(MOTION.ms, 200);
  assert.ok(MOTION.ms >= 180 && MOTION.ms <= 240);
  assert.equal(MOTION.ease, 'cubic-bezier(0.22, 1, 0.36, 1)');
  const points = MOTION.ease.match(/[\d.]+/g).map(Number);
  assert.ok(points.every(point => point >= 0 && point <= 1));
});

test('SurfaceMotion keeps the home row at max-content and drops motion when reduced', () => {
  const moving = SurfaceMotion({ from: 'home', to: 'conversations' });
  const still = SurfaceMotion({ reduced: true, from: 'home', to: 'canvas' });
  assert.equal(moving.ms, 200);
  assert.equal(moving.ease, MOTION.ease);
  assert.equal(moving.dir, 'forward');
  assert.equal(moving.list.height, 'max-content');
  assert.equal(moving.list.gridAutoRows, 'max-content');
  assert.equal(moving.list.alignContent, 'start');
  assert.equal(moving.row.height, 'max-content');
  assert.equal(moving.row.alignSelf, 'start');
  assert.equal(moving.row.flexGrow, 0);
  assert.equal(transitionUsesOnlyTransformAndOpacity(moving.transition), true);
  assert.match(moving.transition, /200ms/);
  assert.equal(moving.animation.includes('bounce'), false);
  assert.equal(still.transition, 'none');
  assert.equal(still.animation, 'none');
  assert.equal(still.list.height, 'max-content');
});

test('cadence.css stops the home list from stretching and honors reduced motion', () => {
  assert.match(css, /\.shell-home-list \{[^}]*height: max-content;/s);
  assert.match(css, /grid-auto-rows: max-content/);
  assert.match(css, /align-content: start/);
  assert.match(css, /\.shell-home-list > button \{[^}]*height: max-content;/s);
  assert.match(css, /align-self: start/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /animation: none !important/);
  assert.match(css, /200ms cubic-bezier\(0\.22, 1, 0\.36, 1\)/);
  assert.match(css, /cadence-enter-forward/);
  assert.match(css, /translateX\(18px\)/);
  assert.match(css, /translateX\(-18px\)/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /data-reduced="true"/);
  assert.match(css, /max-height: 56px/);
  assert.equal(/bounce|@keyframes[^}]*width|@keyframes[^}]*height|@keyframes[^}]*top|@keyframes[^}]*left/s.test(css), false);
});

test('Coordenando starts once, before the text', () => {
  const first = feedMotion({ status: 'generating', activity: 'Coordenando', content: '', partial: true });
  const again = feedMotion({ status: 'generating', activity: 'Coordenando', content: '' }, first);
  assert.equal(first.phase, 'planning');
  assert.equal(first.animate, true);
  assert.equal(first.fragment, '');
  assert.equal(first.content, '');
  assert.equal(again.animate, false);
  assert.equal(first.authoritative, false);
  assert.equal(first.closes_trio, false);
  assert.equal(first.finalAnswer, false);
  assert.equal(first.resend, false);
});

test('each text delta is appended once and partial text is not Flint final', () => {
  const opened = feedMotion({ status: 'generating', activity: 'Recebendo resposta', content: 'Olá' });
  const grown = feedMotion({ status: 'generating', activity: 'Recebendo resposta', content: 'Olá, Dot' }, opened);
  const same = feedMotion({ status: 'generating', activity: 'Recebendo resposta', content: 'Olá, Dot' }, grown);
  assert.equal(opened.fragment, 'Olá');
  assert.equal(grown.fragment, ', Dot');
  assert.equal(same.fragment, '');
  assert.equal(same.animate, false);
  assert.equal(grown.finalAnswer, false);
  assert.equal(grown.partial, true);
  assert.equal(grown.success, false);
});

test('uncertain delivery stops on the canvas phase and does not resend', () => {
  const view = {
    status: 'generating', activity: 'Entrega incerta. Não reenvie.', content: 'parcial',
    authoritative: true, closes_trio: true, process_exit: 0, unit_gate: true,
  };
  const beat = feedMotion(view);
  const repeat = feedMotion(view, beat);
  const copy = workMotion({ taskStatus: 'uncertain' });
  assert.equal(beat.phase, 'uncertain');
  assert.equal(beat.phase, copy.phase);
  assert.equal(beat.stop, true);
  assert.equal(beat.animate, false);
  assert.equal(repeat.animate, false);
  assert.equal(beat.resend, false);
  assert.equal(copy.resend, false);
  assert.equal(beat.authoritative, false);
  assert.equal(beat.closes_trio, false);
  assert.equal(beat.success, false);
  assert.equal(beat.finalAnswer, false);
  assert.match(copy.safeNext, /Não reenvie/);
});

test('confirming delivery and exit code do not close the trio', () => {
  const beat = feedMotion({
    status: 'generating', activity: 'Confirmando entrega', content: 'texto',
    process_exit: 0, unit_gate: true, authoritative: true, closes_trio: true,
  });
  assert.equal(beat.phase, 'waiting');
  assert.equal(beat.success, false);
  assert.equal(beat.closes_trio, false);
  assert.equal(beat.authoritative, false);
  assert.equal(beat.finalAnswer, false);
});

test('an interrupted long draft keeps its text and does not resend', () => {
  const beat = feedMotion({
    status: 'interrupted',
    activity: 'Entrega incerta. Não reenvie.',
    content: 'item 001 ' + 'acessibilidade '.repeat(40),
    authoritative: true,
    closes_trio: true,
  });
  assert.equal(beat.phase, 'uncertain');
  assert.equal(beat.stop, true);
  assert.equal(beat.resend, false);
  assert.equal(beat.success, false);
  assert.equal(beat.finalAnswer, false);
  assert.equal(beat.authoritative, false);
  assert.match(beat.content, /item 001/);
  assert.notEqual(beat.phase, 'idle');
  assert.notEqual(beat.activity, 'Aguardando modelo');
});

test('presentation preserves server-projected bracket prose in every visible phase', () => {
  const content = 'ha haha [[wiki]] [[ação🦉]] [[Canvas]] texto literal [';
  for (const status of ['generating', 'confirming', 'interrupted', 'preview_unavailable']) {
    const beat = feedMotion({status, activity:'Recebendo resposta', content});
    assert.equal(beat.content, content);
    assert.equal(beat.authoritative, false);
    assert.equal(beat.success, false);
  }
});

test('idle is not success and a provider wait retains received prose', () => {
  const idle = feedMotion({ status: 'idle' });
  const waiting = feedMotion({ status: 'generating', activity: 'Aguardando ChatGPT', content: 'ferramenta anterior' });
  assert.equal(idle.success, false);
  assert.equal(idle.phase, 'idle');
  assert.notEqual(idle.phase, 'planning');
  assert.equal(idle.animate, false);
  assert.equal(idle.partial, false);
  assert.equal(waiting.phase, 'waiting');
  assert.equal(waiting.content, 'ferramenta anterior');
  assert.equal(waiting.authoritative, false);
});

test('confirmation and reconnection preserve text without confirming or resending', () => {
  const partial = feedMotion({ status: 'generating', activity: 'Recebendo resposta', content: 'Olá' });
  const confirmation = feedMotion({ status: 'confirming', activity: 'Confirmando entrega', content: 'Olá' }, partial);
  const reconnect = feedMotion({ status: 'generating', activity: 'Reconectando conexão', content: 'Olá' }, confirmation);
  const unavailable = feedMotion({ status: 'preview_unavailable', content: 'Olá' }, reconnect);
  assert.equal(confirmation.phase, 'waiting');
  assert.equal(reconnect.phase, 'waiting');
  assert.equal(unavailable.content, 'Olá');
  for (const beat of [confirmation, reconnect, unavailable]) {
    assert.equal(beat.content, 'Olá');
    assert.equal(beat.resend, false);
    assert.equal(beat.success, false);
    assert.equal(beat.authoritative, false);
  }
});

test('cumulative snapshot keeps a repeated character, ha to haha', () => {
  const first = feedMotion({ status: 'generating', activity: 'Recebendo resposta', content: 'ha' });
  const second = feedMotion({ status: 'generating', activity: 'Recebendo resposta', content: 'haha' }, first);
  assert.equal(first.fragment, 'ha');
  assert.equal(second.fragment, 'ha');
  assert.equal(second.content, 'haha');
  assert.equal(second.animate, true);
  assert.equal(second.finalAnswer, false);
});

test('standby, unavailable and whitespace follow the live view', () => {
  const waiting = feedMotion({ status: 'generating', content: '' });
  const coordinating = feedMotion({ status: 'generating', activity: 'Coordenando', content: '  ' }, waiting);
  const unavailable = feedMotion({ status: 'preview_unavailable', activity: 'Coordenando', content: 'ha' });
  const tool = feedMotion({ status: 'generating', activity: 'Executando ferramenta read_file', content: '' });
  const fake = feedMotion({ status: 'generating', activity: 'ferramenta', content: '' });
  assert.equal(waiting.activity, 'Aguardando modelo');
  assert.equal(waiting.phase, 'standby');
  assert.notEqual(waiting.phase, 'planning');
  assert.equal(coordinating.activity, 'Coordenando');
  assert.equal(coordinating.fragment, '  ');
  assert.equal(coordinating.animate, false);
  assert.equal(unavailable.phase, 'preview_unavailable');
  assert.notEqual(unavailable.phase, 'idle');
  assert.notEqual(unavailable.phase, 'planning');
  assert.equal(unavailable.animate, false);
  assert.equal(tool.kind, 'tool');
  assert.equal(tool.phase, 'executing');
  assert.equal(fake.kind, 'other');
  assert.notEqual(fake.phase, 'executing');
});

test('home read stays on the consulting line until it settles', () => {
  const loading = homeFrame({ loading: true, settled: false, empty: true, readError: 'falhou' });
  const failed = homeFrame({ loading: false, settled: false, empty: true, readError: 'não confirmado' });
  const ready = homeFrame({ loading: false, settled: true, empty: false });
  const vacant = homeFrame({ loading: false, settled: true, empty: true });
  assert.equal(loading.show, 'loading');
  assert.equal(loading.text, HOME_LOADING);
  assert.equal(loading.showEmpty, false);
  assert.equal(loading.showBoard, false);
  assert.equal(failed.show, 'read-error');
  assert.equal(failed.showEmpty, false);
  assert.equal(failed.mutation, false);
  assert.equal(failed.headline.includes('não foi confirmada'), false);
  assert.equal(failed.safeNext.includes('não esvazia'), true);
  assert.equal(ready.showBoard, true);
  assert.equal(ready.showEmpty, false);
  assert.equal(vacant.showEmpty, true);
});

test('collapsed set chevron sits 16px after the count and does not travel on Y', () => {
  const closed = setChevron({ open: false });
  const opened = setChevron({ open: true });
  const still = setChevron({ open: true, reduced: true });
  assert.equal(closed.offset, 16);
  assert.equal(closed.size, 16);
  assert.equal(closed.transform, 'rotate(0deg)');
  assert.equal(opened.transform, 'rotate(90deg)');
  assert.equal(opened.transition, 'transform 200ms cubic-bezier(0.22, 1, 0.36, 1)');
  assert.equal(opened.transform.includes('translateY'), false);
  assert.equal(opened.transition.includes('translateY'), false);
  assert.equal(still.transition, 'none');
  assert.equal(still.transform, 'rotate(90deg)');
  const rule = css.slice(css.indexOf('.cadence-set-chevron'));
  assert.match(css, /column-gap: 16px/);
  assert.match(rule, /width: 16px/);
  assert.match(rule, /rotate\(90deg\)/);
  assert.equal(rule.includes('translateY'), false);
});

test('reduced-motion listener emits and then removes itself', () => {
  const listeners = [];
  const query = {
    matches: false,
    addEventListener(_type, fn) { listeners.push(fn); },
    removeEventListener(_type, fn) {
      const index = listeners.indexOf(fn);
      if (index >= 0) listeners.splice(index, 1);
    },
  };
  const seen = [];
  const stop = watchReducedMotion(value => seen.push(value), () => query);
  assert.deepEqual(seen, [false]);
  query.matches = true;
  listeners[0]();
  assert.deepEqual(seen, [false, true]);
  stop();
  assert.equal(listeners.length, 0);
});
