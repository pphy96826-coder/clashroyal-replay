"""Host-independent tests. A mock Windows API is not Windows execution proof."""
import ast
import errno
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/'project/official-web-replay'
sys.path[:0]=[str(CORE),str(ROOT/'project/vendor')]
import portable_config as cfg
import platform_lock
from windows_doctor import validate_device_abi,inspect
from windows_console import play_request,WorkerClient
from client_session import current_device_binding,validate_device_binding


class WindowsPortTests(unittest.TestCase):
    def test_every_python_source_parses(self):
        for file in (ROOT/'project').rglob('*.py'):ast.parse(file.read_text(encoding='utf-8'),str(file))

    def test_core_import_without_direct_fcntl_dependency(self):
        import console_backend,desktop_worker,build_bootstrap_probe,deploy_bootstrap_probe,bounded_memory_reader,prepare_runtime
        self.assertEqual(console_backend.fcntl.__name__,'platform_lock')
        self.assertEqual(desktop_worker.fcntl.__name__,'platform_lock')
        self.assertEqual(len(console_backend.recipe_digest()),64)

    def test_compiler_windows_uses_exe_no_shell_wrapper(self):
        with patch.object(cfg,'ndk_bin',return_value=Path('/ndk bin')):
            command=cfg.compiler_command('Windows')
        self.assertTrue(command[0].endswith('clang++.exe'));self.assertIn('--target=aarch64-linux-android24',command)
        self.assertFalse(any(v.endswith('.cmd') for v in command))

    def test_windows_user_directory(self):
        with patch.object(cfg,'windows',return_value=True),patch.dict(os.environ,{'LOCALAPPDATA':'C:/PrivateProfile/AppData/Local'}):
            self.assertEqual(str(cfg.local_data()).replace('\\','/'),'C:/PrivateProfile/AppData/Local')

    def test_missing_windows_private_directory_rejected(self):
        with patch.object(cfg,'windows',return_value=True),patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):cfg.local_data()

    def test_arm_translation_not_silently_accepted(self):
        validate_device_abi('arm64-v8a')
        for abi in ('x86_64','x86','armeabi-v7a','',None):
            with self.assertRaises(ValueError):validate_device_abi(abi)

    def test_filelock_windows_byte_initialized_and_locked(self):
        fake=types.SimpleNamespace(LK_NBLCK=2,locking=Mock())
        with tempfile.TemporaryFile('w+b') as file:
            with patch.object(platform_lock,'os',types.SimpleNamespace(name='nt',fstat=os.fstat)),patch.dict(sys.modules,{'msvcrt':fake}):
                platform_lock.flock(file,platform_lock.LOCK_EX|platform_lock.LOCK_NB)
            fake.locking.assert_called_once_with(file.fileno(),2,1)
            file.seek(0);self.assertEqual(file.read(),b'\0')

    def test_windows_lock_contention_not_ignored(self):
        fake=types.SimpleNamespace(LK_NBLCK=2,locking=Mock(side_effect=OSError(errno.EACCES,'busy')))
        with tempfile.TemporaryFile('w+b') as file:
            with patch.object(platform_lock,'os',types.SimpleNamespace(name='nt',fstat=os.fstat)),patch.dict(sys.modules,{'msvcrt':fake}):
                with self.assertRaises(BlockingIOError):platform_lock.flock(file,6)

    def test_native_file_lock_excludes_other_process(self):
        with tempfile.TemporaryDirectory(prefix='锁 test ') as directory:
            path=Path(directory)/'lock'
            with path.open('a+b') as held:
                platform_lock.flock(held,6)
                code='import sys;sys.path.insert(0,sys.argv[1]);import platform_lock;p=open(sys.argv[2],"a+b")\ntry:platform_lock.flock(p,6)\nexcept BlockingIOError:sys.exit(0)\nelse:sys.exit(7)'
                result=subprocess.run([sys.executable,'-X','utf8','-c',code,str(CORE),str(path)],timeout=10)
                self.assertEqual(result.returncode,0)

    def test_selected_port_reloads_and_old_identity_rejected(self):
        with tempfile.TemporaryDirectory(prefix='绑定 test ') as directory:
            folder=Path(directory);selected=folder/'device.json';config=folder/'deploy-config.json'
            config.write_text(json.dumps(dict(device_binding_file=str(selected),instance_name='安卓一')),encoding='utf-8')
            def save(port):selected.write_text(json.dumps(dict(schema='royale-replay.local-binding.v1',vmName='安卓一',adbPort=port)),encoding='utf-8')
            with patch.object(cfg,'CONFIG',config):
                save(16000);first=current_device_binding();identity=dict(serial=first['serial'],device_binding=first)
                save(16001);self.assertEqual(current_device_binding()['serial'],'127.0.0.1:16001')
                with self.assertRaises(ValueError):validate_device_binding(identity)

    def test_bad_binding_rejected(self):
        from adb_discovery import checked_binding
        for serial in ('8.8.8.8:16000','localhost:16000','127.0.0.1:16001'):
            with self.assertRaises(ValueError):checked_binding(dict(instance_name='test',adb_port=16000,serial=serial))

    def test_request_retains_unicode_and_speed(self):
        with tempfile.TemporaryDirectory(prefix='回放 path ') as directory:
            path=Path(directory)/'对局.html';path.write_text('<html/>',encoding='utf-8')
            doc=play_request(str(path),'0.5');self.assertEqual(doc['speed'],.5);self.assertEqual(doc['html'],str(path.resolve()))
            with self.assertRaises(ValueError):play_request(str(path),'3')

    def test_client_shutdown_does_not_kill_native_task(self):
        client=WorkerClient(Mock());client.process=Mock();client.process.poll.return_value=None
        client.shutdown();client.process.kill.assert_not_called();client.process.terminate.assert_not_called()
        self.assertIn('shutdown',client.process.stdin.write.call_args.args[0])

    def test_global_delay_is_still_twenty_ticks(self):
        from timing_policy import offset_for
        self.assertEqual(offset_for('NEW-UNKNOWN-REPLAY'),20)

    def test_mac_doctor_does_not_claim_windows_or_contact_device(self):
        with tempfile.TemporaryDirectory() as directory,patch('windows_doctor.platform.system',return_value='Darwin'),patch('windows_doctor.subprocess.run') as execute:
            report=inspect(Path(directory)/'missing.json')
            self.assertFalse(report['host_ready']);self.assertFalse(report['playback_verified']);self.assertFalse(report['device_contacted'])
            execute.assert_not_called()

    def test_lldb_windows_probe_requires_python_and_android_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);lldb=folder/'lldb.exe';lldb.touch();config=folder/'deploy-config.json'
            config.write_text(json.dumps(dict(lldb_path=str(lldb))),encoding='utf-8')
            with patch('windows_doctor.platform.system',return_value='Windows'),patch('windows_doctor.platform.machine',return_value='AMD64'):
                with patch('windows_doctor.subprocess.run',return_value=types.SimpleNamespace(returncode=0,stdout='RR_PY_OK_v1 remote-android')):
                    self.assertTrue(inspect(config)['checks']['lldb_python_android'])
                with patch('windows_doctor.subprocess.run',return_value=types.SimpleNamespace(returncode=0,stdout='error: Python not supported')):
                    self.assertFalse(inspect(config)['checks']['lldb_python_android'])


if __name__=='__main__':unittest.main()
