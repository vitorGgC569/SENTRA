import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const canvas = await readFile(new URL('../src/shell-dot-canvas.jsx', import.meta.url), 'utf8');
const computer = await readFile(new URL('../src/shell-dot-computer.jsx', import.meta.url), 'utf8');
const vm = await readFile(new URL('../src/shell-dot-vm.jsx', import.meta.url), 'utf8');
const family = await readFile(new URL('../src/shell-dot-family.jsx', import.meta.url), 'utf8');
const css = await readFile(new URL('../src/desktop.css', import.meta.url), 'utf8');
const polish = await readFile(new URL('../src/shell-polish.css', import.meta.url), 'utf8');

test('the canvas stage is the graph and phase detail stays inside the terminal', () => {
  const stage = canvas.indexOf('className="shell-agent-stage"');
  const phase = canvas.indexOf('className="shell-phase-row"');
  const section = canvas.indexOf('className="shell-dot-canvas shell-studio"');
  const flow = canvas.indexOf('className="shell-dot-flow"');
  assert.ok(stage > 0 && phase > stage);
  assert.ok(section > 0 && flow > section);
  assert.match(canvas, /Tarefas e atividade <span>\{recent\.length \+ toolReceipts\.length \|\| ''\}<\/span>/);
  assert.match(canvas, /<Status value=\{selected\.status\} \/>/);
  assert.doesNotMatch(canvas, /receipt\.work_item_state\} \/ \{receipt\.operation_state\}/);
  assert.match(canvas, /execution=\{member\.execution\}/);
  assert.match(css, /\.shell-dot-flow \{[^}]*overflow:\s*hidden/);
  assert.match(polish, /\.opendots-shell \.shell-dot-flow \{[^}]*min-height:\s*240px/);
});

test('the computer panel leads with identity, then the views, and keeps family closed', () => {
  const identity = computer.indexOf('dot-computer-identity');
  const strip = computer.indexOf('<ComputerStatusStrip');
  const tabs = computer.indexOf('dot-computer-tabs');
  const fold = computer.indexOf('shell-dot-family-fold');
  assert.ok(identity > 0 && identity < tabs && tabs < strip && strip < fold);
  assert.match(computer, /<details className="dot-computer-details"><summary>Detalhes do computador<\/summary><ComputerStatusStrip status=\{machine\} \/>/);
  assert.match(computer, /<details className="shell-dot-family-fold">/);
  assert.doesNotMatch(computer, /<details className="shell-dot-family-fold" open>/);
  assert.match(computer, /<DotFamilyControls /);
  assert.match(family, /onClick=\{\(\) => void send\('dot_pause_family'\)\}/);
  assert.match(family, /onClick=\{\(\) => void send\('dot_resume_family'\)\}/);
  assert.match(family, /onClick=\{\(\) => void send\('dot_delete_request'\)\}/);
  assert.doesNotMatch(vm, /setSettings\(!value\.vm\.iso_path\)/);
  assert.doesNotMatch(vm, /hypervisor_available === false && !vm\?\.vm_state \? 'VirtualBox indisponível'/);
  assert.match(vm, /O limite recomendado não altera CPU, RAM nem a VM registrada\./);
  assert.match(vm, /settings && <form className="dot-vm-form"/);
});
