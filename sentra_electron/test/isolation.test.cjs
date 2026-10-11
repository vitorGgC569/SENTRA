'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const http = require('node:http'), crypto = require('node:crypto');
const { execFile } = require('node:child_process');
test('production Electron display has isolated sandbox and denies popup windows', { timeout: 30000 }, async () => {
  const electron = require('electron');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'sentra-electron-isolation-'));
  const ticket = crypto.randomBytes(16).toString('hex');
  const file = path.join(os.tmpdir(), 'sentra-electron-' + ticket + '.json');
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html', 'Cache-Control': 'no-store' });
    response.end('<!doctype html><title>SENTRA isolated Canvas fixture</title><p>Local QA only</p>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const environment = { ...process.env };
  delete environment.ELECTRON_RUN_AS_NODE;
  try {
    fs.writeFileSync(file, JSON.stringify({ schema: 1, port: server.address().port,
      secret: 'qa-local-fixture-'.repeat(4), expires_at: Date.now() + 29000 }));
    const stdout = await new Promise((resolve, reject) => execFile(electron,
      [path.join(__dirname, 'isolation-runner.cjs'), '--user-data-dir=' + profile, '--sentra-ticket=' + ticket],
      { windowsHide: true, timeout: 25000, env: environment },
      (error, stdout, stderr) => error ? reject(Error(String(error) + '\n' + stderr)) : resolve(stdout)));
    assert.match(stdout, /SENTRA_ELECTRON_ISOLATION_OK/);
    assert.equal(fs.existsSync(file), false, 'production bootstrap consumes its ticket');
  } finally {
    server.close();
    if (fs.existsSync(file)) fs.unlinkSync(file);
    const resolved = path.resolve(profile);
    assert.ok(resolved.startsWith(path.resolve(os.tmpdir()) + path.sep) && path.basename(resolved).startsWith('sentra-electron-isolation-'));
    fs.rmSync(resolved, { recursive: true, force: true });
  }
});
