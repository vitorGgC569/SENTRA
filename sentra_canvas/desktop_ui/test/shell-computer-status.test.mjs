import {test} from 'node:test';
import assert from 'node:assert/strict';
import {computerStatus} from '../src/shell-computer-status.js';

const host = {reserved_cpus: 2, max_cpus: 8, reserved_memory_mb: 4096, max_memory_mb: 16384};

test('a live human holds the keyboard and a running VM offers pause, shutdown and handoff', () => {
  const view = computerStatus({
    vm: {vm_state: 'running', last_project_import: {guest_path: '/home/dot/projeto'}},
    input: {live: true, holder: 'human'},
    host,
  });
  assert.equal(view.powerLabel, 'Ligada');
  assert.equal(view.keyboardOwner, 'human');
  assert.equal(view.keyboardLabel, 'Você tem o teclado');
  assert.deepEqual(view.actions, ['pause-or-resume', 'shutdown', 'handoff']);
  assert.ok(view.actionLabels.includes('Desligar'));
  assert.equal(view.importedPath, '/home/dot/projeto');
  assert.equal(view.performance.reservedCpus, 2);
});

test('keyboard ownership requires a live lease', () => {
  assert.equal(computerStatus({vm: {vm_state: 'paused'}, input: {live: false, holder: 'human'}}).keyboardOwner, 'none');
  assert.equal(computerStatus({vm: {vm_state: 'paused'}, input: {live: true, holder: 'agent'}}).keyboardLabel, 'O Dot tem o teclado');
  assert.deepEqual(computerStatus({vm: {vm_state: 'poweroff'}}).actions, ['start']);
  const unknown = computerStatus({});
  assert.equal(unknown.power, 'unknown');
  assert.equal(unknown.powerLabel, 'Estado ainda não confirmado');
  assert.deepEqual(unknown.actions, []);
  assert.notEqual(unknown.hypervisor, 'unavailable');
  assert.equal(computerStatus(null).powerLabel, 'Consultando o computador…');
  assert.equal(computerStatus({vm: {vm_state: 'not_created'}, hypervisor_available: true}).powerLabel, 'Ainda não criada');
  assert.equal(computerStatus({hypervisor_available: false}).hypervisor, 'unavailable');
  assert.equal(computerStatus({hypervisor_available: false}).power, 'unknown');
  assert.notEqual(computerStatus({hypervisor_available: false}).powerLabel, 'Ainda não criada');
  assert.equal(computerStatus(null).copyLabel, '');
  assert.equal(computerStatus(null).performanceLabel, '');
  assert.notEqual(computerStatus(null).hypervisor, 'unavailable');
  assert.equal(computerStatus({}).copyLabel, '');
  assert.equal(computerStatus({}).performanceLabel, 'Desempenho da VM ainda não consultado');
  assert.equal(computerStatus({vm: {vm_state: 'running'}}).copyLabel, 'Nenhum recibo de cópia confirmada');
  assert.equal(computerStatus({
    vm: {vm_state: 'running', last_project_import: {guest_path: '/home/dot/projeto'}},
    host,
  }).copyLabel, '');
  assert.equal(computerStatus({
    vm: {vm_state: 'running', last_project_import: {guest_path: '/home/dot/projeto'}},
    host,
  }).performanceLabel, '');
});
