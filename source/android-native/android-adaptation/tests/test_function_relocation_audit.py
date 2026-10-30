import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from compare_client_functions import normalized
from resolve_update_functions import incoming_pin_candidate


def words(*items):
    return struct.pack('<'+'I'*len(items), *items)


class Image:
    def __init__(self, start, data):
        self.starts=[start]; self.data=data
    def at(self, va, n):
        return self.data[va-self.starts[0]:va-self.starts[0]+n]
    def body(self, index):
        return self.data


class FunctionRelocationTests(unittest.TestCase):
    def test_pc_relative_data_changes_normalized_without_masking_object_offsets(self):
        before = words(0x90000008, 0xf9457100, 0xf9411260)
        after = words(0xb0000008, 0xf943f100, 0xf9411260)
        self.assertEqual(normalized(before), normalized(after))
        self.assertNotEqual(normalized(before), normalized(after[:-4]+words(0xf9411660)))

    def test_changed_callee_does_not_keep_old_internal_offset(self):
        pin = words(0xa9be7bfd, 0x910003fd, 1, 2, 3, 4, 5, 0xd65f03c0)
        before=Image(0x1000, words(9, 10)+pin)
        after=Image(0x2000, words(9, 10, 11, 12)+pin)
        result, method=incoming_pin_candidate(before,after,0,0,0x1008)
        self.assertEqual(result,'0x2010')
        self.assertEqual(method,'unique_internal_pin')
        self.assertNotEqual(result,'0x2008')

    def test_repeated_internal_pin_is_not_arbitrarily_chosen(self):
        pin=words(1,2,3,4,5,6,7,8)
        before=Image(0x1000,words(99)+pin)
        after=Image(0x2000,words(99)+pin+pin)
        result, method=incoming_pin_candidate(before,after,0,0,0x1004)
        self.assertIsNone(result)
        self.assertEqual(method,'internal_pin_ambiguous')

    def test_entry_mapping_does_not_claim_body_equivalence(self):
        result, method=incoming_pin_candidate(Image(0x1000,words(1)),Image(0x2000,words(2)),0,0,0x1000)
        self.assertEqual((result,method),('0x2000','function_entry'))


if __name__=='__main__':
    unittest.main()
