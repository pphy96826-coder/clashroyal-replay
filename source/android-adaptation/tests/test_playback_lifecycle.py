"""Lifecycle regression tests; /proc, native calls and Android are mocked."""
import ast
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import traceback
import struct
import hashlib
import time
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'device/device_playback.py').read_text()
TREE=ast.parse(SOURCE)

def load(name,scope):
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'lifecycle', 'exec'),scope)
    return scope[name]

class LifecycleTests(unittest.TestCase):
    def preparation_case(self,*,modern=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        files=Path(temporary.name)/'files';directory=files/'local-imports/job/result/phone-playback';directory.mkdir(parents=True)
        (files/'phone-active.json').write_text(json.dumps(dict(directory=str(directory),source_sha256='a'*64)))
        state=dict(state='failed_before_native' if modern else 'needs_review')
        if modern:state['native_entry_started']=False
        (directory/'status.json').write_text(json.dumps(state))
        (directory/'error.txt').write_text("metadata(source,preparation,Path(request['apk']))\nprepare_native_replay.py\nValueError: 当前已验证天梯配置需要明确的16级塔楼；不会猜测国王塔等级\n")
        action=directory/str(uuid.uuid4());action.mkdir()
        def write_new(path,value):
            with path.open('x') as stream:json.dump(value,stream)
        scope=dict(Path=Path,uuid=uuid,fcntl=fcntl,hashlib=hashlib,time=time,os=Mock(),
                   read=lambda p:json.loads(p.read_text()),write_new=write_new)
        return load('release_preparation',scope),files,directory,action/'preparation-release'

    def test_legacy_metadata_failure_can_release_without_game_calls(self):
        release,files,directory,out=self.preparation_case()
        before=(directory/'status.json').read_bytes()
        release(directory,out,Path('/unused'))
        receipt=json.loads((directory/'preparation-release.json').read_text())
        self.assertTrue(receipt['native_not_entered']);self.assertTrue(receipt['legacy_metadata_failure'])
        self.assertEqual(before,(directory/'status.json').read_bytes())
        self.assertEqual(receipt['status_sha256'],hashlib.sha256(before).hexdigest())

    def test_new_pre_native_failure_requires_explicit_false_and_lock(self):
        release,files,directory,out=self.preparation_case(modern=True)
        (directory/'error.txt').unlink()
        with (files/'phone-operation.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):release(directory,out,Path('/unused'))
        release(directory,out,Path('/unused'))

    def test_missing_pid_or_unknown_error_does_not_prove_release(self):
        release,files,directory,out=self.preparation_case()
        (directory/'error.txt').write_text('unknown failure')
        with self.assertRaises(RuntimeError):release(directory,out,Path('/unused'))
        self.assertFalse((directory/'preparation-release.json').exists())

    def test_native_artifacts_block_preparation_release(self):
        for artifact in ('native-entry.json','bootstrap-v2-binding.json','bootstrap-v2-build'):
            release,files,directory,out=self.preparation_case()
            (directory/artifact).touch()
            with self.assertRaises(RuntimeError):release(directory,out,Path('/unused'))

    def test_modern_compile_failure_can_release_before_durable_native_entry(self):
        release,files,directory,out=self.preparation_case(modern=True)
        (directory/'bootstrap-v2-build').mkdir()
        release(directory,out,Path('/unused'))
        self.assertTrue((directory/'preparation-release.json').is_file())

    def test_foreign_active_preparation_is_not_released(self):
        release,files,directory,out=self.preparation_case()
        (files/'phone-active.json').write_text(json.dumps(dict(directory='/other',source_sha256='a'*64)))
        with self.assertRaises(ValueError):release(directory,out,Path('/unused'))

    def test_generation_exit_not_read_error(self):
        path=Mock();scope={'Path':Mock(return_value=path),'start_time':lambda s:s}
        path.__truediv__=Mock(return_value=path)
        check=load('generation_released',scope)
        identity=dict(pid=123,process_start_time='42')
        path.read_text.return_value='42';self.assertFalse(check(identity))
        path.read_text.return_value='43';self.assertTrue(check(identity))
        path.read_text.side_effect=FileNotFoundError;self.assertTrue(check(identity))
        path.read_text.side_effect=PermissionError
        with self.assertRaises(PermissionError):check(identity)

    def test_invalid_pid_cannot_be_a_proc_path(self):
        check=load('generation_released',{'Path':Mock(),'start_time':Mock()})
        for pid in (0,-1,'../x',1<<22):
            with self.assertRaises(ValueError):check(dict(pid=pid,process_start_time='42'))

    def finish_case(self,*,gone=False,proof=True):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        files=Path(temporary.name)/'files';directory=files/'local-imports/job/result/phone-playback';directory.mkdir(parents=True)
        binding=directory/'scene-v1-binding.json'
        data={files/'phone-active.json':dict(directory=str(directory),source_sha256='a'*64),
              binding:dict(identity=dict(pid=123,process_start_time='42')),
              directory/'scene-v1-terminal-result.json':dict(battle_terminal=proof,scene_state=dict(tick=6208),local_driver=dict(terminal_tick=6208)),
              directory/'scene-v1-result.json':dict(fields=[0]*28),directory/'scene-v1-component.json':dict(device_path='/owned/component')}
        for path,value in data.items():path.write_text(json.dumps(value))
        stop=Mock()
        scope=dict(Path=Path,uuid=uuid,traceback=traceback,read=lambda p:json.loads(p.read_text()),checked_receipt=Mock(),generation_released=Mock(return_value=gone),
                   stop_owned=stop,fcntl=fcntl,os=Mock(),write_new=lambda p,v:p.write_text(json.dumps(v)))
        action=directory/str(uuid.uuid4());action.mkdir()
        return load('finish_completed',scope),binding,action/'phone-finish',stop

    def test_explicit_exit_only_stops_owned_scene_no_reopen(self):
        finish,binding,out,stop=self.finish_case()
        finish(binding,out,Path('/prefix'))
        stop.assert_called_once();self.assertEqual(stop.call_args.kwargs,{'reopen':False})
        self.assertTrue(stop.call_args.args[1]['battle_terminal'])
        self.assertTrue(json.loads((out/'result.json').read_text())['generation_released'])

    def test_already_killed_does_not_stop_new_game(self):
        finish,binding,out,stop=self.finish_case(gone=True)
        finish(binding,out,Path('/prefix'));stop.assert_not_called()

    def test_incomplete_match_cannot_enter_terminal_cleanup(self):
        finish,binding,out,stop=self.finish_case(proof=False)
        with self.assertRaises(RuntimeError):finish(binding,out,Path('/prefix'))
        stop.assert_not_called()

    def test_repeat_cleanup_is_not_republished(self):
        finish,binding,out,stop=self.finish_case()
        finish(binding,out,Path('/prefix'))
        with self.assertRaises(FileExistsError):finish(binding,out,Path('/prefix'))
        self.assertEqual(stop.call_count,1)

    def test_foreign_job_is_not_touched(self):
        finish,binding,out,stop=self.finish_case()
        active=next(p for p in binding.parents if p.name=='files')/'phone-active.json'
        active.write_text(json.dumps(dict(directory='/other',source_sha256='b'*64)))
        with self.assertRaises(ValueError):finish(binding,out,Path('/prefix'))
        stop.assert_not_called()

    def test_terminal_returns_once_and_replay_is_user_action(self):
        service=(ROOT/'app/src/local/royale/replay/android/PlaybackService.java').read_text()
        self.assertIn('PlaybackStatus.completedVerified(status.getParentFile(),state)',service)
        self.assertIn('id+"-returned.json"',service)
        self.assertIn('if(!returned.exists())',service)
        terminal=SOURCE[SOURCE.index('completed=True'):SOURCE.index("if context['playback_started']:")]
        self.assertIn('monitor_active=False',terminal)
        self.assertEqual(terminal.count('stop_owned(identity,terminal,'),1)
        self.assertIn('reopen=True',terminal)
        self.assertNotIn("action='return-lobby'",terminal)
        self.assertIn('seamless=False',terminal)
        main=(ROOT/'app/src/local/royale/replay/android/MainActivity.java').read_text()
        self.assertIn('input.html',main)
        self.assertIn('sha(source).equals(state.optString("source_sha256"',main)
        self.assertIn('NativePython.finishCompleted',main)

    def test_diagnostic_bundle_is_local_hash_and_source_bound(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        files=Path(temporary.name);queue=files/'replay-queue';queue.mkdir()
        path=queue/'test.diagnostic.json'
        proof=dict(user_authorized=True,source_sha256='a'*64,preparation=dict(source_sha256='a'*64))
        path.write_text(json.dumps(proof));raw=path.read_bytes()
        request=dict(diagnostic_prefix=str(path),diagnostic_sha256=hashlib.sha256(raw).hexdigest(),source_sha256='a'*64)
        check=load('diagnostic_bundle',dict(Path=Path,json=json,hashlib=hashlib))
        self.assertEqual(check(request,files),proof)
        with self.assertRaises(ValueError):check(dict(request,source_sha256='b'*64),files)
        path.write_text('{}')
        with self.assertRaises(ValueError):check(request,files)

    def test_diagnostic_never_claims_completion_or_enters_auto_return(self):
        self.assertIn('diagnostic_prefix_verified=True,complete_replay_verified=False',SOURCE)
        start=SOURCE.index("if diagnostic is not None:",SOURCE.index("if current['tick']>=full['native_terminal_tick']:"))
        block=SOURCE[start:SOURCE.index("terminal=debugger.run",start)]
        self.assertIn("status('diagnostic_ready'",block)
        self.assertIn('continue',block)
        self.assertNotIn('stop_owned',block)
        self.assertNotIn("status('complete'",block)

    def stop_scope(self,*,terminal=True,lobby=True,component=True):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        proc=Path(temporary.name);(proc/'status').write_text('TracerPid:\t0\n')
        session=Mock(base=1,proc=proc)
        session.verify.return_value='1000-2000 r-xp 0 0 0 /owned/component' if component else ''
        process=Mock()
        def require(value):
            if not value:raise ValueError('foreign battle')
        scope=dict(ReadOnlySession=Mock(return_value=session),live_scene=Mock(return_value=dict(controller=999,domain=500)),
                   checked_receipt=Mock(),require_idle_lobby=require,scene_state=Mock(return_value=lobby),
                   struct=struct,subprocess=process,generation_released=Mock(return_value=True))
        scene=dict(fields=[0]*28,battle_terminal=terminal);scene['fields'][27]=123
        return load('stop_owned',scope),scene,process

    def test_verified_terminal_back_in_idle_lobby_can_exit(self):
        stop,scene,process=self.stop_scope()
        stop({},scene,'/owned/component',reopen=False)
        process.run.assert_called_once()
        self.assertIn('force-stop',process.run.call_args.args[0])

    def test_foreign_battle_is_not_closed_even_with_terminal_history(self):
        stop,scene,process=self.stop_scope(lobby=False)
        with self.assertRaises(ValueError):stop({},scene,'/owned/component',reopen=False)
        process.run.assert_not_called()

    def test_changed_controller_without_terminal_is_not_closed(self):
        stop,scene,process=self.stop_scope(terminal=False)
        with self.assertRaises(RuntimeError):stop({},scene,'/owned/component',reopen=False)
        process.run.assert_not_called()

    def test_missing_owned_component_is_not_closed(self):
        stop,scene,process=self.stop_scope(component=False)
        with self.assertRaises(RuntimeError):stop({},scene,'/owned/component',reopen=False)
        process.run.assert_not_called()

if __name__=='__main__':unittest.main()
