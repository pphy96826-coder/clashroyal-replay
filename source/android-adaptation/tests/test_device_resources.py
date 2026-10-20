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

    def test_no_game_write_debugger_or_network_implementation(self):
        source=(DEVICE/'device_session.py').read_text()
        self.assertNotIn('os.O_RDWR',source)
        self.assertNotIn('os.pwrite',source)
        self.assertNotIn('import socket',source)
        self.assertNotIn('PTRACE_ATTACH',source)
        self.assertIn('os.O_RDONLY | os.O_CLOEXEC',source)


if __name__=='__main__':unittest.main()
