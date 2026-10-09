import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
const project = resolve(import.meta.dirname, '..');
const assets = resolve(project, '../static/desktop-assets');
await mkdir(assets, { recursive: true });
await writeFile(resolve(project, '../static/desktop.html'), await readFile(resolve(assets, 'index.html')));
const pkg = JSON.parse(await readFile(resolve(project, 'package.json'), 'utf8'));
const lock = JSON.parse(await readFile(resolve(project, 'package-lock.json'), 'utf8'));
let licenses = 'SENTRA Desktop third-party runtime notices\n\n';
for (const [name, info] of Object.entries(lock.packages)) {
  if (!name || info.dev) continue;
  const dir = resolve(project, name);
  for (const file of ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'License']) {
    try {
      const text = await readFile(resolve(dir, file), 'utf8');
      licenses += '\n--- ' + name.replace('node_modules/', '') + ' ' + info.version + ' ---\n' + text + '\n';
      break;
    } catch (e) { if (e.code !== 'ENOENT') throw e; }
  }
}
await writeFile(resolve(assets, 'THIRD_PARTY_NOTICES.txt'), licenses);
const files = {};
for (const name of ['desktop.js', 'desktop.css', 'bootstrap.js']) {
  files[name] = createHash('sha256').update(await readFile(resolve(assets, name))).digest('hex');
}
await writeFile(resolve(assets, 'manifest.json'), JSON.stringify({
  product: 'SENTRA Desktop', version: pkg.version,
  dependencies: pkg.dependencies, files,
  entry: '/desktop.html',
  styles: '/desktop-assets/desktop.css', script: '/desktop-assets/desktop.js',
  bootstrap: '/desktop-assets/bootstrap.js',
  legacyScripts: ['/workflow-panel.js', '/remote-panel.js', '/machine-panel.js', '/center-panel.js',
    '/vendor/sentra-collab-runtime.js', '/sentra-collab.js', '/collaboration-panel.js'],
}, null, 2) + '\n');
process.stdout.write('Desktop entry and local assets materialized.\n');
