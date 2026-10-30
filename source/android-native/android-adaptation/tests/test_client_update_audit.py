import hashlib,importlib.util,struct,tempfile,unittest,zipfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('audit_update',Path(__file__).resolve().parents[1]/'scripts/audit_client_update.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class AuditTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.apk=Path(self.tmp.name)/'client.apk'
  self.data=bytearray(192);self.data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',self.data,18,183);struct.pack_into('<Q',self.data,32,64);struct.pack_into('<HH',self.data,54,56,1)
  struct.pack_into('<IIQQQQQQ',self.data,64,1,5,128,4096,4096,64,64,4)
  self.contract={'library_sha256':'0'*64,'pins':[{'va':'0x1000','size':32,'file_sha256':hashlib.sha256(self.data[128:160]).hexdigest()}]}
 def save(self):
  with zipfile.ZipFile(self.apk,'w') as z:z.writestr('lib/arm64-v8a/libg.so',self.data)
 def test_even_all_code_samples_matching_do_not_authorize_an_unknown_binary(self):
  self.save();r=module.audit(self.apk,self.contract);self.assertEqual(r['matching_pins'],1);self.assertFalse(r['supported']);self.assertTrue(r['adaptation_required']);self.assertFalse(r['native_calls'])
 def test_full_hash_match_selects_existing_adapter(self):
  self.save();self.contract['library_sha256']=hashlib.sha256(self.data).hexdigest();self.assertTrue(module.audit(self.apk,self.contract)['supported'])
 def test_architecture_and_corrupt_tables_are_rejected(self):
  for offset,fmt,value in [(18,'<H',62),(54,'<H',0),(32,'<Q',99999)]:
   before=self.data[:];struct.pack_into(fmt,self.data,offset,value);self.save()
   with self.assertRaises(ValueError):module.audit(self.apk,self.contract)
   self.data=before
 def test_readonly_audit_does_not_modify_apk(self):
  self.save();before=self.apk.read_bytes();module.audit(self.apk,self.contract);self.assertEqual(self.apk.read_bytes(),before)
if __name__=='__main__':unittest.main()
