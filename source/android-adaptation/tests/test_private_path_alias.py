"""Bind-mount identity and pre-native failure release; never contacts Android."""
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'device/device_playback.py').read_text())


def load(name):
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    def write_new(path,value):
        with path.open('x') as stream:json.dump(value,stream)
    scope=dict(Path=Path,read=lambda p:json.loads(p.read_text()),write_new=write_new,
        hashlib=hashlib,time=time)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'private-path-test','exec'),scope)
    return scope[name]


class PrivatePathTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.files=Path(self.temp.name)/'files';self.result=self.files/'local-imports/job/result'
        self.result.mkdir(parents=True);self.manifest=self.result/'source.json';self.manifest.write_text('{}')
        self.request=self.result/'play-request.json';self.request.write_text('{}')

    def test_distinct_path_spelling_same_file_is_accepted(self):
        # Hardlink identity models a bind view without privileged mounts.
        other=Path(self.temp.name)/'second-view';other.mkdir()
        alias=other/'source.json';os.link(self.manifest,alias)
        self.assertEqual(load('checked_source_manifest')(self.request,str(alias)),self.manifest)

    def test_same_contents_foreign_inode_is_rejected(self):
        other=Path(self.temp.name)/'foreign';other.mkdir();wrong=other/'source.json';wrong.write_text('{}')
        with self.assertRaises(ValueError):load('checked_source_manifest')(self.request,str(wrong))

    def test_wrong_basename_and_nested_foreign_manifest_are_rejected(self):
        wrong=self.result/'other.json';os.link(self.manifest,wrong)
        with self.assertRaises(ValueError):load('checked_source_manifest')(self.request,str(wrong))
        sub=self.result/'other-job';sub.mkdir();foreign=sub/'source.json';foreign.write_text('{}')
        with self.assertRaises(ValueError):load('checked_source_manifest')(self.request,str(foreign))

    def prepare_failure(self,**changes):
        directory=self.result/'phone-playback';directory.mkdir()
        state=dict(state='failed_before_native',source_sha256='a'*64,native_entry_started=False)
        state.update(changes);(directory/'status.json').write_text(json.dumps(state))
        (self.files/'phone-active.json').write_text(json.dumps(dict(directory=str(directory),source_sha256='a'*64)))
        return directory

    def test_before_native_failure_produces_hash_bound_release(self):
        directory=self.prepare_failure()
        load('record_pre_native_release')(directory,self.files,'a'*64)
        proof=json.loads((directory/'preparation-release.json').read_text())
        self.assertTrue(proof['native_not_entered'])
        self.assertEqual(proof['status_sha256'],hashlib.sha256((directory/'status.json').read_bytes()).hexdigest())

    def test_native_entry_or_foreign_source_cannot_be_released(self):
        directory=self.prepare_failure()
        with self.assertRaises(ValueError):load('record_pre_native_release')(directory,self.files,'b'*64)
        (directory/'native-entry.json').write_text('{}')
        with self.assertRaises(ValueError):load('record_pre_native_release')(directory,self.files,'a'*64)
        self.assertFalse((directory/'preparation-release.json').exists())

    def test_unknown_entry_does_not_count_as_false(self):
        directory=self.prepare_failure(native_entry_started=None)
        with self.assertRaises(ValueError):load('record_pre_native_release')(directory,self.files,'a'*64)

    def test_ui_exposes_reconciliation_error(self):
        java=(ROOT/'app/src/local/royale/replay/android/MainActivity.java').read_text()
        self.assertIn('reconciliationNote="旧任务核验失败："',java)
        self.assertIn('reconciliationNote.isEmpty()',java)
        status=(ROOT/'app/src/local/royale/replay/android/PlaybackStatus.java').read_text()
        self.assertIn('Files.isSameFile(directory.toPath(),current.toPath())',status)


if __name__=='__main__':unittest.main()
