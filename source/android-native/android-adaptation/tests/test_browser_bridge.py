from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT/'app/src/local/royale/replay/android'


class BrowserBridgeTests(unittest.TestCase):
    def test_pure_java_decoder_and_adversarial_inputs(self):
        javac, java = shutil.which('javac'), shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK is required for executable transport tests')
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([javac, '-encoding', 'UTF-8', '-d', directory,
                            *[str(JAVA/name) for name in ('BrowserPolicy.java', 'ReplaySource.java', 'BrowserImport.java')],
                            str(ROOT/'tests/BrowserImportCheck.java')], check=True, capture_output=True)
            result = subprocess.run([java, '-cp', directory, 'local.royale.replay.android.BrowserImportCheck',
                                     str(ROOT/'app/assets/synthetic.html')], check=True, capture_output=True, text=True)
            self.assertRegex(result.stdout, r'PASS 3[0-9] browser transport checks')
            node = shutil.which('node')
            if node:
                transport = Path(directory)/'transport.txt'
                result = subprocess.run([node, str(ROOT/'tests/browser_bridge_check.cjs'), str(transport)],
                                        check=True, capture_output=True, text=True)
                self.assertIn('PASS 14 offline browser-script checks', result.stdout)
                result = subprocess.run([java, '-cp', directory, 'local.royale.replay.android.BrowserImportCheck',
                                         '--decode', str(transport)], check=True, capture_output=True, text=True)
                self.assertEqual(result.stdout.strip(), 'SYNTHETIC01 4')

    def test_export_is_review_only_and_service_stays_private(self):
        ns = '{http://schemas.android.com/apk/res/android}'
        app = ET.parse(ROOT/'app/AndroidManifest.xml').getroot().find('application')
        review = next(a for a in app.findall('activity') if a.get(ns+'name') == '.BrowserImportActivity')
        self.assertEqual(review.get(ns+'exported'), 'false')
        activity = next(a for a in app.findall('activity') if a.get(ns+'name') == '.BrowserBridgeActivity')
        self.assertEqual(activity.get(ns+'exported'), 'true')
        self.assertEqual(activity.find('intent-filter/data').attrib,
                         {ns+'scheme': 'royalereplay', ns+'host': 'import', ns+'path': '/v1'})
        exported = [a.get(ns+'name') for a in app.findall('activity') if a.get(ns+'exported') == 'true']
        self.assertEqual(sorted(exported), ['.BrowserBridgeActivity', '.MainActivity', '.WebWorkerActivity'])
        web = next(a for a in app.findall('activity') if a.get(ns+'name') == '.WebWorkerActivity')
        self.assertEqual(web.get(ns+'permission'), 'android.permission.DUMP')
        self.assertIsNone(web.find('intent-filter'))  # No browser-accessible unattended URL.
        bridge = (JAVA/'BrowserBridgeActivity.java').read_text()
        self.assertIn('FloatingConsole.offer(BrowserBridgeActivity.this,BrowserImport.decode(link))', bridge)
        for forbidden in ('getStringExtra(', 'getDoubleExtra(', 'getBooleanExtra(', 'PlaybackService', 'NativePython.', 'ConsoleActions', 'ReplayQueue', 'Runtime.getRuntime', 'su'):
            self.assertNotIn(forbidden, bridge.replace('super.', '').replace('Bundle state', ''))
        floating = (JAVA/'FloatingConsole.java').read_text()
        offer = floating[floating.index('static void offer('):floating.index('static boolean finished(')]
        self.assertNotIn('ConsoleActions', offer)  # Receiving never plays; only the panel buttons do.
        self.assertIn('ConsoleActions.playOffer(FloatingConsole.this,chosen.html)', floating)
        service = next(s for s in app.findall('service') if s.get(ns+'name') == '.PlaybackService')
        self.assertEqual(service.get(ns+'exported'), 'false')
        receiver = (JAVA/'BrowserImportActivity.java').read_text()
        self.assertLess(receiver.index('play.setOnClickListener'), receiver.index('PlaybackService.submitOrQueue'))
        self.assertIn('本场尚未播放',receiver)
        self.assertIn('确认播放本场回放', receiver)
        self.assertIn('PlaybackService.submitOrQueue', receiver)
        service=(JAVA/'PlaybackService.java').read_text()
        self.assertIn('if(busy||PlaybackStatus.ownsTask(state))',service)
        self.assertIn('ReplayQueue.add',service)
        for forbidden in ('getStringExtra(', 'getDoubleExtra(', 'evaluateJavascript', 'NativePython.', 'Runtime.getRuntime', 'recoverInitialization'):
            self.assertNotIn(forbidden, receiver)
        pure = (JAVA/'BrowserImport.java').read_text()
        for forbidden in ('android.', 'java.net.Socket', 'FileOutputStream', 'ProcessBuilder', 'URL.openConnection'):
            self.assertNotIn(forbidden, pure)

    def test_script_is_click_scoped_local_and_bounded(self):
        script = (ROOT/'browser-bridge/royale-replay-phone.user.js').read_text()
        self.assertIn('@grant        none', script)
        self.assertEqual(script.count('// @match'), 2)
        for forbidden in ('document.cookie', 'GM_xmlhttpRequest', 'fetch(', 'XMLHttpRequest', 'localStorage', 'navigator.clipboard', '@require', '@connect'):
            self.assertNotIn(forbidden, script)
        self.assertLess(script.index("button.addEventListener('click'"), script.index('cloneNode(true)'))
        self.assertIn("clone.querySelector('#royale-replay-phone-bridge')?.remove()", script)
        self.assertIn('package=local.royale.replay.android;', script)
        self.assertIn("new window.CompressionStream('gzip')", script)
        self.assertIn('window.crypto.subtle.digest', script)
        self.assertNotIn('globalThis', script)
        self.assertIn('160 * 1024', script)
        self.assertNotIn('browser_fallback_url', script)


if __name__ == '__main__':
    unittest.main()
