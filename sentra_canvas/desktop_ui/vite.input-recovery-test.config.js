import {fileURLToPath} from 'node:url';
import {mergeConfig} from 'vite';
import base from './vite.config.js';
export default mergeConfig(base,{base:'./',build:{outDir:'.tmp/input-recovery-test',emptyOutDir:true,
 rolldownOptions:{input:fileURLToPath(new URL('./test/input-recovery.html',import.meta.url))}}});
