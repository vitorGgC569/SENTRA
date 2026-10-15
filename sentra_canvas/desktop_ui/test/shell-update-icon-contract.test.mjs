import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../src/shell-app.jsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/desktop.css', import.meta.url), 'utf8');

test('local update occupies one icon, never a pushing banner or text badge', () => {
  assert.equal((source.match(/id="shell-update-all"/g) || []).length, 1);
  assert.match(source, /onClick=\{applyDetectedUpdate\}/);
  assert.match(source, /className=\{'shell-icon shell-update-trigger'/);
  assert.doesNotMatch(source, /shell-update-banner|shell-update-available|showUpdateBanner|dismissUpdateBanner/);
  assert.doesNotMatch(source, />Atualização disponível<|>Atualizar agora</);
  assert.match(css, /\.shell-update-trigger\.is-updating svg\s*\{[^}]*animation:/);
});

test('icon click has no native confirm; the owner retains admission checks and failure notice', () => {
  assert.doesNotMatch(source, /window\.confirm\(['"](?:Há alterações no código|Atualizar o código e os serviços)/);
  assert.match(source, /const status = await native\.check_full_updates\(\)/);
  assert.match(source, /if \(!status\.safe\)/);
  assert.match(source, /const applied = await native\.apply_full_updates\(\)/);
  assert.match(source, /aria-busy=\{updatingCode\}/);
  assert.match(source, /waitForUpdateNavigation\(\)/);
  for (const [start, end] of [['async function refreshCode()', 'async function refreshAll()'], ['async function refreshAll()', 'function showInstalledVersion()']]) {
    const path = source.slice(source.indexOf(start), source.indexOf(end));
    assert.match(path, /finally\s*\{\s*if \(!navigationIssued\) finishUpdateAttempt\(\);\s*\}/);
  }
  assert.match(css, /\.shell-update-feedback\s*\{[^}]*position:fixed/);
});

test('update cleanup disarms its deadline but never unlocks an uncertain attempt', () => {
  const body = source.match(/function finishUpdateAttempt\(\)\s*\{([\s\S]*?)\n  \}/)?.[1];
  assert.ok(body, 'The finalizer must remain available to both update paths');
  for (const uncertain of [false, true]) {
    const events = [];
    const updateInFlight = { current: true };
    const finish = new Function('updateDeadline', 'updateUncertain', 'endCanvasMaintenance', 'updateInFlight', 'setUpdatingCode', body);
    finish({ current: { disarm: () => events.push('disarm') } }, { current: uncertain },
      () => events.push('endMaintenance'), updateInFlight, value => events.push(['updating', value]));
    assert.deepEqual(events, uncertain ? ['disarm'] : ['disarm', 'endMaintenance', ['updating', false]]);
    assert.equal(updateInFlight.current, uncertain);
  }
});
