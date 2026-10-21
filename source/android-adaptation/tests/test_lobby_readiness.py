"""Foreground is not readiness. These tests never contact a game/device."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'device/device_playback.py').read_text())


class LobbyReadinessTests(unittest.TestCase):
    def run_wait(self,states,foreground=None,cancel_at=None,timeout=8):
        class Clock:
            now=0
            def monotonic(self):return self.now
            def sleep(self,seconds):self.now+=seconds
        clock=Clock();reads=[];progress=[]
        def scene(identity):
            reads.append(clock.now)
            value=states[min(int(clock.now),len(states)-1)]
            if isinstance(value,Exception):raise value
            return value
        def required(state):
            if state!='idle':raise ValueError('not the strict lobby')
        def cancellation():
            if clock.now==cancel_at:raise RuntimeError('user cancelled')
        class Cancelled(Exception):pass
        class SceneSnapshotChanged(ValueError):pass
        scope=dict(time=clock,scene_state=scene,require_idle_lobby=required,Cancelled=Cancelled,
                   SceneSnapshotChanged=SceneSnapshotChanged,
                   game_foreground=lambda:True if foreground is None else foreground[min(int(clock.now),len(foreground)-1)])
        node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='wait_idle_lobby')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'lobby-test','exec'),scope)
        scope['wait_idle_lobby']({},progress=lambda *args:progress.append(args),cancellation=cancellation,timeout=timeout)
        return clock.now,reads,progress

    def test_loading_activity_is_not_idle_lobby(self):
        now,reads,progress=self.run_wait(['loading','loading','idle'])
        self.assertEqual(now,4)
        self.assertEqual(reads,[0,1,2,3,4])
        self.assertTrue(all(p[0]=='waiting_lobby' for p in progress))

    def test_preparation_pause_survives_two_minutes_and_resumes_same_wait(self):
        now,_,_=self.run_wait(['idle'],foreground=[False]*130+[True]*3,timeout=None)
        self.assertEqual(now,132)

    def test_unbounded_preparation_pause_is_still_user_cancellable(self):
        with self.assertRaisesRegex(RuntimeError,'user cancelled'):
            self.run_wait(['idle'],foreground=[False],cancel_at=130,timeout=None)

    def test_foreground_loss_resets_stability(self):
        now,_,_=self.run_wait(['idle'],[True,False,True,True,True])
        self.assertEqual(now,4)

    def test_loading_return_resets_stability(self):
        now,_,_=self.run_wait(['idle','loading','idle'])
        self.assertEqual(now,4)

    def test_foreign_battle_never_passes(self):
        with self.assertRaisesRegex(Exception,'scene was not published'):self.run_wait(['battle'])

    def test_identity_read_error_is_not_retried(self):
        with self.assertRaisesRegex(ValueError,'generation changed'):self.run_wait([ValueError('generation changed')])

    def test_user_can_cancel_before_scene(self):
        with self.assertRaisesRegex(RuntimeError,'user cancelled'):self.run_wait(['loading'],cancel_at=1)

    def test_native_guard_remains_and_wait_is_before_only_attempt(self):
        source=(ROOT/'device/device_playback.py').read_text()
        self.assertLess(source.index('wait_idle_lobby(identity,progress=status'),source.index("scene=probe('scene-v1'"))
        self.assertEqual(source.count("scene=probe('scene-v1'"),1)

    def test_unknown_controller_has_no_battle_field_reads(self):
        source=(ROOT/'device/device_runtime.py').read_text()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='scene_state')
        class Session:
            base=0x100000
            def __init__(self,identity):pass
            def pointer(self,address):
                return {self.base+0x1d46bd0:0x2000,0x2028:0x3000,0x3000:self.base+0x1bec9f0}[address]
            def read(self,*args):raise AssertionError('typed field read from unknown controller')
            def verify(self):pass
        scope=dict(ReadOnlySession=Session)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'snapshot-test','exec'),scope)
        self.assertEqual(scope['scene_state']({}),dict(controller_present=True,controller_vtable_va='0x1bec9f0'))


if __name__=='__main__':unittest.main()
