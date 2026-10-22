import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { sourceInputs } from './source-inputs.mjs';
const project = resolve(import.meta.dirname, '..');
const before = await sourceInputs(project);
await new Promise((done, reject) => {
  const child = spawn(process.execPath, [resolve(project, 'node_modules/vite/bin/vite.js'), 'build', '--config', 'vite.island.config.js'], { cwd: project, stdio: 'inherit' });
  child.once('error', reject);
  child.once('exit', code => code === 0 ? done() : reject(Error('Desktop island build failed')));
});
if (JSON.stringify(before) !== JSON.stringify(await sourceInputs(project))) throw Error('Island sources changed during compilation');
const directory = resolve(project, '../../sentra_electron/island');
const files = {};
for (const name of ['island.html', 'island.js', 'island.css']) files[name] = createHash('sha256').update(await readFile(resolve(directory, name))).digest('hex');
await writeFile(resolve(directory, 'source-manifest.json'), JSON.stringify({ schema: 1, source_inputs: before, files }, null, 2));
