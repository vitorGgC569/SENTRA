'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { spawn } = require('node:child_process');
test('native bar renders, reconnects, routes shortcuts and fits each connected monitor', { timeout: 30000 }, async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'sentra-presence-native-'));
  const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
  const child = spawn(require('electron'), [path.join(__dirname, 'presence-native-runner.cjs'), '--user-data-dir=' + profile],
    { windowsHide: true, env, stdio: 'ignore' });
  const file = path.join(profile, 'presence-result.json');
  try {
    const deadline = Date.now() + 22000;
    while (!fs.existsSync(file) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100));
    assert.ok(fs.existsSync(file), 'native integration result missing');
    const result = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.equal(result.error, undefined, result.error);
    assert.ok(result.monitors.length > 0 && result.monitors.every(row => row.contained));
    for (const name of ['native', 'hideReopen', 'ownerHiddenBarVisible', 'conversationShortcut', 'canvasShortcut',
      'approvalsShortcut', 'reconnectNoDuplicateWindows', 'styled']) assert.equal(result[name], true, name);
    const proof = path.join(__dirname, '../../.tmp/native-presence-delivery/native-integration-result.json');
    fs.writeFileSync(proof, JSON.stringify(result, null, 2));
  } finally {
    child.kill();
    const resolved = path.resolve(profile);
    assert.ok(resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith('sentra-presence-native-'));
    try { fs.rmSync(resolved, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
    catch (error) { if (!['EPERM', 'EBUSY'].includes(error.code)) throw error; }
  }
});
