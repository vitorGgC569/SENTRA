import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
import {dirname,resolve} from 'node:path';
const here=dirname(fileURLToPath(import.meta.url));
await build({entryPoints:[resolve(here,'browser_entry.mjs')],bundle:true,platform:'browser',
  format:'iife',target:['es2022'],minify:true,legalComments:'eof',
  outfile:resolve(here,'../sentra_canvas/static/vendor/sentra-collab-runtime.js')});
