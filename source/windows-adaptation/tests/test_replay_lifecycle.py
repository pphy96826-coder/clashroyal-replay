import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch
CORE=Path(__file__).resolve().parents[1]/'project/official-web-replay'
sys.path.insert(0,str(CORE))
from replay_lifecycle import client_generation,ClientUnavailable
from desktop_worker import Worker
from console_backend import Player

class LifecycleTests(unittest.TestCase):
    def test_reused_pid_does_not_inherit_replay(self):
        identity=dict(serial='127.0.0.1:16384',pid=123,process_start_time='old')
        stat='123 (game) '+' '.join(['S']*19+['new'])
        with (patch('replay_lifecycle.subprocess.run',return_value=types.SimpleNamespace(returncode=0,stdout='123')),
             patch('replay_lifecycle.subprocess.check_output',return_value=stat)):
            self.assertEqual(client_generation(identity),'replaced')

    def worker(self):
        with patch('desktop_worker.Player') as player:
            worker=Worker();worker.emit=Mock();worker.last_request=dict(command='play',html='sample.html',speed=1)
            worker.playback=dict(attempt='scene-v1',duration=10);worker.player.active='scene-v1'
            return worker

    def test_forced_exit_clears_state_without_restarting_client(self):
        worker=self.worker()
        with patch('console_backend.read_json',return_value=dict(identity={})),patch('desktop_worker.client_generation',return_value='closed'),patch('desktop_worker.owned_scene_state') as observe:
            worker.poll_playback()
        self.assertIsNone(worker.playback);self.assertIsNone(worker.player.active)
        worker.player.stop_owned.assert_not_called();observe.assert_not_called()
        self.assertEqual(worker.emit.call_args.args[0],'playback_ended')

    def test_completion_refreshes_client_and_exposes_replay_choice(self):
        worker=self.worker();worker.finish(worker.playback)
        worker.player.stop_owned.assert_called_once();self.assertIsNone(worker.playback)
        event,value=worker.emit.call_args.args
        self.assertEqual(event,'playback_ended');self.assertTrue(value['can_replay']);self.assertTrue(value['client_refreshed'])

    def test_replay_reuses_last_file_and_speed(self):
        worker=self.worker();worker.launch=lambda action:action()
        worker.command(dict(command='replay'))
        worker.player.play.assert_called_once_with('sample.html',1)

    def test_exit_without_owned_scene_is_immediately_idle(self):
        worker=self.worker();worker.player.active=None;worker.player.discover_owned.return_value=None
        worker.launch=lambda action:action();worker.command(dict(command='exit'))
        self.assertIsNone(worker.last_request);self.assertIsNone(worker.playback)
        worker.player.stop_owned.assert_not_called()

    def test_native_helper_wait_ends_when_target_generation_is_gone(self):
        with tempfile.TemporaryDirectory() as folder,patch('console_backend.read_json',return_value=dict(identity={'pid':123})),patch('console_backend.subprocess.Popen') as popen,patch('console_backend.subprocess.run'),patch('console_backend.client_generation',return_value='closed'),patch('console_backend.time.sleep'):
            player=Player();player.folder=Path(folder);player.active='scene-v1';popen.return_value.poll.return_value=None
            with self.assertRaises(ClientUnavailable):player.command('run_bootstrap_probe.py','--attempt','scene-v1',native=True)
            self.assertIsNone(player.active)

if __name__=='__main__':unittest.main()
