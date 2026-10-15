import {test} from 'node:test';
import assert from 'node:assert/strict';
import {shouldPollTerminalOutput, terminalReconcileAction} from '../src/shell-terminal-gate.js';

test('terminal output is polled only while the canvas gate is open', () => {
  assert.equal(shouldPollTerminalOutput({
    outputEnabled: false, alive: true, workspace: 'w', activeWorkspace: 'w', hidden: false,
  }), false);
  assert.equal(shouldPollTerminalOutput({
    outputEnabled: true, alive: true, workspace: 'w', activeWorkspace: 'w', hidden: false,
  }), true);
  assert.equal(shouldPollTerminalOutput({
    outputEnabled: true, alive: true, workspace: 'w', activeWorkspace: 'w', hidden: true,
  }), false);
});

test('canvas inactive holds the terminal reconcile and does not apply it', () => {
  assert.equal(terminalReconcileAction(false), 'hold');
  assert.equal(terminalReconcileAction(true), 'apply');
  assert.equal(terminalReconcileAction(undefined), 'hold');
});
