import {fileURLToPath} from 'node:url';
import {mergeConfig} from 'vite';
import preview from './vite.orca-preview.config.js';
export default mergeConfig(preview,{base:'./',build:{outDir:'.tmp/shell-flow-test',emptyOutDir:true,rolldownOptions:{input:fileURLToPath(new URL('./test/shell-flow.html',import.meta.url))}}});
