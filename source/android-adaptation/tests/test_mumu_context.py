from pathlib import Path
import sys,unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'device'))
from mumu_context import ready,HOST_LIBC

class ContextTests(unittest.TestCase):
 def setUp(self):
  self.lldb=Mock(eStateStopped=5,eStopReasonSignal=5)
  self.process=Mock();self.process.GetProcessID.return_value=123;self.process.GetState.return_value=5
  self.thread=self.process.GetThreadByID.return_value;self.thread.GetThreadID.return_value=123
  self.thread.GetStopReason.return_value=5;self.thread.GetStopReasonDataCount.return_value=1
  self.thread.GetStopReasonDataAtIndex.return_value=19
  self.frame=self.thread.GetFrameAtIndex.return_value;self.frame.GetPC.return_value=0x1102
  self.process.ReadMemory.return_value=b'\x0f\x05'
  self.maps='1000-2000 r-xp 00000000 00:00 1 '+HOST_LIBC
 def test_verified_host_syscall_wait_is_accepted(self):
  self.assertTrue(ready(self.lldb,self.process,123,self.maps)[0]);self.process.ReadMemory.assert_called_once()
 def test_translator_or_anonymous_pc_never_runs_an_expression(self):
  for maps in ('1000-2000 rwxp 0 00:00 0','1000-2000 r-xp 0 00:00 1 /system/lib64/libhoudini.so'):
   self.assertFalse(ready(self.lldb,self.process,123,maps)[0])
  self.process.ReadMemory.assert_not_called();self.frame.EvaluateExpression.assert_not_called()
 def test_host_mapping_without_syscall_wait_is_rejected(self):
  self.process.ReadMemory.return_value=b'\x90\x90';self.assertFalse(ready(self.lldb,self.process,123,self.maps)[0])
 def test_fault_stop_is_not_resumed_or_retried(self):
  self.thread.GetStopReasonDataAtIndex.return_value=11
  with self.assertRaisesRegex(RuntimeError,'never resume'):ready(self.lldb,self.process,123,self.maps)
  self.process.ReadMemory.assert_not_called();self.process.Continue.assert_not_called()
 def test_different_generation_process_id_is_rejected(self):
  self.process.GetProcessID.return_value=456
  with self.assertRaises(RuntimeError):ready(self.lldb,self.process,123,self.maps)
if __name__=='__main__':unittest.main()
