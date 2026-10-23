import { readFile, readdir, lstat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, relative, dirname } from 'node:path';

export async function sourceInputs(project) {
  const names = ['package.json', 'package-lock.json', 'index.html', 'vite.config.js',
    'scripts/build.mjs', 'scripts/build-island.mjs', 'scripts/materialize.mjs', 'scripts/source-inputs.mjs',
    'island.html', 'vite.island.config.js'];
  async function walk(directory) {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, item.name);
      if (item.isSymbolicLink()) throw new Error('Linked desktop build input: ' + path);
      if (item.isDirectory()) await walk(path);
      else if (item.isFile()) names.push(relative(project, path).replaceAll('\\', '/'));
    }
  }
  await walk(resolve(project, 'src'));
  // Imported source outside desktop_ui must also invalidate a packaged bundle.
  for(const name of ['consumer-flow.mjs','input-queue.mjs','emulator-budget.mjs','saved-register.mjs']
    .map(name=>'../../integrations/orca-terminal/src/'+name)
    .concat('../../integrations/orca-terminal/vendor/orca/src/shared/terminal-unicode-provider.ts')){
    try{
      const info=await lstat(resolve(project,name));if(info.isSymbolicLink()||!info.isFile())throw Error('Linked desktop build input: '+name);
      for(let parent=dirname(resolve(project,name)),root=resolve(project,'../..');parent!==root;parent=dirname(parent)){
        if((await lstat(parent)).isSymbolicLink())throw Error('Linked desktop shared build input: '+name);
      }
      names.push(name);
    }catch(error){if(error.code!=='ENOENT')throw error;}
  }
  try { await walk(resolve(project, 'public')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const hashes = {};
  for (const name of names.sort()) {
    const bytes = await readFile(resolve(project, name));
    // These source extensions have LF checkout attributes. Sealing CRLF here
    // produces an artifact which fails its exact-byte proof after Git checkout.
    if (/\.(?:js|jsx|mjs|cjs|ts|tsx|css|html|json)$/.test(name) && bytes.includes('\r\n')) {
      throw new Error('Noncanonical CRLF desktop source; normalize to LF before building: ' + name);
    }
    hashes[name] = createHash('sha256').update(bytes).digest('hex');
  }
  return hashes;
}
