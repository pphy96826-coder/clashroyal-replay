import struct
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_object_allocation import allocations, safe_argument_move


def call(pc, destination):
    return 0x94000000 | (((destination-pc)//4) & 0x3ffffff)


def image(size=0x240, middle=()):
    words = [0x52800000 | (size << 5), call(0x1004, 0x2000),
             0x52800021, 0xaa1503e2, 0xaa1603e3, 0x2a1f03e4, 0xaa0003f7,
             *middle]
    words.append(call(0x1000+len(words)*4, 0x3000))
    data = struct.pack('<'+'I'*len(words), *words)
    return SimpleNamespace(data=data, loads=[(0, 0x1000, len(data))])


class AllocationTests(unittest.TestCase):
    def test_allocation_growth_not_masked_as_address_relocation(self):
        old = allocations(image(), 0x3000, 0x2000)
        new = allocations(image(0x248), 0x3000, 0x2000)
        self.assertEqual(old['observed_sizes'], [576])
        self.assertEqual(new['observed_sizes'], [584])
        self.assertTrue(new['consistent'])
        self.assertFalse(new['native_execution_allowed'])

    def test_return_value_clobber_or_extra_call_breaks_proof(self):
        for middle in [(0xaa1603e0,), (call(0x101c, 0x2500),), (0xf9000260,)]:
            result = allocations(image(middle=middle), 0x3000, 0x2000)
            self.assertFalse(result['consistent'])
            self.assertEqual(len(result['unrecognized_calls']), 1)

    def test_only_narrow_argument_moves_accepted(self):
        self.assertTrue(safe_argument_move(0xaa0003f7))
        self.assertTrue(safe_argument_move(0x52800021))
        self.assertFalse(safe_argument_move(0xaa1703e0))
        self.assertFalse(safe_argument_move(0x94000000))


if __name__ == '__main__':
    unittest.main()
