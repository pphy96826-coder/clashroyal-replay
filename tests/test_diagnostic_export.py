import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

REPO=Path(__file__).resolve().parents[1]
MAC=REPO/'source/macos/royale-replay-deploy/assets/project/official-web-replay/diagnostic_export.py'
WIN=REPO/'source/windows-adaptation/project/official-web-replay/diagnostic_export.py'
spec=importlib.util.spec_from_file_location('export_test',MAC)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.core=self.root/'core';self.store=self.core/'console-runs'
        self.run=self.store/'20261019-120000-12345678';self.run.mkdir(parents=True)
        (self.run/'console.log').write_text('running bootstrap-v12 and scene-v14')
        (self.run/'source.json').write_text('{"retained_action_count":71}')
        (self.core/'bootstrap-v12-result.json').write_text('{"error":107}')
        (self.core/'scene-v14-component.json').write_text('{}')
        self.target=self.root/'diag.zip'

    def export(self,**kwargs):
        result=module.export_diagnostics(self.store,self.target,**kwargs)
        with zipfile.ZipFile(self.target) as archive:
            self.assertIsNone(archive.testzip())
            return result,{n:archive.read(n) for n in archive.namelist()}

    def test_collects_current_log_referenced_attempts_and_checksums(self):
        result,files=self.export()
        self.assertIn('attempts/bootstrap-v12-result.json',files)
        self.assertIn('task/source.json',files)
        for row in files['SHA256SUMS.txt'].decode().splitlines():
            digest,name=row.split('  ',1);self.assertEqual(hashlib.sha256(files[name]).hexdigest(),digest)
        self.assertFalse(result['partial'])

    def test_excludes_html_binaries_browser_and_foreign_attempts(self):
        for name in ('source.html','library.so','private.key','browser.log'):(self.run/name).write_text('SECRET')
        (self.core/'scene-v123-result.json').write_text('SECRET')
        _,files=self.export();self.assertNotIn(b'SECRET',b''.join(files.values()))

    def test_does_not_overwrite_existing_file(self):
        self.target.write_text('keep')
        with self.assertRaises(FileExistsError):self.export()
        self.assertEqual(self.target.read_text(),'keep')

    def test_symlinked_allowed_file_excluded(self):
        foreign=self.root/'outside';foreign.write_text('SECRET')
        (self.run/'error.txt').symlink_to(foreign)
        result,files=self.export();self.assertTrue(result['partial'])
        self.assertNotIn('task/error.txt',files)

    def test_oversized_file_skipped(self):
        (self.run/'large.json').write_bytes(b'0'*(module.MAX_FILE+1))
        result,files=self.export();self.assertTrue(result['partial'])
        self.assertNotIn('task/large.json',files)

    def test_foreign_run_rejected(self):
        with self.assertRaises(ValueError):self.export(run=self.root/'20261019-120000-87654321')

    def test_missing_store_still_produces_report(self):
        result=module.export_diagnostics(self.root/'missing',self.target)
        self.assertEqual(result['records'],0)

    def test_both_desktops_have_identical_exporter_and_controls(self):
        self.assertEqual(MAC.read_bytes(),WIN.read_bytes())
        self.assertIn('导出诊断',MAC.with_name('ReplayConsole.swift').read_text())
        self.assertIn('导出诊断',WIN.with_name('windows_console.py').read_text())


if __name__=='__main__':unittest.main()
