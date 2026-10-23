import ast,hashlib,re,stat,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class BatchTests(unittest.TestCase):
 def setup_scope(self):
  self.raw=b'\x7fELF'+bytes(124)+b'first-func'+b'second-func'+bytes(100)
  exports={str(i):dict(va=hex(offset),size=size,sha256=hashlib.sha256(self.raw[offset:offset+size]).hexdigest()) for i,(offset,size) in enumerate(((128,10),(138,11)))}
  self.component=dict(device_path='/data/local/tmp/royale-phone-'+'a'*32+'/libphone_replay_bootstrap.so',sha256=hashlib.sha256(self.raw).hexdigest(),exports=exports)
  outer=self
  class File:
   def __init__(self,path):self.path=path
   @property
   def parent(self):return File('parent')
   def lstat(self):return types.SimpleNamespace(st_mode=(stat.S_IFDIR|0o750) if self.path=='parent' else stat.S_IFREG|0o640,st_uid=0,st_size=len(outer.raw))
   def read_bytes(self):return outer.raw
  class Elf:
   programs=[(1,1,0,0,0,len(self.raw))]
   def __init__(self,raw):pass
   def exports(self,wanted):return exports
  self.session=types.SimpleNamespace(identity={'native_transport':'mumu-nativebridge-v1'},verify=lambda:'maps')
  self.calls=[]
  def read_many(ranges):
   self.calls.append(ranges);return [outer.raw[address-0x10000:address-0x10000+size] for address,size in ranges]
  self.session.read_many=read_many;self.session.read=lambda *a:(_ for _ in ()).throw(AssertionError('per-export transaction used'))
  text=(ROOT/'device/mumu_runtime.py').read_text(encoding='utf-8');node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='component_code_ranges');scope=dict(enabled=lambda:True,Path=File,stat=stat,hashlib=hashlib,re=re,Elf=Elf,load_bias=lambda *a:0x10000);exec(compile(ast.Module(body=[node],type_ignores=[]),'component-batch','exec'),scope);return scope['component_code_ranges']
 def test_all_header_and_export_hashes_use_one_bounded_transaction(self):
  run=self.setup_scope();self.assertEqual(run(self.session,self.component),[(0x10000,0x10000+len(self.raw))]);self.assertEqual(len(self.calls),1);self.assertEqual(len(self.calls[0]),3)
 def test_export_mutation_still_rejected(self):
  run=self.setup_scope();original=self.session.read_many
  def corrupted(ranges):
   raw=original(ranges);raw[1]=b'x'*len(raw[1]);return raw
  self.session.read_many=corrupted
  with self.assertRaisesRegex(ValueError,'loaded component export differs'):run(self.session,self.component)
 def test_header_mutation_still_rejected(self):
  run=self.setup_scope();original=self.session.read_many
  def corrupted(ranges):
   raw=original(ranges);raw[0]=b'x'*64;return raw
  self.session.read_many=corrupted
  with self.assertRaisesRegex(ValueError,'header differs'):run(self.session,self.component)
 def test_file_hash_must_still_match(self):
  run=self.setup_scope();self.component['sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'hash differs'):run(self.session,self.component)
  self.assertEqual(self.calls,[])
 def test_batch_process_verification_failure_propagates(self):
  run=self.setup_scope();self.session.read_many=lambda *a:(_ for _ in ()).throw(ValueError('game generation changed'))
  with self.assertRaisesRegex(ValueError,'generation changed'):run(self.session,self.component)
 def test_ownership_path_still_bounded(self):
  run=self.setup_scope();self.component['device_path']='/data/local/tmp/foreign.so'
  with self.assertRaisesRegex(ValueError,'not an owned'):run(self.session,self.component)
