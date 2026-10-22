"""Configure an Expo Android preview signing block after native prebuild."""
from pathlib import Path
import argparse,json
ROOT=Path(__file__).resolve().parents[2]
def prepare(app,build_number):
 if type(build_number) is not int or build_number<1:raise ValueError('Positive Android versionCode required')
 config=app/'app.json';value=json.loads(config.read_text(encoding='utf-8-sig'))
 value['expo']['name']='SENTRA Preview';value['expo']['android'].update(package='app.sentra.mobile.preview',versionCode=build_number)
 config.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def sign(app):
 path=app/'android/app/build.gradle';text=path.read_text()
 if '// SENTRA preview signing' in text:raise ValueError('Signing already configured')
 text+='''
// SENTRA preview signing. Secrets are environment-only; never Gradle arguments.
android {
 signingConfigs {
  sentraPreview {
   storeFile file(System.getenv("SENTRA_ANDROID_KEYSTORE_FILE"))
   storeType "PKCS12"
   storePassword System.getenv("SENTRA_ANDROID_STORE_PASSWORD")
   keyAlias System.getenv("SENTRA_ANDROID_KEY_ALIAS")
   keyPassword System.getenv("SENTRA_ANDROID_STORE_PASSWORD")
  }
 }
 buildTypes { release { signingConfig signingConfigs.sentraPreview } }
}
'''
 path.write_text(text)
if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__);p.add_argument('--prepare',type=int);a=p.parse_args();app=ROOT/'integrations/orca-mobile/app'
 if a.prepare is not None:prepare(app,a.prepare)
 else:sign(app)
