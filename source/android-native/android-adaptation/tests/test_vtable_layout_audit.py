from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_vtable_layout import slots


class VirtualSlotTests(unittest.TestCase):
    def test_inserted_methods_shift_callback_slots_not_the_table_base(self):
        old = slots({0x1000+0xb08: 0x4000, 0x1000+0xb10: 0x5000},
                    0x1000, 0xc00, dict(interpolate='0x4000', frame='0x5000'))
        new = slots({0x2000+0xb28: 0x6000, 0x2000+0xb30: 0x7000},
                    0x2000, 0xc20, dict(interpolate='0x6000', frame='0x7000'))
        self.assertEqual([r['slots'] for r in old], [['0xb08'], ['0xb10']])
        self.assertEqual([r['slots'] for r in new], [['0xb28'], ['0xb30']])
        # The old-slot subtraction is 0x2020, not the constructor's table 0x2000.
        self.assertNotEqual(0x2000+int(new[1]['slots'][0], 0)-0xb10, 0x2000)

    def test_duplicates_and_absent_methods_remain_unresolved(self):
        result = slots({0x1000: 0x3000, 0x1008: 0x3000}, 0x1000, 32,
                       dict(repeated='0x3000', absent='0x4000'))
        self.assertEqual(result[0]['slots'], ['0x0', '0x8'])
        self.assertFalse(result[0]['unique'])
        self.assertEqual(result[1]['slots'], [])
        self.assertFalse(result[1]['unique'])

    def test_bad_table_ranges_rejected(self):
        for base, size in [(0, 32), (0x1001, 32), (0x1000, 16392), (0x1000, 9)]:
            with self.assertRaises(ValueError):
                slots({}, base, size, {})


if __name__ == '__main__':
    unittest.main()
