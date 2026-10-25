"""Produce checksummed metadata for an actual Android preview APK."""
from pathlib import Path
import datetime,hashlib,json,os,shutil
ROOT=Path(__file__).resolve().parents[2]
def package(apk,out,run,commit,verified=None):
 if not apk.is_file() or apk.stat().st_size<1024*1024:raise ValueError('No complete Android APK')
 out.mkdir(parents=True,exist_ok=True);target=out/'SENTRA-Android-preview.apk';shutil.copy2(apk,target)
 sha=hashlib.sha256(target.read_bytes()).hexdigest();tag='mobile-preview-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')+'-'+str(run)
 metadata={'schema':1,'tag':tag,'commit':commit,'physical_device_qualified':False,'android':{'sha256':sha,'size':target.stat().st_size,'package':'app.sentra.mobile.preview','architectures':['arm64-v8a']},'ios':None}
 if verified is not None:
  if verified.get('apk_sha256')!=sha or verified.get('version_code')!=int(run) or verified.get('package')!='app.sentra.mobile.preview':raise ValueError('Verified Android provenance does not match this APK')
  metadata['android'].update(version_code=verified['version_code'],signing_certificate_sha256=verified['certificate_sha256'])
 (out/'mobile-downloads.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
 (out/'SHA256SUMS.txt').write_text(sha+'  '+target.name+'\n',encoding='ascii')
 (out/'RELEASE-NOTES.md').write_text('# SENTRA Android preview\n\nStandalone ARM64 APK for LAN evaluation. No Metro server is required.\n\n'
  'Package: `app.sentra.mobile.preview`. Signed with the dedicated SENTRA preview key.\n\n'
  'Install the APK, connect to the same network as the Windows host, scan the temporary QR in Canvas → Devices and approve on the host.\n\n'
  '**Physical Android/iPhone qualification is pending.** This release does not include an iOS installation package or claim remote relay support.\n\n'
  'Source: `'+commit+'`. Verify the APK against SHA256SUMS.txt.\n',encoding='utf-8')
 return metadata
if __name__=='__main__':
 verified=json.loads((ROOT/os.environ['VERIFIED_ANDROID_REPORT']).read_text()) if os.environ.get('VERIFIED_ANDROID_REPORT') else None
 print(json.dumps(package(ROOT/os.environ['APK_PATH'],ROOT/'.tmp/mobile-release',os.environ['RUN_NUMBER'],os.environ.get('SOURCE_COMMIT') or os.environ['GITHUB_SHA'],verified)))
