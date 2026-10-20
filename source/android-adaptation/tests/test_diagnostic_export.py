"""Run the actual Java ZIP exporter with synthetic private files; no Android/root."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


class DiagnosticExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jdk=Path(os.environ.get('JAVA_HOME','/nonexistent-jdk'))/'bin'
        javac,cls.java=shutil.which('javac'),shutil.which('java')
        if (jdk/'javac').is_file():javac,cls.java=str(jdk/'javac'),str(jdk/'java')
        if not javac or not cls.java:raise unittest.SkipTest('JDK required for actual Java export checks')
        cls.build=tempfile.TemporaryDirectory()
        subprocess.run([javac,'-encoding','UTF-8','-d',cls.build.name,
            str(ROOT/'app/src/local/royale/replay/android/DiagnosticExport.java'),
            str(ROOT/'tests/DiagnosticExportCheck.java')],check=True,capture_output=True,timeout=30)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'build'):cls.build.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.files=self.root/'files'
        self.task=self.files/'local-imports/12345678-1234-1234-1234-123456789abc/result/phone-playback'
        self.task.mkdir(parents=True)
        (self.files/'phone-active.json').write_text('{}')
        (self.task/'status.json').write_text('{"state":"needs_review"}')
        (self.task/'error.txt').write_text('native deal mismatch')

    def export(self,active=True):
        target=self.root/'diagnostic.zip'
        subprocess.run([self.java,'-cp',self.build.name,'local.royale.replay.android.DiagnosticExportCheck',
            str(self.files),str(self.task) if active else 'none',str(target)],check=True,capture_output=True,timeout=20)
        with zipfile.ZipFile(target) as archive:
            self.assertIsNone(archive.testzip())
            return {name:archive.read(name) for name in archive.namelist()}

    def test_includes_failures_calibration_and_checksums(self):
        (self.task/'deal-check-1-result.json').write_text('{"detached":true}')
        preparation=self.task/'native-preparation';(preparation/'runtime').mkdir(parents=True)
        (preparation/'preparation-calibrated-2.json').write_text('{}')
        (preparation/'runtime/loader-diagnostic.json').write_text('{}')
        files=self.export()
        for name in ('task/status.json','task/error.txt','task/deal-check-1-result.json',
                     'task/native-preparation/preparation-calibrated-2.json',
                     'task/native-preparation/runtime/loader-diagnostic.json'):
            self.assertIn(name,files)
        for row in files['SHA256SUMS.txt'].decode().splitlines():
            digest,name=row.split('  ',1);self.assertEqual(hashlib.sha256(files[name]).hexdigest(),digest)

    def test_excludes_html_binaries_browser_and_other_jobs(self):
        for name in ('input.html','source.json','secret.apk','library.so','cookies.json','signing-password.txt','private.log'):
            (self.task/name).write_text('DO_NOT_EXPORT')
        (self.files/'input.html').write_text('DO_NOT_EXPORT')
        other=self.files/'local-imports/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/result/phone-playback'
        other.mkdir(parents=True);(other/'error.txt').write_text('OTHER_JOB')
        files=self.export()
        self.assertNotIn(b'DO_NOT_EXPORT',b''.join(files.values()))
        self.assertNotIn(b'OTHER_JOB',b''.join(files.values()))

    def test_symlinked_record_is_skipped(self):
        secret=self.root/'secret';secret.write_text('SECRET')
        (self.task/'error.txt').unlink();(self.task/'error.txt').symlink_to(secret)
        files=self.export()
        self.assertNotIn('task/error.txt',files)
        self.assertIn(b'linked record refused',files['REPORT.txt'])

    def test_symlinked_task_rejected(self):
        original=self.task;replacement=original.with_name('original');original.rename(replacement)
        original.symlink_to(replacement,target_is_directory=True)
        files=self.export();self.assertNotIn('task/status.json',files)
        self.assertIn(b'Active task rejected',files['REPORT.txt'])

    def test_missing_active_task_still_exports_console(self):
        files=self.export(False)
        self.assertIn('console/phone-active.json',files)
        self.assertNotIn('task/status.json',files)
        self.assertIn(b'No readable active task',files['REPORT.txt'])

    def test_oversized_record_skipped_and_source_unchanged(self):
        (self.task/'bootstrap-v2-result.json').write_bytes(b'a'*(4*1024*1024+1))
        before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in self.files.rglob('*') if path.is_file()}
        files=self.export()
        self.assertNotIn('task/bootstrap-v2-result.json',files)
        after={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in self.files.rglob('*') if path.is_file()}
        self.assertEqual(before,after)

    def test_version_matches_manifest_and_button_is_always_available(self):
        manifest=ET.parse(ROOT/'app/AndroidManifest.xml').getroot()
        version=manifest.attrib['{http://schemas.android.com/apk/res/android}versionName']
        java=(ROOT/'app/src/local/royale/replay/android/DiagnosticExport.java').read_text()
        self.assertIn('VERSION="'+version+'"',java)
        ui=(ROOT/'app/src/local/royale/replay/android/MainActivity.java').read_text()
        self.assertIn('导出诊断',ui);self.assertIn('android.intent.action.CREATE_DOCUMENT',ui)
        self.assertNotIn('exportDiagnostic.setVisibility',ui)
        self.assertNotIn('PlaybackService',java)
        self.assertNotIn('StandaloneDoctor.root',java)


if __name__=='__main__':unittest.main()
