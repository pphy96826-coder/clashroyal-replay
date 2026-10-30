from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_entry_control_flow import branch,compare_flow
from compare_client_functions import normalized

def body(*items):return struct.pack('<'+'I'*len(items),*items)

class ControlFlowTests(unittest.TestCase):
    def test_normalized_equality_cannot_hide_an_internal_jump_change(self):
        a=body(0x14000001,0xd503201f,0xd65f03c0)
        b=body(0x14000002,0xd503201f,0xd65f03c0)
        self.assertEqual(normalized(a),normalized(b))
        self.assertEqual(compare_flow(a,b,0x1000,0x2000,{})['state'],'mismatch')

    def test_known_callee_must_follow_its_own_mapping(self):
        a=body(0x94000400);b=body(0x94000800)
        self.assertEqual(compare_flow(a,b,0x1000,0x3000,{0x2000:0x5000})['known_calls'],1)
        self.assertEqual(compare_flow(a,b,0x1000,0x3000,{0x2000:0x6000})['state'],'mismatch')

    def test_backward_conditional_test_and_compare_branches(self):
        for word in [0x54ffffe0,0x34ffffe0,0x36ffffe0]:
            self.assertEqual(branch(word,0x1004)[1],0x1000)

    def test_unresolved_call_is_retained_and_cannot_authorize_execution(self):
        r=compare_flow(body(0x94000400),body(0x94000800),0x1000,0x3000,{})
        self.assertEqual(len(r['unresolved_external_calls']),1)
        self.assertFalse(r['native_execution_allowed'])

    def test_different_length_is_not_aligned_by_old_offsets(self):
        r=compare_flow(body(0xd65f03c0),body(0xd503201f,0xd65f03c0),0x1000,0x2000,{})
        self.assertFalse(r['checked'])

if __name__=='__main__':unittest.main()
