import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('companion', ROOT/'scripts/companion.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class JobContractTests(unittest.TestCase):
    def setUp(self):
        self.identifier = '12345678-abcd-abcd-abcd-123456789abc'
        self.token = 'a'*64
        self.job = dict(schema='royale-replay.android-job.v1', id=self.identifier,
                        token=self.token, command='play', speed=1,
                        created_at=1000, source_sha256='b'*64)

    def check(self):
        return module.checked_job(self.job, self.identifier, self.token, 1000)

    def test_valid(self):
        self.assertIs(self.check(), self.job)

    def test_rejects_stale_and_future(self):
        for timestamp in (99, 1061, float('nan')):
            self.job['created_at'] = timestamp
            with self.assertRaises(ValueError): self.check()

    def test_rejects_other_session(self):
        self.job['token'] = 'c'*64
        with self.assertRaises(ValueError): self.check()

    def test_rejects_noncanonical_id(self):
        self.identifier = '../source'
        self.job['id'] = self.identifier
        with self.assertRaises(ValueError): self.check()

    def test_rejects_invalid_speed(self):
        for speed in (True, 0, -1, 500, float('inf')):
            self.job['speed'] = speed
            with self.assertRaises(ValueError): self.check()

    def test_rejects_missing_hash(self):
        del self.job['source_sha256']
        with self.assertRaises(ValueError): self.check()

    def test_rejects_arbitrary_command(self):
        self.job['command'] = 'shell'
        with self.assertRaises(ValueError): self.check()

    def test_visible_service_and_proxy_gated_browser_permissions(self):
        manifest = (ROOT/'app/AndroidManifest.xml').read_text()
        import re
        self.assertEqual(re.findall(r'<uses-permission android:name="([^"]+)"',manifest),['android.permission.FOREGROUND_SERVICE','android.permission.INTERNET','android.permission.SYSTEM_ALERT_WINDOW'])
        self.assertIn('android:name=".PlaybackService" android:exported="false"',manifest)
        self.assertNotIn('WebView', (ROOT/'app/src/local/royale/replay/android/MainActivity.java').read_text())

    def test_compile_api_not_in_app_source(self):
        self.assertFalse((ROOT/'app/src/android').exists())

    def test_game_must_be_top_resumed_not_merely_listed(self):
        for state, expected in (
            ('topResumedActivity=ActivityRecord{aa u0 '+module.GAME+'/Game t1}', True),
            ('mResumedActivity: ActivityRecord{aa u0 '+module.GAME+'/Game t1}', True),
            ('topResumedActivity=ActivityRecord{aa u0 local.royale.replay.android/.MainActivity t1}\nbackground '+module.GAME+'/Game', False),
            ('', False),
        ):
            with patch.object(module.subprocess, 'check_output', return_value=state):
                self.assertEqual(module.game_foreground(['adb']), expected)

    def test_submit_switches_to_game_and_review_is_not_terminal(self):
        source = (ROOT/'app/src/local/royale/replay/android/PlaybackService.java').read_text()
        self.assertIn('if(game==null)throw new IOException', source)
        self.assertIn('context.startActivity(game.addFlags(0x10000000))',source)
        self.assertIn('NativePython.startPlayback',source)
        self.assertNotIn('recoverInitialization',source)


if __name__ == '__main__': unittest.main()
