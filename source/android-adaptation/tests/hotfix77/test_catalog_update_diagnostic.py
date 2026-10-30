from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'device'))
from device_catalog_diagnostic import capture,simple_getter

class CatalogDiagnosticTests(unittest.TestCase):
    def test_only_plain_self_field_getters_are_decoded(self):
        self.assertEqual(simple_getter(struct.pack('<II',0xf9405000,0xd65f03c0)),dict(kind='pointer',field_offset='0xa0'))
        self.assertEqual(simple_getter(struct.pack('<II',0xb9423000,0xd65f03c0)),dict(kind='integer',field_offset='0x230'))
        for word in [0xf9405001,0xf9405020,0x94000000,0xd503201f]:
            self.assertIsNone(simple_getter(struct.pack('<II',word,0xd65f03c0)))
        self.assertIsNone(simple_getter(struct.pack('<II',0xf9405000,0xd63f0000)))

    def test_not_loaded_catalog_stops_before_traversing_objects(self):
        class Session:
            identity={'library_sha256':'a'*64}
            def read(self,address,size):
                assert address==0x1038 and size==8
                return bytes(8)
        result=capture(Session(),0x1000,{26000000})
        self.assertEqual(result['state'],'catalog_not_ready')
        self.assertFalse(result['native_calls'])
        self.assertFalse(result['compatibility_approved'])

    def test_new_catalog_count_does_not_trigger_unbounded_reads(self):
        class Session:
            base=0x1000000
            identity={'library_sha256':'a'*64}
            def read(self,address,size):
                if address==0x1038:return struct.pack('<Q',0x2000)
                assert address==0x2000 and size==0xc8
                raw=bytearray(size);struct.pack_into('<Q',raw,0,0x1001000)
                struct.pack_into('<Q',raw,0xb8,0x3000);struct.pack_into('<i',raw,0xc4,999999)
                return bytes(raw)
        self.assertEqual(capture(Session(),0x1000,set())['state'],'catalog_shape_changed')

if __name__=='__main__':unittest.main()
