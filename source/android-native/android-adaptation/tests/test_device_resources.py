"""Source-only tests: no su, game attach or game memory access."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT/'device'
CONTRACT = ROOT.parents[0]/'official-web-replay'  # no historical files imported


def load_reader():
    spec = importlib.util.spec_from_file_location('device_session_test', DEVICE/'device_session.py')
    module = importlib.util.module_from_spec(spec)
    original = Path.read_text
    def content(path, *args, **kwargs):
        if path.name == 'native-contract.json':
            return json.dumps(dict(library_sha256='a'*64, package='test', executable_span=4096, jni_exports=[]))
        return original(path, *args, **kwargs)
    with patch.object(Path, 'read_text', content):
        maps_spec=importlib.util.spec_from_file_location('proc_maps',DEVICE/'proc_maps.py')
        maps_module=importlib.util.module_from_spec(maps_spec);maps_spec.loader.exec_module(maps_module)
        with patch.dict(sys.modules,proc_maps=maps_module):spec.loader.exec_module(module)
    return module


reader = load_reader()


class ResourceContractTests(unittest.TestCase):
    def test_start_time_with_spaces_and_parentheses(self):
        self.assertEqual(reader.start_time('9 (game (worker) name) '+' '.join(['S']+['1']*18+['12345'])), '12345')

    def test_bad_start_time_is_rejected(self):
        for text in ('', '9 (bad)', '9 no-parentheses'):
            with self.assertRaises(ValueError): reader.start_time(text)

    def test_read_range_can_cross_adjacent_readable_vmas(self):
        self.assertEqual(reader.checked_range(0x1800, 4096, [(0x1000,0x2000,'r--p'),(0x2000,0x3000,'rw-p')],0),0x1800)

    def test_gaps_and_unreadable_ranges_are_rejected(self):
        for mapping in ([(0x1000,0x2000,'r--p'),(0x2100,0x3000,'rw-p')],[(0x1000,0x2000,'r--p'),(0x2000,0x3000,'---p')]):
            with self.assertRaises(ValueError): reader.checked_range(0x1800,4096,mapping,0)

    def test_read_budgets_types_and_tagged_pointers(self):
        mapping=[(0x1000,0x3000,'r--p')]
        self.assertEqual(reader.checked_range(0xab00000000001800,8,mapping,0),0x1800)
        for address, size, used in ((True,4,0),(0x1800,True,0),(0x1800,4097,0),(0x1800,8,65530),(0x1800,0,0)):
            with self.assertRaises(ValueError): reader.checked_range(address,size,mapping,used)

    def test_ungranted_root_is_not_bypassed(self):
        with patch.object(reader.os,'getuid',return_value=10036),patch.object(reader,'installed_library') as apk:
            with self.assertRaises(PermissionError):reader.bind('/data/app/test/base.apk')
            apk.assert_not_called()

    def test_native_identity_preserves_heap_tag(self):
        import struct
        session=object.__new__(reader.ReadOnlySession)
        session.read=lambda address,size:struct.pack('<Q',0xb4000076f1cf4e10)
        self.assertEqual(session.raw_pointer(0x1000),0xb4000076f1cf4e10)
        self.assertEqual(session.pointer(0x1000),0x76f1cf4e10)

    def session_for_reads(self):
        session=object.__new__(reader.ReadOnlySession)
        session.mappings=[(0x1000,0x9000,'r--p')];session.used=0;session.proc=Path('/proc/1')
        calls=[];session.verify=lambda:(calls.append('full'),setattr(session,'verified_at',reader.time.monotonic()))
        session.generation=lambda:calls.append('generation')
        return session,calls

    def test_single_reads_check_generation_each_time_but_maps_at_most_once_per_interval(self):
        session,calls=self.session_for_reads()
        with patch.object(reader.os,'open',return_value=3),patch.object(reader.os,'close'),\
             patch.object(reader.os,'pread',side_effect=lambda fd,size,address:b'x'*size):
            for _ in range(50):session.read(0x1000,8)
            self.assertEqual(calls.count('full'),1)
            self.assertEqual(calls.count('generation'),99)  # before (49) and after (50) each read
            session.verified_at-=reader.FULL_VERIFY_INTERVAL
            session.read(0x1000,8);self.assertEqual(calls.count('full'),2)

    def test_generation_change_or_short_read_still_fails(self):
        session,calls=self.session_for_reads()
        def changed():raise ValueError('game generation changed')
        with patch.object(reader.os,'open',return_value=3),patch.object(reader.os,'close'),\
             patch.object(reader.os,'pread',side_effect=lambda fd,size,address:b'x'*size):
            session.read(0x1000,8);session.generation=changed
            with self.assertRaisesRegex(ValueError,'generation'):session.read(0x1000,8)
        session,calls=self.session_for_reads()
        with patch.object(reader.os,'open',return_value=3),patch.object(reader.os,'close'),\
             patch.object(reader.os,'pread',return_value=b'x'):
            with self.assertRaisesRegex(ValueError,'short'):session.read(0x1000,8)

    def test_library_hash_is_cached_only_for_an_unchanged_file(self):
        reader._LIBRARY_OFFSETS.clear()
        stat=lambda ino,size:type('S',(),dict(st_dev=1,st_ino=ino,st_size=size,st_mtime_ns=5))()
        states=[stat(7,100)]
        with patch.object(reader.os,'stat',side_effect=lambda p:states[0]),\
             patch.object(reader,'_hashed_library',return_value=4096) as hashed:
            apk='/data/app/x/base.apk'
            self.assertEqual(reader.installed_library(apk),4096);reader.installed_library(apk)
            self.assertEqual(hashed.call_count,1)
            states[0]=stat(8,100);reader.installed_library(apk);self.assertEqual(hashed.call_count,2)
            states[0]=stat(8,101);reader.installed_library(apk);self.assertEqual(hashed.call_count,3)
        with self.assertRaises(ValueError):reader.installed_library('/sdcard/base.apk')

    def test_no_game_write_debugger_or_network_implementation(self):
        source=(DEVICE/'device_session.py').read_text()
        self.assertNotIn('os.O_RDWR',source)
        self.assertNotIn('os.pwrite',source)
        self.assertNotIn('import socket',source)
        self.assertNotIn('PTRACE_ATTACH',source)
        self.assertIn('os.O_RDONLY | os.O_CLOEXEC',source)


if __name__=='__main__':unittest.main()
