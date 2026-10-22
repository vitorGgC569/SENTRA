"""Stage an independent, manifest-checked mobile gateway (no npm at runtime)."""
from pathlib import Path
import hashlib,json,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[2]
FILES=('node.exe','gateway.mjs','LICENSE','THIRD_PARTY_NOTICES.txt','runtime.json')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def validate_mobile_runtime(root):
 root=Path(root).resolve();manifest=root/'runtime.json'
 if manifest.is_symlink() or manifest.stat().st_size>256000:raise ValueError('Invalid mobile runtime manifest')
 if set(p.name for p in root.iterdir())!=set(FILES):raise ValueError('Unexpected mobile runtime contents')
 m=json.loads(manifest.read_text(encoding='utf-8'))
 if m.get('schema')!=1 or m.get('protocol_version')!=1 or set(m.get('files',{}))!=set(FILES)-{'runtime.json'}:raise ValueError('Mobile runtime manifest incompatible')
 for name,digest in m['files'].items():
  p=root/name
  if p.is_symlink() or not p.is_file() or sha(p)!=digest:raise ValueError('Mobile runtime integrity failure: '+name)
 if not re.fullmatch(r'v24\.\d+\.\d+',m.get('node_version','')):raise ValueError('Pinned Node 24 runtime required')
 return m

def stage_mobile_runtime(destination,node):
 destination=Path(destination).resolve();node=Path(node).resolve(strict=True)
 if destination==ROOT or destination.is_relative_to(ROOT/'integrations'):raise ValueError('Choose a packaging output directory')
 version=subprocess.check_output([str(node),'--version'],text=True).strip()
 if not re.fullmatch(r'v24\.\d+\.\d+',version) or node.name.lower()!='node.exe':raise ValueError('Explicit Windows Node 24 executable required')
 license=node.parent/'LICENSE'
 if not license.is_file():raise FileNotFoundError('Node third-party license missing')
 destination.mkdir(parents=True,exist_ok=True)
 esbuild=ROOT/'integrations/orca-terminal/node_modules/esbuild/bin/esbuild'
 source=ROOT/'integrations/orca-mobile/transport/src/gateway.ts'
 subprocess.run([str(node),str(esbuild),str(source),'--bundle','--platform=node','--format=esm','--target=node24','--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);','--outfile='+str(destination/'gateway.mjs')],check=True,capture_output=True)
 shutil.copy2(node,destination/'node.exe');shutil.copy2(license,destination/'LICENSE')
 notices=['SENTRA Mobile direct gateway\n\nBundled dependency notices; Node notices are in LICENSE.\n']
 for name,source_license in (
     ('ORCA (Lovecast Inc., pinned adaptation)',ROOT/'vendor/orca/LICENSE'),
     ('ws',ROOT/'integrations/orca-mobile/transport/node_modules/ws/LICENSE'),
     ('TweetNaCl',ROOT/'integrations/orca-mobile/transport/node_modules/tweetnacl/LICENSE'),
     ('@noble/hashes',ROOT/'integrations/orca-mobile/transport/node_modules/@noble/hashes/LICENSE'),
     *((name,ROOT/'integrations/orca-mobile/transport/node_modules'/name/'LICENSE') for name in
       ('multicast-dns','dns-packet','thunky','@leichtgewicht/ip-codec'))):
  notices.append('\n=== '+name+' ===\n'+source_license.read_text(encoding='utf-8'))
 (destination/'THIRD_PARTY_NOTICES.txt').write_text('\n'.join(notices),encoding='utf-8')
 source_inputs={p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'integrations/orca-mobile/transport/src').rglob('*')) if p.is_file()}
 for name in ('package.json','package-lock.json'):
  dependency=ROOT/'integrations/orca-mobile/transport'/name;source_inputs[dependency.relative_to(ROOT).as_posix()]=sha(dependency)
 manifest={'schema':1,'protocol_version':1,'node_version':version,'files':{name:sha(destination/name) for name in FILES if name!='runtime.json'},'source_inputs':source_inputs,'authority':'existing scoped SENTRA mobile gateway'}
 (destination/'runtime.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
 return validate_mobile_runtime(destination)
