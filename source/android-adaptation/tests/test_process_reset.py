from pathlib import Path
import hashlib,importlib.util,json,sys,tempfile,types,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reset_test',ROOT/'device/device_reset.py');reset=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,fcntl=types.SimpleNamespace()):spec.loader.exec_module(reset)

class ResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.files=Path(self.tmp.name)/'files';self.files.mkdir()
        self.home=self.files/'runtime';self.exe=self.home/'app/mumu-support/runtime/bin/phone_runtime';self.exe.parent.mkdir(parents=True);self.exe.write_bytes(b'verified-cli')
        member=self.exe.relative_to(self.home).as_posix();(self.home/'runtime-files.json').write_text(json.dumps({member:hashlib.sha256(self.exe.read_bytes()).hexdigest()}))
        self.argv=[str(self.exe),'play',str(self.home),str(self.files/'request.json'),str(self.files/'output'),str(self.files/'tools')]
    def test_only_fixed_private_verified_cli_is_owned(self):
        self.assertTrue(reset.owned_command(self.argv,self.files))
        args=list(self.argv);args[1]='reset';self.assertFalse(reset.owned_command(args,self.files))
        args=list(self.argv);args[3]='/sdcard/foreign.json';self.assertFalse(reset.owned_command(args,self.files))
        args=list(self.argv);args[0]='/system/bin/phone_runtime';self.assertFalse(reset.owned_command(args,self.files))
    def test_source_parser_with_no_tool_prefix_is_owned(self):
        args=list(self.argv);args[1]='import-source';args[5]='-';self.assertTrue(reset.owned_command(args,self.files))
    def test_changed_executable_is_not_killed(self):
        self.exe.write_bytes(b'changed');self.assertFalse(reset.owned_command(self.argv,self.files))
    def proc(self,pid,start,argv,state='S',parent=1):
        folder=self.files/'proc'/str(pid);folder.mkdir(parents=True,exist_ok=True)
        parts=[state,str(parent)]+['0']*17+[str(start)]
        (folder/'stat').write_text(str(pid)+' (same name) '+' '.join(parts))
        (folder/'cmdline').write_bytes(b'\0'.join(s.encode() for s in argv)+b'\0');return self.files/'proc'
    def test_reused_pid_is_never_signalled(self):
        row=dict(pid=123,start='10',argv=self.argv)
        proc=self.proc(123,11,self.argv);called=[]
        with self.assertRaisesRegex(RuntimeError,'reused'):reset.terminate(row,9,proc,lambda *args:called.append(args))
        self.assertEqual(called,[])
    def test_changed_command_is_never_signalled(self):
        row=dict(pid=123,start='10',argv=self.argv);proc=self.proc(123,10,['foreign'])
        with self.assertRaisesRegex(RuntimeError,'reused'):reset.terminate(row,9,proc,lambda *args:self.fail('foreign kill'))
    def test_owned_generation_can_be_terminated(self):
        row=dict(pid=123,start='10',argv=self.argv);proc=self.proc(123,10,self.argv);called=[]
        self.assertTrue(reset.terminate(row,15,proc,lambda *args:called.append(args)));self.assertEqual(called,[(123,15)])
    def test_zombie_is_already_released(self):
        row=dict(pid=123,start='10',argv=self.argv);proc=self.proc(123,10,[],state='Z')
        self.assertFalse(reset.terminate(row,9,proc,lambda *args:self.fail('zombie kill')))
    def test_foreign_children_are_not_selected(self):
        proc=self.proc(123,10,self.argv)
        self.proc(124,11,['/system/bin/unrelated'],parent=123)
        self.proc(125,12,[str(self.home/'compiler/clang++')],parent=123)
        found=reset.worker_snapshot(self.files,proc)
        self.assertEqual({r['pid'] for r in found},{123,125})
    def test_marker_without_user_authorization_is_refused(self):
        action=self.files/'process-resets/00000000-0000-0000-0000-000000000000';action.mkdir(parents=True)
        request=action/'request.json';payload=dict(schema='royale-replay.reset.v1',id=action.name,user_authorized=False)
        request.write_text(json.dumps(payload));(self.files/'reset-in-progress.json').write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError,'explicit'):reset.perform(request,action/'reset-result',self.files/'tools')
    def test_reset_never_uses_global_name_kills_or_unlinks_the_lease(self):
        code=(ROOT/'device/device_reset.py').read_text()
        self.assertNotIn('killall',code);self.assertNotIn('pkill',code);self.assertNotIn('unlink(',code)
        self.assertLess(code.index("'force-stop'"),code.index('for sig in (signal.SIGTERM'))

if __name__=='__main__':unittest.main()
