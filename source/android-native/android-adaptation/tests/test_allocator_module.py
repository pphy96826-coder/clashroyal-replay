"""Verified libc registration for LLDB on phone VMs; fake debugger objects only."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'device/device_playback.py').read_text()
spec=importlib.util.spec_from_file_location('device_loader_alloc',ROOT/'device/device_loader.py')
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
LIBC=b'\x7fELF'+bytes(range(252))*64
MMAP=LIBC[300:332];MUNMAP=LIBC[400:416]


def load():
    tree=ast.parse(SOURCE)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('lldb_mmap_addresses','register_allocator')]
    scope=dict(hashlib=hashlib,json=json,Path=Path,read=lambda path:json.loads(Path(path).read_text()))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'allocator','exec'),scope)
    return scope['register_allocator']


class Address:
    def __init__(self,value):self.value=value
    def GetLoadAddress(self,target):return self.value
class Context:
    def __init__(self,value):self.value=value
    def GetFunction(self):return type('F',(),dict(IsValid=lambda s:False))()
    def GetSymbol(self):return type('S',(),dict(GetStartAddress=lambda s:Address(self.value)))()
class Found:
    def __init__(self,values):self.values=values
    def GetSize(self):return len(self.values)
    def GetContextAtIndex(self,index):return Context(self.values[index])
class Status:
    def __init__(self,ok):self.ok=ok
    def Success(self):return self.ok
class Module:
    def IsValid(self):return True
class Target:
    def __init__(self,initial=(),slide_to=None):
        self.symbols=list(initial);self.slide_to=slide_to;self.added=[];self.removed=0;self.slide=None
    def FindFunctions(self,name,kind):return Found(self.symbols)
    def AddModule(self,path,triple,uuid):self.added.append(path);return Module()
    def SetModuleLoadAddress(self,module,slide):
        self.slide=slide;self.symbols=[(self.slide_to if self.slide_to is not None else slide)+300];return Status(True)
    def RemoveModule(self,module):self.removed+=1;self.symbols=[]
class Lldb:
    LLDB_INVALID_ADDRESS=2**64-1;eFunctionNameTypeFull=2
class Session:
    def __init__(self,live=None):self.live=live or {}
    def read(self,address,size):return self.live.get(address,b'\0'*size)[:size]


class AllocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dir=Path(self.temp.name)
        self.libc=self.dir/'libc.so';self.libc.write_bytes(LIBC)
        base=0x7000000000
        self.base=base
        pins=dict(mmap=dict(address=hex(base+300),size=32,sha256=hashlib.sha256(MMAP).hexdigest()),
                  munmap=dict(address=hex(base+400),size=16,sha256=hashlib.sha256(MUNMAP).hexdigest()))
        self.loader=dict(identity=dict(pid=1),allocator=dict(library=str(self.libc),library_sha256=hashlib.sha256(LIBC).hexdigest(),
                         base=hex(base),exports=pins))
        (self.dir/'a-loader-binding.json').write_text(json.dumps(self.loader))
        self.session=Session({base+300:MMAP,base+400:MUNMAP})
        self.register=load()

    def tearDown(self):self.temp.cleanup()

    def evidence(self):return json.loads((self.dir/'a-allocator-binding.json').read_text())

    def test_lldb_that_already_finds_mmap_is_left_unchanged(self):
        target=Target(initial=[0x1234])
        result=self.register(Lldb,target,self.dir,'a','a',self.session)
        self.assertFalse(result['needed']);self.assertEqual(target.added,[])
        self.assertFalse((self.dir/'a-allocator-binding.json').exists())

    def test_missing_mmap_registers_verified_libc_at_verified_base(self):
        target=Target()
        result=self.register(Lldb,target,self.dir,'a','a',self.session)
        self.assertTrue(result['registered']);self.assertEqual(target.added,[str(self.libc)])
        self.assertEqual(target.slide,self.base);self.assertEqual(target.removed,0)
        saved=self.evidence();self.assertTrue(saved['registered']);self.assertFalse(saved['native_calls'])
        self.assertFalse(saved['game_memory_written']);self.assertEqual(saved['lldb_mmap'],[hex(self.base+300)])

    def test_changed_file_live_bytes_or_symbol_address_fail_closed(self):
        self.libc.write_bytes(LIBC+b'x')
        with self.assertRaisesRegex(RuntimeError,'libc file changed'):self.register(Lldb,Target(),self.dir,'a','a',self.session)
        self.libc.write_bytes(LIBC)
        with self.assertRaisesRegex(RuntimeError,'live libc allocator bytes changed'):
            self.register(Lldb,Target(),self.dir,'a','b',Session())
        target=Target(slide_to=0x6000000000)
        with self.assertRaisesRegex(RuntimeError,'mmap differs'):self.register(Lldb,target,self.dir,'a','c',self.session)
        self.assertEqual(target.removed,1)
        self.assertIn('differs',json.loads((self.dir/'c-allocator-binding.json').read_text())['error'])

    def test_unverified_allocator_refuses_instead_of_guessing(self):
        del self.loader['allocator'];(self.dir/'a-loader-binding.json').write_text(json.dumps(self.loader))
        target=Target()
        with self.assertRaisesRegex(RuntimeError,'not verified'):self.register(Lldb,target,self.dir,'a','a',self.session)
        self.assertEqual(target.added,[])

    def test_registration_happens_after_attach_before_any_gate(self):
        block=SOURCE[SOURCE.index("process=target.AttachToProcessWithID"):SOURCE.index("return read(directory/(name+'-result.json'))")]
        self.assertLess(block.index('register_allocator('),block.index('import run_scene_gate'))
        self.assertLess(block.index('register_allocator('),block.index('import phone_bootstrap_gate'))
        gate=(ROOT/'device/phone_bootstrap_gate.py').read_text()
        self.assertIn("list(loader['exports'].values()),allocator)",gate)
        runtime=(ROOT/'device/device_runtime.py').read_text()
        self.assertIn("resolve_loader(session,Elf,library='libc.so',names=('mmap','munmap'))",runtime)


class LibcLoaderTests(unittest.TestCase):
    def test_libc_variant_uses_libc_rows_and_requested_exports(self):
        raw=bytes(range(256))*32
        class Elf:
            def __init__(self,data):
                if data!=raw:raise ValueError('bad ELF')
                self.raw=data;self.phoff=64
                self.programs=[(1,5,0,0,0,4096,4096,4096)]
            def slice(self,offset,size):return self.raw[offset:offset+size]
            def at(self,va,size):return self.raw[va:va+size]
            def exports(self,names):
                return {n:dict(va=hex(256+i*16),size=16,sha256=hashlib.sha256(raw[256+i*16:272+i*16]).hexdigest())
                        for i,n in enumerate(sorted(names))}
        text=('100000-101000 r-xp 00000000 08:01 42 /apex/com.android.runtime/lib64/bionic/libc.so\n'
              '200000-201000 r-xp 00000000 08:01 43 /apex/com.android.runtime/lib64/bionic/libdl.so')
        class Session:
            proc=Path('/proc/1');used=0;identity=dict(pid=1)
            def verify(self):return text
            def read_many(self,ranges):return [raw[a-0x100000:a-0x100000+s] for a,s in ranges]
        result,diagnostic=loader.resolve_loader(Session(),Elf,page=4096,read_file=lambda p:raw,
                                                library='libc.so',names=('mmap','munmap'))
        self.assertEqual(result['base'],'0x100000');self.assertEqual(set(result['exports']),{'mmap','munmap'})
        self.assertTrue(result['library'].endswith('/libc.so'));self.assertEqual(diagnostic['mapped_objects'],1)


if __name__=='__main__':unittest.main()
