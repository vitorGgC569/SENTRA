import { readFile, writeFile, mkdir, rename, unlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { sourceInputs } from './source-inputs.mjs';
const project = resolve(import.meta.dirname, '..');
if (!process.argv[2]) throw new Error('Build input seal required; run npm run build');
const inputSeal = JSON.parse(await readFile(process.argv[2], 'utf8'));
const currentInputs = await sourceInputs(project);
if (JSON.stringify(inputSeal) !== JSON.stringify(currentInputs)) {
  throw new Error('Desktop sources changed during compilation; rebuild before packaging');
}
const assets = resolve(project, '../static/desktop-assets');
await mkdir(assets, { recursive: true });
// OneDrive/Windows can hold a short-lived handle on the previous manifest.
// Stage a complete replacement, then rename with bounded retries. A failed
// swap must never truncate the last valid release manifest.
async function replaceManifest(content) {
  const destination = resolve(assets, 'manifest.json');
  const staging = resolve(assets, '.manifest-' + process.pid + '-' + Date.now() + '.tmp');
  await writeFile(staging, content);
  try {
    for (let attempt = 0; attempt < 5; attempt++) {
      try { await rename(staging, destination); return; }
      catch (error) {
        if (!['EBUSY', 'EPERM', 'EACCES', 'UNKNOWN'].includes(error?.code) || attempt === 4) throw error;
        await new Promise(done => setTimeout(done, 100 * (attempt + 1)));
      }
    }
  } finally {
    await unlink(staging).catch(error => { if (error?.code !== 'ENOENT') throw error; });
  }
}
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
// Git preserves these sealed text assets as LF on every platform. npm legal
// files can contain CRLF even on a Unix build; canonicalize before hashing.
await writeFile(resolve(assets, 'THIRD_PARTY_NOTICES.txt'), licenses.replace(/\r\n/g, '\n'));
const files = {};
const emitted = JSON.parse(await readFile(resolve(assets, '.vite/manifest.json'), 'utf8'));
const outputNames = new Set(['desktop.js', 'desktop.css', 'bootstrap.js', 'THIRD_PARTY_NOTICES.txt', 'index.html']);
for (const item of Object.values(emitted)) {
  for (const name of [item.file, ...(item.css || []), ...(item.assets || [])]) {
    if (name) outputNames.add(name);
  }
}
for (const name of [...outputNames].sort()) {
  if (name.includes('/') || name.includes('\\') || name.startsWith('.')) {
    throw new Error('Non-portable emitted desktop asset: ' + name);
  }
  files[name] = createHash('sha256').update(await readFile(resolve(assets, name))).digest('hex');
}
if (JSON.stringify(inputSeal) !== JSON.stringify(await sourceInputs(project))) {
  throw new Error('Desktop sources changed during materialization; no new manifest written');
}
await replaceManifest(JSON.stringify({
  product: 'SENTRA Desktop', version: pkg.version,
  dependencies: pkg.dependencies, files, source_inputs: currentInputs,
  build_toolchain: { node: process.version, vite: lock.packages['node_modules/vite'].version },
  entry: '/desktop.html',
  styles: '/desktop-assets/desktop.css', script: '/desktop-assets/desktop.js',
  bootstrap: '/desktop-assets/bootstrap.js',
  legacyScripts: ['/workflow-panel.js', '/remote-panel.js', '/machine-panel.js', '/center-panel.js',
    '/vendor/sentra-collab-runtime.js', '/sentra-collab.js', '/collaboration-panel.js'],
}, null, 2) + '\n');
process.stdout.write('Desktop entry and local assets materialized.\n');
