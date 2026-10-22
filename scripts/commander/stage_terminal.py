"""Stage the read-only terminal mirror and its pinned xterm dependencies."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[2]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def inventory(root):
 result={}
 for path in sorted(Path(root).rglob('*')):
  if path.is_symlink():raise ValueError('Linked terminal runtime file')
  if path.is_file() and path.name!='runtime.json':result[path.relative_to(root).as_posix()]=sha(path)
 if len(result)>512:raise ValueError('Terminal runtime inventory exceeded')
 return result

def validate_terminal_runtime(root):
 root=Path(root).resolve();p=root/'runtime.json'
 if p.is_symlink() or p.stat().st_size>256000:raise ValueError('Invalid terminal runtime manifest')
 manifest=json.loads(p.read_text(encoding='utf-8'))
 if manifest.get('schema')!=1 or manifest.get('files')!=inventory(root):raise ValueError('Terminal runtime integrity failure')
 for name in ('src/worker.mjs','dist/engine.cjs','dist/manifest.json',
              'vendor/orca/LICENSE','node_modules/@xterm/headless/lib-headless/xterm-headless.js'):
  if name not in manifest['files']:raise ValueError('Incomplete terminal runtime: '+name)
 return manifest

def stage_terminal_runtime(destination):
 destination=Path(destination).resolve();source=ROOT/'integrations/orca-terminal'
 if destination==ROOT or destination.is_relative_to(ROOT/'integrations'):raise ValueError('Choose a packaging directory')
 seal=json.loads((source/'dist/manifest.json').read_text(encoding='utf-8'))
 if seal.get('version')!=1 or sha(source/'dist/engine.cjs')!=seal.get('output'):raise ValueError('Terminal engine build unavailable')
 for name,digest in seal['sources'].items():
  file=(source/name).resolve()
  if not file.is_relative_to(source.resolve()) or sha(file)!=digest:raise ValueError('Terminal engine source seal stale')
  target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
 for folder in ('dist','node_modules/@xterm'):
  shutil.copytree(source/folder,destination/folder,dirs_exist_ok=True)
 record={'schema':1,'read_only':True,'engine_build_id':seal['build_id'],'files':inventory(destination)}
 (destination/'runtime.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
 return validate_terminal_runtime(destination)
