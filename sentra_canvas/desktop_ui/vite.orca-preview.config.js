import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { mergeConfig } from 'vite';
import base from './vite.config.js';
// Fixtures are available only with this explicit configuration, never in the
// production build or installed application.
export default mergeConfig(base, {
  plugins: [{name:'isolated-orca-preview-api',enforce:'pre',resolveId(source,importer){
    if(importer?.replaceAll('\\','/').includes('/src/')&&/^\.\.?\/api(?:\.js)?$/.test(source))
      return fileURLToPath(new URL('./qa/orca-preview-api.js',import.meta.url));
  },configureServer(server){server.middlewares.use((req,res,next)=>{
    if(req.url!=='/sentra-logo.png')return next();
    res.setHeader('Content-Type','image/png');res.end(readFileSync(new URL('../static/sentra-logo.png',import.meta.url)));
  })},generateBundle(){this.emitFile({type:'asset',fileName:'sentra-logo.png',source:readFileSync(new URL('../static/sentra-logo.png',import.meta.url))})}}],
  build:{outDir:'.tmp/orca-visual-preview',emptyOutDir:true,rolldownOptions:{input:fileURLToPath(new URL('./qa/orca-workspace.html',import.meta.url))}},
});
