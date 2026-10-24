import unittest
from scripts.site.build import validate_catalog, validate_windows_catalog
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
class WindowsCatalogTests(unittest.TestCase):
 def setUp(self):
  self.tag='installer-preview-20261023-1'
  base='https://github.com/vitorGgC569/SENTRA/releases/'
  names=['windows-preview.json','preview-parts.json','PREVIEW-SHA256SUMS.txt','Reassemble-Preview.ps1','SENTRA-Setup-1.0.1.exe.part0001']
  self.release={'tag_name':self.tag,'draft':False,'published_at':'2026-10-23','html_url':base+'tag/'+self.tag,'assets':[
   {'name':n,'browser_download_url':base+'download/'+self.tag+'/'+n,'size':10,'digest':'sha256:'+'a'*64} for n in names]}
  self.metadata={'source_commit':'b'*40,'setup':{'size_bytes':10,'sha256':'c'*64},'installer_parts':[{'name':names[-1],'size_bytes':10,'sha256':'a'*64}]}
 def verify(self):return validate_windows_catalog([self.release],lambda _:self.metadata)
 def test_verified_old_preview_is_not_current_or_stable(self):
  result=self.verify();self.assertEqual(result['size'],10);self.assertFalse(result['current_interface']);self.assertFalse(result['stable_qualified'])
 def test_wrong_digest_size_or_duplicate_parts_is_rejected(self):
  self.release['assets'][-1]['digest']='sha256:'+'d'*64;self.assertIsNone(self.verify())
  self.release['assets'][-1]['digest']='sha256:'+'a'*64;self.metadata['setup']['size_bytes']=11;self.assertIsNone(self.verify())
  self.metadata['setup']['size_bytes']=20;self.metadata['installer_parts']*=2;self.assertIsNone(self.verify())
 def test_foreign_metadata_or_draft_is_never_fetched(self):
  self.release['assets'][0]['browser_download_url']='https://example.com/metadata'
  self.assertIsNone(validate_windows_catalog([self.release],lambda _:self.fail('Foreign fetch')))
  self.setUp();self.release['draft']=True
  self.assertIsNone(validate_windows_catalog([self.release],lambda _:self.fail('Draft fetch')))
 def test_malformed_metadata_is_unavailable(self):
  for invalid in (None,[],{'setup':[]},{'source_commit':123,'setup':{}}, {**self.metadata,'installer_parts':[None]}):
   with self.subTest(invalid=invalid):self.assertIsNone(validate_windows_catalog([self.release],lambda _:invalid))
 def test_newest_published_candidate_wins(self):
  older={**self.release,'published_at':'2026-10-22','html_url':'invalid'}
  self.assertEqual(validate_windows_catalog([older,self.release],lambda _:self.metadata)['version'],self.tag)

if __name__=='__main__':unittest.main()
