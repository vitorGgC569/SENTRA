import hashlib,json,tempfile,unittest
from pathlib import Path
from scripts.site.verify_android import verify
from scripts.site.build import validate_catalog,ROOT


class AndroidVerificationTests(unittest.TestCase):
 def setUp(self):
  self.policy=json.loads((ROOT/'scripts/site/android-preview-signing.json').read_text())
  self.sign='Signer #1 certificate SHA-256 digest: '+self.policy['certificate_sha256']+'\n'
  self.badging="package: name='app.sentra.mobile.preview' versionCode='3' versionName='0.1.0'\n"
 def test_signed_update_keeps_package_certificate_and_increases_version(self):
  with tempfile.TemporaryDirectory() as folder:
   apk=Path(folder)/'test.apk';apk.write_bytes(b'owned synthetic artifact')
   result=verify(apk,self.sign,self.badging,3,self.policy)
   self.assertEqual(result['version_code'],3);self.assertEqual(result['apk_sha256'],hashlib.sha256(apk.read_bytes()).hexdigest())
   for sign,badging,run in [(self.sign.replace(self.policy['certificate_sha256'],'a'*64),self.badging,3),
      (self.sign,self.badging.replace('preview','foreign'),3),(self.sign,self.badging,4),
      (self.sign,self.badging.replace("Code='3'","Code='2'"),2),(self.sign+self.sign,self.badging,3)]:
    with self.assertRaises(ValueError):verify(apk,sign,badging,run,self.policy)

 def test_signature_refusal_reports_only_public_certificate_diagnostics(self):
  with tempfile.TemporaryDirectory() as folder:
   apk=Path(folder)/'test.apk';apk.write_bytes(b'owned artifact')
   with self.assertRaisesRegex(ValueError,'public_certificate_sha256') as refused:
    verify(apk,self.sign.replace(self.policy['certificate_sha256'],'a'*64),self.badging,3,self.policy)
   self.assertIn('a'*64,str(refused.exception))
   self.assertNotIn('password',str(refused.exception))


if __name__=='__main__':unittest.main()
