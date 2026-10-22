import {fileURLToPath} from 'node:url';
import {mergeConfig} from 'vite';
import base from './vite.config.js';
export default mergeConfig(base,{base:'./',build:{outDir:'.tmp/workspace-ux-test',emptyOutDir:true,
 rolldownOptions:{input:fileURLToPath(new URL('./test/workspace-ux.html',import.meta.url))}}});
