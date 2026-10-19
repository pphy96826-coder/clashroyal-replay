from pathlib import Path
import sys
import struct
import types
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'project/official-web-replay'))
from mapped_elf import game_mapping,load_bias
from elf_contract import Elf

class MappedElfTests(unittest.TestCase):
    def test_native_bridge_relative_callbacks_reject_wrong_relocation_type(self):
        raw=bytearray(0x200);raw[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<H',raw,18,62);struct.pack_into('<H',raw,54,56)
        struct.pack_into('<Q',raw,40,64);struct.pack_into('<HH',raw,58,64,1)
        struct.pack_into('<II4QII2Q',raw,64,0,4,0,0,0xa0,24,0,0,8,24)
        struct.pack_into('<QQq',raw,0xa0,0x4748,8,0x1e80)
        self.assertEqual(Elf(raw,machine=62).relative_pointer(0x4748),0x1e80)
        struct.pack_into('<Q',raw,0xa8,7)
        with self.assertRaises(ValueError):Elf(raw,machine=62).relative_pointer(0x4748)

    def test_mumu_repeated_zero_offsets_require_complete_segment_geometry(self):
        path='/system/lib64/arm64/nb/libdl.so'
        elf=types.SimpleNamespace(programs=[(1,4,0,0,0,0x494,0x494,4096),(1,5,0x4a0,0x14a0,0,0xd4,0xd4,4096),(1,6,0x578,0x2578,0,0xa0,0xa0,4096)])
        rows=[f'{low:x}-{low+4096:x} r--p 00000000 08:06 1 {path}' for low in (0x10000,0x11000,0x12000)]
        self.assertEqual(load_bias(rows,path,elf),0x10000)
        with self.assertRaises(ValueError):load_bias(rows[:-1],path,elf)
        duplicate=rows+[f'{low:x}-{low+4096:x} r--p 00000000 08:06 1 {path}' for low in (0x20000,0x21000,0x22000)]
        with self.assertRaises(ValueError):load_bias(duplicate,path,elf)
        self.assertEqual(load_bias(duplicate,path,elf,anchor=(0x1550,0x21550)),0x20000)
        with self.assertRaises(ValueError):load_bias(duplicate,path,elf,anchor=(0x1550,0x31550))

    def test_readonly_guest_mapping_requires_explicit_translated_mode_and_extent(self):
        profile=dict(mapping_file_offset=0x284d000,executable_span=0x1b3d000)
        row='03164000-04ca1000 r--p 0284d000 08:23 1 /data/app/game/base.apk'
        with self.assertRaises(ValueError):game_mapping([row],'/data/app/game/base.apk',profile)
        self.assertEqual(game_mapping([row],'/data/app/game/base.apk',profile,True)[:2],(0x3164000,0x4ca1000))
        with self.assertRaises(ValueError):game_mapping([row.replace('04ca1000','04ca2000')],'/data/app/game/base.apk',profile,True)

if __name__=='__main__':unittest.main()
