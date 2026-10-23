import hashlib,json,tempfile,unittest
from pathlib import Path
from scripts.site.verify_android import verify,certificate_identity
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

 def test_v31_sdk_labels_keep_exactly_one_preserved_identity(self):
  digest=self.policy['certificate_sha256']
  report=('Number of signers: 1\n'
          f'Signer (minSdkVersion=33, maxSdkVersion=2147483647) certificate SHA-256 digest: {digest}\n'
          f'Signer (minSdkVersion=24, maxSdkVersion=32) certificate SHA-256 digest: {digest}\n')
  self.assertEqual(certificate_identity(report),digest)
  for invalid in (report.replace('Number of signers: 1','Number of signers: 2'),
     report.replace(digest,'a'*64,1),report.replace('maxSdkVersion=32','maxSdkVersion=33'),
     report+self.sign,report.replace('Number of signers: 1\n',''),
     report.replace('maxSdkVersion=2147483647','maxSdkVersion=2147483648')):
   with self.assertRaises(ValueError):certificate_identity(invalid)

 def test_actual_build_tools_scheme_label_requires_one_preserved_signer(self):
  digest=self.policy['certificate_sha256']
  report=f'Number of signers: 1\nV2 Signer: certificate SHA-256 digest: {digest}\n'
  self.assertEqual(certificate_identity(report),digest)
  self.assertEqual(certificate_identity(report+f'V3 Signer: certificate SHA-256 digest: {digest}\n'),digest)
  for invalid in (report.replace('signers: 1','signers: 2'),report.replace('Number of signers: 1\n',''),
      report+report.split('\n')[1]+'\n',report+f'V3 Signer: certificate SHA-256 digest: {"a"*64}\n',report+self.sign):
   with self.assertRaises(ValueError):certificate_identity(invalid)


if __name__=='__main__':unittest.main()
