import { readFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, relative } from 'node:path';

export async function sourceInputs(project) {
  const names = ['package.json', 'package-lock.json', 'index.html', 'vite.config.js',
    'scripts/build.mjs', 'scripts/materialize.mjs', 'scripts/source-inputs.mjs'];
  async function walk(directory) {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, item.name);
      if (item.isSymbolicLink()) throw new Error('Linked desktop build input: ' + path);
      if (item.isDirectory()) await walk(path);
      else if (item.isFile()) names.push(relative(project, path).replaceAll('\\', '/'));
    }
  }
  await walk(resolve(project, 'src'));
  try { await walk(resolve(project, 'public')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const hashes = {};
  for (const name of names.sort()) {
    hashes[name] = createHash('sha256').update(await readFile(resolve(project, name))).digest('hex');
  }
  return hashes;
}
