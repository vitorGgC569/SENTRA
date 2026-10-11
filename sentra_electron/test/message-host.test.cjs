'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { execFile } = require('node:child_process');

test('candidate Browser Host private challenge/snapshot uses actual isolated Electron WebContents', {
  timeout: 30000, skip: !process.env.SENTRA_BROWSER_QA_TREE && 'Set SENTRA_BROWSER_QA_TREE to candidate source',
}, async () => {
  const electron = require('electron');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'sentra-message-host-electron-'));
  const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
  try {
    const stdout = await new Promise((resolve, reject) => execFile(electron,
      [path.join(__dirname, 'message-host-runner.cjs'), '--user-data-dir=' + profile],
      { windowsHide: true, timeout: 25000, env },
      (error, stdout, stderr) => error ? reject(Error(String(error) + '\n' + stderr + '\n' + stdout)) : resolve(stdout)));
    assert.match(stdout, /SENTRA_MESSAGE_HOST_ELECTRON_OK/);
  } finally {
    const resolved = path.resolve(profile);
    assert.ok(resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith('sentra-message-host-electron-'));
    fs.rmSync(resolved, { recursive: true, force: true });
  }
});
