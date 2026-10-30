import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_pending_code_contract import build

class Image:
    data=b'owned synthetic library'
    def at(self,va,size):return b'F'*size

class PendingContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name);digest=hashlib.sha256(Image.data).hexdigest()
        self.reference=dict(library_sha256='a'*64,pins=[dict(va='0x1000',size=32),dict(va='0x2000',size=32)])
        self.candidates=dict(schema='royale-replay.code-candidates.v1',library_sha256=digest,
                             functions={'pin-1000':dict(va='0x3000',bytes=32),'pin-2000':dict(va='0x4000',bytes=32)})
        self.snapshot=dict(schema='royale-replay.loaded-code-snapshot.v1',library_sha256=digest,
                           generation_verified=True,native_calls=False,game_memory_written=False,
                           process_id=12345,functions={})
        for name,row in self.candidates['functions'].items():
            raw=b'R'*32;(self.path/(name+'.bin')).write_bytes(raw)
            self.snapshot['functions'][name]=dict(**row,file=name+'.bin',sha256=hashlib.sha256(raw).hexdigest())
    def run_build(self):return build(self.reference,self.candidates,self.snapshot,self.path,Image())
    def test_complete_set_keeps_approval_disabled_and_excludes_process_state(self):
        self.snapshot['supported']=True
        r=self.run_build();self.assertEqual(len(r['pins']),2)
        self.assertFalse(r['supported']);self.assertFalse(r['native_execution_allowed'])
        self.assertNotIn('process_id',r)
        self.assertNotEqual(r['pins'][0]['file_sha256'],r['pins'][0]['runtime_sha256'])
    def test_missing_duplicate_and_wrong_generation_are_rejected(self):
        before=copy.deepcopy(self.snapshot)
        self.snapshot['functions'].pop('pin-1000')
        with self.assertRaises(ValueError):self.run_build()
        self.snapshot=before;self.snapshot['generation_verified']=False
        with self.assertRaises(ValueError):self.run_build()
        self.snapshot=before;self.snapshot['generation_verified']=True
        self.candidates['functions']['pin-2000']['va']='0x3000'
        self.snapshot['functions']['pin-2000']['va']='0x3000'
        with self.assertRaises(ValueError):self.run_build()
    def test_wrong_hash_and_tampered_capture_rejected(self):
        self.snapshot['library_sha256']='f'*64
        with self.assertRaises(ValueError):self.run_build()
        self.snapshot['library_sha256']=self.candidates['library_sha256']
        (self.path/'pin-1000.bin').write_bytes(b'X'*32)
        with self.assertRaises(ValueError):self.run_build()

if __name__=='__main__':unittest.main()
