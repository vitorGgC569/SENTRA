"""Build the public site from source and verified release metadata only."""
from pathlib import Path
import argparse,datetime,json,re,shutil,urllib.request
ROOT=Path(__file__).resolve().parents[2]
REPO='vitorGgC569/SENTRA'
def validate_catalog(releases,fetch):
 for release in releases:
  if release.get('draft') or not release.get('tag_name','').startswith('mobile-preview-'):continue
  assets={a['name']:a for a in release.get('assets',[])}
  if not {'SENTRA-Android-preview.apk','mobile-downloads.json'}<=assets.keys():continue
  metadata_url=assets['mobile-downloads.json']['browser_download_url']
  if not metadata_url.startswith('https://github.com/'+REPO+'/releases/download/'):continue
  metadata=fetch(metadata_url)
  apk=assets['SENTRA-Android-preview.apk'];m=metadata.get('android',{})
  if metadata.get('schema')!=1 or m.get('sha256')!=apk.get('digest','').removeprefix('sha256:') or not re.fullmatch('[a-f0-9]{64}',m.get('sha256','')):continue
  if m.get('size')!=apk['size'] or metadata.get('tag')!=release['tag_name']:continue
  if 'version_code' in m:
   policy=json.loads((ROOT/'scripts/site/android-preview-signing.json').read_text())
   if (type(m['version_code']) is not int or m['version_code']<policy['minimum_version_code'] or
       m.get('package')!=policy['package'] or m.get('signing_certificate_sha256')!=policy['certificate_sha256']):continue
  url=apk['browser_download_url'];notes=release['html_url']
  if not url.startswith('https://github.com/'+REPO+'/releases/download/') or not notes.startswith('https://github.com/'+REPO+'/releases/tag/'):continue
  return {'url':url,'release':notes,'sha256':m['sha256'],'size':apk['size'],'version':release['tag_name'],
          **({k:m[k] for k in ('version_code','signing_certificate_sha256')} if 'version_code' in m else {})}
 return None

def validate_windows_catalog(releases,fetch):
 """Identify published multipart previews; never turn old checks into success."""
 base='https://github.com/'+REPO+'/releases/'
 ordered=sorted(releases,key=lambda r:r.get('published_at') or '',reverse=True)
 for release in ordered:
  tag=release.get('tag_name','')
  if release.get('draft') or not re.fullmatch(r'installer-preview-[A-Za-z0-9._-]+',tag):continue
  assets={a['name']:a for a in release.get('assets',[])}
  required={'windows-preview.json','preview-parts.json','PREVIEW-SHA256SUMS.txt','Reassemble-Preview.ps1'}
  if not required<=assets.keys() or release.get('html_url')!=base+'tag/'+tag:continue
  expected=base+'download/'+tag+'/'
  if any(assets[n].get('browser_download_url')!=expected+n for n in required):continue
  try:metadata=fetch(expected+'windows-preview.json')
  except (OSError,ValueError):continue
  if not isinstance(metadata,dict):continue
  source=metadata.get('source_commit','');setup=metadata.get('setup');parts=metadata.get('installer_parts')
  if not isinstance(setup,dict) or not isinstance(source,str):continue
  if not re.fullmatch('[a-f0-9]{40}',source) or not isinstance(setup.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',setup['sha256']):continue
  if type(setup.get('size_bytes')) is not int or setup['size_bytes']<=0:continue
  if not isinstance(parts,list) or not 1<=len(parts)<=32:continue
  verified=[]
  for part in parts:
   if not isinstance(part,dict):break
   name=part.get('name','')
   if not isinstance(name,str):break
   asset=assets.get(name,{})
   if (not re.fullmatch(r'SENTRA-Setup-[A-Za-z0-9._-]+\.exe\.part[0-9]+',name)
       or asset.get('browser_download_url')!=expected+name
       or type(part.get('size_bytes')) is not int or part['size_bytes']<=0
       or part['size_bytes']!=asset.get('size')
       or not isinstance(part.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',part['sha256'])
       or asset.get('digest')!='sha256:'+part['sha256']):break
   verified.append({'url':asset['browser_download_url'],'sha256':part['sha256'],'size':part['size_bytes']})
  if len(verified)!=len(parts) or len({p['url'] for p in verified})!=len(parts):continue
  if sum(p['size'] for p in verified)!=setup['size_bytes']:continue
  reviewed=json.loads((ROOT/'site/release-status.json').read_text())
  return {'release':release['html_url'],'metadata':expected+'windows-preview.json',
    'checksums':expected+'PREVIEW-SHA256SUMS.txt','version':tag,'source_commit':source,
    'sha256':setup['sha256'],'size':setup['size_bytes'],'parts':verified,
    'current_interface':source in reviewed.get('current_interface_installer_sources',[]),
    'stable_qualified':False}
 return None

def build(out,releases=None,fetch=None):
 if fetch is None:
  def fetch(url):
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SENTRA-download-catalog','Accept':'application/vnd.github+json'}),timeout=25) as r:return json.load(r)
 if releases is None:releases=fetch('https://api.github.com/repos/'+REPO+'/releases?per_page=30')
 out=out.resolve()
 if out==ROOT or not out.is_relative_to(ROOT/'.tmp'):raise ValueError('Site output must be inside repository .tmp')
 out.mkdir(parents=True,exist_ok=True)
 for f in (ROOT/'site').rglob('*'):
  if f.is_file():
   dest=out/f.relative_to(ROOT/'site');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,dest)
 for image in ['home.png','workspace.png','selector.png','sentra.png']:
  if not (out/'assets'/image).is_file():raise FileNotFoundError('Missing real demonstration screenshot: '+image)
 catalog={'schema':1,'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'android':validate_catalog(releases,fetch),'ios':None,'windows':validate_windows_catalog(releases,fetch)}
 (out/'downloads.json').write_text(json.dumps(catalog,indent=2)+'\n',encoding='utf-8')
 return catalog
if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__);p.add_argument('--out',type=Path,default=ROOT/'.tmp/pages');a=p.parse_args();print(json.dumps(build(a.out)))
