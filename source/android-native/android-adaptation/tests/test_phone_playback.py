"""Fail-closed playback gates; no device, debugger or native calls."""
import ast
import threading
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'device/device_playback.py').read_text())
NAMESPACE={}
ast_function=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='checked_receipt')
exec(compile(ast.Module(body=[ast_function],type_ignores=[]),'receipt-test','exec'),NAMESPACE)
check=NAMESPACE['checked_receipt']


class PhonePlaybackGateTests(unittest.TestCase):
    def receipt(self,**changes):
        value=dict(errors=[],detached=True,source_bootstrap_verified=True,component_unloaded=True,
                   private_source_execution_complete=True,native_replay_scene_present=True,local_driver=dict(error=0))
        value.update(changes);return value

    def test_compiled_or_queued_is_not_success(self):
        for result in ({},{'state':'compiled_not_loaded'},{'state':'queued'}):
            with self.assertRaises(RuntimeError):check(result,execute=True)

    def test_errors_or_attached_debugger_block_progress(self):
        for result in (self.receipt(errors=['pending']),self.receipt(detached=False)):
            with self.assertRaises(RuntimeError):check(result,execute=True)

    def test_incomplete_source_cannot_become_scene(self):
        with self.assertRaises(RuntimeError):check(self.receipt(private_source_execution_complete=False),execute=True)

    def test_missing_cleanup_blocks_next_component(self):
        with self.assertRaises(RuntimeError):check(self.receipt(component_unloaded=False))

    def test_loading_is_not_playing(self):
        for result in (self.receipt(native_replay_scene_present=False),self.receipt(local_driver=dict(error=7))):
            with self.assertRaises(RuntimeError):check(result,scene=True)

    def test_complete_receipts_pass(self):
        check(self.receipt(),execute=True);check(self.receipt(),scene=True)

    def test_no_host_transport_or_bypass_commands(self):
        source=(ROOT/'device/device_playback.py').read_text()
        imports={alias.name for node in ast.walk(TREE) if isinstance(node,(ast.Import,ast.ImportFrom)) for alias in node.names}
        self.assertNotIn('socket',imports)
        for command in ('adb forward','adb shell','setenforce','iptables','kill-server','nohup'):
            self.assertNotIn(command,source)
        self.assertIn('fcntl.LOCK_EX|fcntl.LOCK_NB',source)
        self.assertIn('require_idle_lobby',source)
        self.assertIn('roundtrip[\'commands\']!=full[\'native_replay\'][\'cmd\']',source)

    def test_async_process_uses_debuggers_persistent_listener(self):
        source=(ROOT/'device/device_playback.py').read_text()
        self.assertIn('AttachToProcessWithID(self.debugger.GetListener()',source)
        self.assertNotIn("AttachToProcessWithID(lldb.SBListener(",source)

    def test_recovery_has_no_repeat_publication(self):
        source=(ROOT/'device/phone_bootstrap_gate.py').read_text()
        self.assertIn("if original.get('publication')!=1 or not original.get('detached')",source)
        self.assertIn("if struct.unpack('<I',memory(done,4))[0]!=1",source)
        self.assertIn("if not observe_original:\n            public()",source)
        self.assertIn("component remains mapped",source)

    def test_service_is_visible_non_sticky_and_not_exported(self):
        source=(ROOT/'app/src/local/royale/replay/android/PlaybackService.java').read_text()
        self.assertIn('startForeground(21,notification)',source)
        self.assertIn('return START_NOT_STICKY',source)
        self.assertNotIn('START_STICKY',source)

    def test_embedded_event_loop_commits_state_without_resuming(self):
        node=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='EventDebugger')
        scope=dict(threading=threading)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'event-test','exec'),scope)
        class Listener:
            def __init__(self):self.events=[1,2,3];self.delivered=0
            def GetNextEvent(self,event):
                if not self.events:return False
                self.events.pop();self.delivered+=1;return True
        class Core:
            def __init__(self):self.listener=Listener();self.mode=None
            def GetListener(self):return self.listener
            def SetAsync(self,enabled):self.mode=enabled
        class API:
            @staticmethod
            def SBEvent():return object()
        core=Core();debugger=scope['EventDebugger'](core,API)
        debugger.SetAsync(True);debugger.SetAsync(False)
        self.assertEqual(core.listener.delivered,3)
        self.assertFalse(core.mode);self.assertIsNone(debugger.thread)


if __name__=='__main__':unittest.main()
