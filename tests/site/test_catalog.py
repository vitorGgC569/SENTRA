import unittest
from scripts.site.build import validate_catalog
class CatalogTests(unittest.TestCase):
 def release(self):
  base='https://github.com/vitorGgC569/SENTRA/releases/'
  return {'tag_name':'mobile-preview-1','draft':False,'html_url':base+'tag/mobile-preview-1','assets':[
   {'name':'SENTRA-Android-preview.apk','browser_download_url':base+'download/mobile-preview-1/SENTRA-Android-preview.apk','digest':'sha256:'+'a'*64,'size':12345},
   {'name':'mobile-downloads.json','browser_download_url':base+'download/mobile-preview-1/mobile-downloads.json'}]}
 def metadata(self,_):return {'schema':1,'tag':'mobile-preview-1','android':{'sha256':'a'*64,'size':12345}}
 def test_empty_is_unavailable(self):self.assertIsNone(validate_catalog([],self.metadata))
 def test_verified_asset_only(self):self.assertEqual(validate_catalog([self.release()],self.metadata)['sha256'],'a'*64)
 def test_mismatched_digest_is_unavailable(self):
  r=self.release();r['assets'][0]['digest']='sha256:'+'b'*64;self.assertIsNone(validate_catalog([r],self.metadata))
 def test_draft_or_old_release_cannot_supply_download(self):
  r=self.release();r['draft']=True;self.assertIsNone(validate_catalog([r],self.metadata));r['draft']=False;r['tag_name']='installer-preview-old';self.assertIsNone(validate_catalog([r],self.metadata))
 def test_foreign_metadata_not_fetched(self):
  r=self.release();r['assets'][1]['browser_download_url']='https://invalid.test/metadata'
  self.assertIsNone(validate_catalog([r],lambda _:self.fail('Foreign fetch')))
 def test_size_mismatch(self):
  r=self.release();r['assets'][0]['size']=1;self.assertIsNone(validate_catalog([r],self.metadata))
 def test_new_mobile_metadata_requires_preserved_signer_and_version(self):
  from scripts.site.build import ROOT
  import json
  policy=json.loads((ROOT/'scripts/site/android-preview-signing.json').read_text())
  metadata=self.metadata(None);metadata['android'].update(version_code=3,package=policy['package'],signing_certificate_sha256=policy['certificate_sha256'])
  self.assertEqual(validate_catalog([self.release()],lambda _:metadata)['version_code'],3)
  for key,value in [('version_code',2),('package','foreign'),('signing_certificate_sha256','b'*64)]:
   bad={**metadata,'android':{**metadata['android'],key:value}}
   self.assertIsNone(validate_catalog([self.release()],lambda _:bad))
if __name__=='__main__':unittest.main()
