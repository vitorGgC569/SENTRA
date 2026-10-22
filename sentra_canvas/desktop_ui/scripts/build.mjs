import { spawn } from 'node:child_process';
import { mkdir, writeFile, unlink } from 'node:fs/promises';
import { resolve } from 'node:path';
import { sourceInputs } from './source-inputs.mjs';

const project = resolve(import.meta.dirname, '..');
const inputs = await sourceInputs(project);
const staging = resolve(project, '.tmp', 'build-inputs-' + process.pid + '.json');
await mkdir(resolve(project, '.tmp'), { recursive: true });
await writeFile(staging, JSON.stringify(inputs));
async function run(script, args = []) {
  await new Promise((done, reject) => {
    const child = spawn(process.execPath, [script, ...args], { cwd: project, stdio: 'inherit' });
    child.once('error', reject);
    child.once('exit', (code, signal) => code === 0 ? done() : reject(new Error('Build failed: ' + (signal || code))));
  });
}
try {
  await run(resolve(project, 'scripts/build-island.mjs'));
  await run(resolve(project, 'node_modules/vite/bin/vite.js'), ['build']);
  await run(resolve(project, 'scripts/materialize.mjs'), [staging]);
} finally {
  await unlink(staging);
}
