"""Executable JVM tests of the exact phone-side candidate resolver, without a device."""
import hashlib,importlib.util,os,shutil,struct,subprocess,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('relocation_reference',ROOT/'scripts/build_relocation_reference.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class RelocationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.build=tempfile.TemporaryDirectory();cls.javac=shutil.which('javac');cls.java=shutil.which('java')
  subprocess.run([cls.javac,'-d',cls.build.name,str(ROOT/'app/src/local/royale/replay/android/ClientRelocator.java'),str(ROOT/'tests/hotfix77/ClientRelocatorCheck.java')],check=True,capture_output=True)
 @classmethod
 def tearDownClass(cls):cls.build.cleanup()
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
  self.data=bytearray(0x400);self.data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',self.data,18,183);struct.pack_into('<Q',self.data,32,64);struct.pack_into('<HH',self.data,54,56,1);struct.pack_into('<IIQQQQQQ',self.data,64,1,5,0x100,0x1000,0x1000,0x300,0x300,4)
  for offset in range(0x100,len(self.data),4):struct.pack_into('<I',self.data,offset,0xd503201f)
 def words(self,offset,words):struct.pack_into('<8I',self.data,offset,*words)
 def row(self,key,words,edge='-'):
  normalized=struct.pack('<8I',*(module.normalize(w) for w in words));return f'{key} {hashlib.sha256(normalized).hexdigest()} {module.normalize(words[0]):08x} {edge}'
 def run_scan(self,rows):
  apk=self.path/'client.apk';reference=self.path/'reference.tsv'
  with zipfile.ZipFile(apk,'w') as z:z.writestr('lib/arm64-v8a/libg.so',self.data)
  reference.write_text('replay-relocation-v2 '+'a'*64+'\n'+'\n'.join(rows)+'\n')
  before=apk.read_bytes();r=subprocess.run([self.java,'-cp',self.build.name,'local.royale.replay.android.ClientRelocatorCheck',str(apk),str(reference),'a'*64],capture_output=True,text=True);self.assertEqual(apk.read_bytes(),before);return r
 def test_pc_relative_change_still_resolves_moved_function(self):
  old=[0x94000010,0xd65f03c0,1,2,3,4,5,6];new=[0x94000030,*old[1:]];self.words(0x180,new)
  r=self.run_scan([self.row('100',old)]);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('unique=1',r.stdout)
 def test_identical_short_patterns_remain_ambiguous(self):
  words=[0xd65f03c0,1,2,3,4,5,6,7];self.words(0x100,words);self.words(0x180,words)
  r=self.run_scan([self.row('100',words)]);self.assertIn('ambiguous=1',r.stdout)
 def test_call_graph_rejects_wrong_duplicate(self):
  source=[0x94000020,0xd65f03c0,1,2,3,4,5,6];target=[0xd65f03c0,7,8,9,10,11,12,13]
  self.words(0x100,source);self.words(0x140,[0x94000030,*source[1:]]);self.words(0x180,target)
  r=self.run_scan([self.row('100',source,'0:200'),self.row('200',target)]);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('unique=2',r.stdout);self.assertIn('rejected=1',r.stdout)
 def test_unknown_graph_target_and_wrong_architecture_rejected(self):
  words=[0xd65f03c0,1,2,3,4,5,6,7]
  self.assertNotEqual(self.run_scan([self.row('100',words,'0:999')]).returncode,0)
  struct.pack_into('<H',self.data,18,62);self.assertNotEqual(self.run_scan([self.row('100',words)]).returncode,0)
 def test_masking_preserves_registers_and_non_address_immediates(self):
  self.assertEqual(module.normalize(0x94000010),module.normalize(0x94000020))
  self.assertNotEqual(module.normalize(0x91000400),module.normalize(0x91000800))
  self.assertNotEqual(module.normalize(0x90000000),module.normalize(0x90000001))
if __name__=='__main__':unittest.main()
