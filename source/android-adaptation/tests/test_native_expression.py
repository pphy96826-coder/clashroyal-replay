"""Native expression context regression; synthetic SB API, never a game."""
import importlib.util
import ast
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

SHARED=ROOT.parent/'official-web-replay'
if not SHARED.is_dir():SHARED=ROOT.parent/'windows-adaptation/project/official-web-replay'
native=module('device_expression_test',ROOT/'device/device_expression.py')
evaluate=native.evaluate
explain=module('failure_recovery_test',SHARED/'failure_recovery.py').explanation


class NativeExpressionTests(unittest.TestCase):
    def case(self):
        api=Mock(eStateStopped=5,eLanguageTypeC=2)
        process=Mock();process.IsValid.return_value=True;process.GetProcessID.return_value=42;process.GetState.return_value=5
        target=Mock();target.GetProcess.return_value=process;target.GetAddressByteSize.return_value=8;target.GetTriple.return_value='aarch64-linux-android'
        thread=process.GetThreadByID.return_value;thread.IsValid.return_value=True;thread.GetThreadID.return_value=42
        frame=thread.GetFrameAtIndex.return_value;frame.IsValid.return_value=True;frame.GetThread.return_value=thread;frame.GetPC.return_value=0x1234
        value=frame.EvaluateExpression.return_value;value.GetError.return_value.Success.return_value=True;value.GetValueAsUnsigned.return_value=44
        return api,target,process,frame

    def test_frame_context_is_used_exactly_once_not_target_fallback(self):
        api,target,process,frame=self.case();evidence={}
        self.assertEqual(evaluate(api,target,process,42,'test()',evidence=evidence),44)
        frame.EvaluateExpression.assert_called_once();target.EvaluateExpression.assert_not_called()
        self.assertTrue(evidence['native_call_completed']);self.assertEqual(evidence['frame_pc'],'0x1234')
        api.SBExpressionOptions.return_value.SetAllowJIT.assert_called_once_with(True)

    def test_non_stopped_process_is_not_resumed_or_called(self):
        api,target,process,frame=self.case();process.GetState.return_value=6
        with self.assertRaisesRegex(RuntimeError,'stopped process'):evaluate(api,target,process,42,'test()')
        frame.EvaluateExpression.assert_not_called();process.Continue.assert_not_called()

    def test_wrong_pid_or_target_or_word_size_cannot_execute(self):
        for field in ('pid','target','bits'):
            api,target,process,frame=self.case()
            if field=='pid':process.GetProcessID.return_value=43
            elif field=='target':target.GetProcess.return_value=Mock(GetProcessID=Mock(return_value=43))
            else:target.GetAddressByteSize.return_value=4
            with self.assertRaises(RuntimeError):evaluate(api,target,process,42,'test()')
            frame.EvaluateExpression.assert_not_called()

    def test_missing_or_foreign_frame_and_unselectable_thread_fail_closed(self):
        for field in ('missing','foreign','selection','thread'):
            api,target,process,frame=self.case()
            if field=='missing':frame.IsValid.return_value=False
            elif field=='foreign':frame.GetThread.return_value=Mock(GetThreadID=Mock(return_value=43))
            elif field=='thread':process.GetThreadByID.return_value.GetThreadID.return_value=43
            else:process.SetSelectedThread.return_value=False
            with self.assertRaises(RuntimeError):evaluate(api,target,process,42,'test()')
            frame.EvaluateExpression.assert_not_called();target.EvaluateExpression.assert_not_called()

    def test_original_interpreter_error_is_retained_without_retry(self):
        api,target,process,frame=self.case();evidence={}
        error=frame.EvaluateExpression.return_value.GetError.return_value
        error.Success.return_value=False
        error.__str__=Mock(return_value="Can't evaluate the expression without a running target due to: Interpreter doesn't handle one of the expression's opcodes")
        with self.assertRaisesRegex(RuntimeError,'native expression failed'):evaluate(api,target,process,42,'test()',evidence=evidence)
        frame.EvaluateExpression.assert_called_once();target.EvaluateExpression.assert_not_called()
        self.assertFalse(evidence['native_call_completed']);self.assertTrue(evidence['execution_unavailable'])

    def test_stop_others_policy_is_preserved(self):
        api,target,process,frame=self.case();evaluate(api,target,process,42,'test()',stop_others=False)
        api.SBExpressionOptions.return_value.SetStopOthers.assert_called_once_with(False)

    def test_interpreter_handle_is_not_hand_or_ability_error(self):
        for error in ("Interpreter doesn't handle one of the expression's opcodes",'native expression requires a stopped process','no JIT compiled function'):
            self.assertIn('本机调试器无法执行原生函数',explain(error))
        for error in ('loader handle absent','owned_loader_handle missing','deal-check path only','handler failed'):
            self.assertNotIn('实际手牌',explain(error))

    def test_real_deal_failure_remains_a_deal_failure(self):
        for error in ('native deal mismatch','card-unavailable','hand mismatch','原生牌序有界校准未通过'):
            self.assertIn('实际手牌',explain(error))

    def test_only_exact_unpublished_interpreter_refusal_is_a_release_candidate(self):
        receipt=dict(initialization_only=True,detached=True,publication=None,errors=[
            "RuntimeError: error: Can't evaluate the expression without a running target due to: Interpreter doesn't handle one of the expression's opcodes"])
        self.assertTrue(native.rejected_before_load(receipt))
        for changes in ({'publication':1},{'detached':False},{'owned_loader_handle':'0x0'},
                        {'fields':[]},{'initialization_only':False},{'errors':['timeout']},
                        {'errors':receipt['errors']+['second error']}):
            self.assertFalse(native.rejected_before_load(dict(receipt,**changes)))
        del receipt['publication'];self.assertFalse(native.rejected_before_load(receipt))

    def test_all_android_native_calls_bind_frames(self):
        self.assertIn('evaluate(lldb,target,process', (ROOT/'device/phone_bootstrap_gate.py').read_text())
        self.assertIn('evaluate(lldb,target,process', (ROOT/'device/device_tools.py').read_text())
        scene=(SHARED/'run_scene_gate.py').read_text()
        self.assertIn('frame.EvaluateExpression(',scene)
        self.assertNotIn('target.EvaluateExpression(',scene)

    def recovery_case(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        directory=Path(temporary.name);(directory/'status').write_text('TracerPid:\t0\n')
        receipt=dict(initialization_only=True,detached=True,publication=None,errors=[
            "RuntimeError: Can't evaluate the expression without a running target due to: Interpreter doesn't handle one of the expression's opcodes"])
        identity={'pid':42,'process_start_time':'123'}
        session=Mock();session.verify.return_value='';session.proc=directory
        records={'test-binding.json':{'identity':identity},'test-result.json':receipt,
                 'test-component.json':{'device_path':'/data/local/tmp/own/libphone_replay_bootstrap.so'}}
        scope=dict(read=lambda p:records[p.name],generation_released=Mock(return_value=False),
                   ReadOnlySession=Mock(return_value=session),require_idle_lobby=Mock(),scene_state=Mock(),
                   subprocess=Mock(),stop_owned=Mock())
        tree=ast.parse((ROOT/'device/device_playback.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='recover_failed_attempt')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'recovery-test','exec'),scope)
        return directory,identity,receipt,session,scope

    def test_unloaded_parse_refusal_releases_without_killing_or_loading(self):
        directory,identity,receipt,session,scope=self.recovery_case()
        with patch.dict(sys.modules,device_expression=native):
            self.assertEqual(scope['recover_failed_attempt'](directory,'test',identity),'already_clean')
        scope['subprocess'].run.assert_not_called();scope['stop_owned'].assert_not_called()
        scope['require_idle_lobby'].assert_called_once();self.assertEqual(session.verify.call_count,2)

    def test_parse_refusal_cannot_release_other_component_or_active_debugger(self):
        for kind in ('other','tracer','lobby','permission','unknown'):
            directory,identity,receipt,session,scope=self.recovery_case()
            if kind=='other':session.verify.return_value='unrelated libphone_replay_scene.so'
            elif kind=='tracer':(directory/'status').write_text('TracerPid:\t999\n')
            elif kind=='lobby':scope['require_idle_lobby'].side_effect=ValueError('not idle')
            elif kind=='permission':session.verify.side_effect=PermissionError('no read')
            else:receipt['errors']=['generic failed call']
            with patch.dict(sys.modules,device_expression=native):
                with self.assertRaises((RuntimeError,ValueError,PermissionError)):
                    scope['recover_failed_attempt'](directory,'test',identity)
            scope['subprocess'].run.assert_not_called();scope['stop_owned'].assert_not_called()


if __name__=='__main__':unittest.main()
