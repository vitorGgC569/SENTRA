"""Produce checksummed metadata for an actual Android preview APK."""
from pathlib import Path
import datetime,hashlib,json,os,shutil
ROOT=Path(__file__).resolve().parents[2]
def package(apk,out,run,commit):
 if not apk.is_file() or apk.stat().st_size<1024*1024:raise ValueError('No complete Android APK')
 out.mkdir(parents=True,exist_ok=True);target=out/'SENTRA-Android-preview.apk';shutil.copy2(apk,target)
 sha=hashlib.sha256(target.read_bytes()).hexdigest();tag='mobile-preview-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')+'-'+str(run)
 metadata={'schema':1,'tag':tag,'commit':commit,'physical_device_qualified':False,'android':{'sha256':sha,'size':target.stat().st_size,'package':'app.sentra.mobile.preview','architectures':['arm64-v8a']},'ios':None}
 (out/'mobile-downloads.json').write_text(json.dumps(metadata,indent=2)+'\n')
 (out/'SHA256SUMS.txt').write_text(sha+'  '+target.name+'\n')
 (out/'RELEASE-NOTES.md').write_text('# SENTRA Android preview\n\nStandalone ARM64 APK for LAN evaluation. No Metro server is required.\n\n'
  'Package: `app.sentra.mobile.preview`. Signed with the dedicated SENTRA preview key.\n\n'
  'Install the APK, connect to the same network as the Windows host, scan the temporary QR in Canvas → Devices and approve on the host.\n\n'
  '**Physical Android/iPhone qualification is pending.** This release does not include an iOS installation package or claim remote relay support.\n\n'
  'Source: `'+commit+'`. Verify the APK against SHA256SUMS.txt.\n')
 return metadata
if __name__=='__main__':print(json.dumps(package(ROOT/os.environ['APK_PATH'],ROOT/'.tmp/mobile-release',os.environ['RUN_NUMBER'],os.environ['GITHUB_SHA'])))
