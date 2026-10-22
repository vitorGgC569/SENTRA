import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
import {dirname,resolve,relative} from 'node:path';
import {spawnSync} from 'node:child_process';
import {readFileSync,readdirSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(root,'../..');
const directory=relative(repo,resolve(root,'node_modules/@xterm/addon-serialize')).replaceAll('\\','/');
const patch=resolve(root,'vendor/orca/config/patches/@xterm__addon-serialize@0.15.0-beta.301.patch');
const git=args=>spawnSync('git',['apply','--directory='+directory,...args,'--',patch],{cwd:repo,encoding:'utf8',windowsHide:true});
if(git(['--reverse','--check']).status!==0){
 if(git(['--check']).status!==0)throw Error('Pinned ORCA serializer patch does not match the installed version');
 if(git([]).status!==0)throw Error('Could not apply the pinned ORCA serializer patch');
}
await build({entryPoints:[resolve(root,'src/engine.ts')],outfile:resolve(root,'dist/engine.cjs'),
 bundle:true,platform:'node',format:'cjs',target:'node22',packages:'external',logLevel:'warning',
 plugins:[{name:'sentra-osc-leaf-import',setup(builder){builder.onResolve({filter:/\/agent-detection$/},args=>
  args.importer.endsWith('terminal-osc-cwd-title-scanner.ts')
   ?{path:resolve(root,'vendor/orca/src/shared/osc-title-extraction.ts')}:undefined)}}]});
console.log('Built isolated ORCA terminal snapshot engine.');
const walk=directory=>readdirSync(directory,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?walk(resolve(directory,entry.name)):[resolve(directory,entry.name)]);
const hash=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
const paths=[...walk(resolve(root,'src')),...walk(resolve(root,'vendor')),...walk(resolve(root,'scripts')),
 resolve(root,'package.json'),resolve(root,'package-lock.json'),resolve(root,'provenance.json')];
const sources=Object.fromEntries(paths.sort().map(file=>[relative(root,file).replaceAll('\\','/'),hash(file)]));
const output=hash(resolve(root,'dist/engine.cjs'));
const buildId=createHash('sha256').update(JSON.stringify({sources,output})).digest('hex');
writeFileSync(resolve(root,'dist/manifest.json'),JSON.stringify({version:1,build_id:buildId,sources,output},null,2)+'\n');
