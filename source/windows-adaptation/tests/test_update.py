"""Offline update tests. No Windows game/device is contacted."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class UpdateTests(unittest.TestCase):
    def case(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);bundle=root/'update';target=root/'existing'
        core=target/'app/official-web-replay';core.mkdir(parents=True)
        config=target/'app/deploy-config.json';config.write_text(json.dumps(dict(native_transport='mumu-nativebridge-v1',keep='original')))
        (core/'sample.py').write_text('old')
        project=bundle/'project/official-web-replay';project.mkdir(parents=True);(project/'sample.py').write_text('new')
        manifest={'official-web-replay/sample.py':hashlib.sha256(b'new').hexdigest()}
        (bundle/'update-manifest.json').write_text(json.dumps(manifest))
        spec=importlib.util.spec_from_file_location('test_updater',ROOT/'scripts/apply_update.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.ROOT=bundle
        fake_cfg=types.SimpleNamespace(operation_lock=lambda:target/'state/native.lock')
        fake_lock=types.SimpleNamespace(flock=lambda *args:None,LOCK_EX=2,LOCK_NB=4)
        return module,target,core,config,fake_cfg,fake_lock

    def test_update_preserves_config_and_backs_up_previous_source(self):
        module,target,core,config,cfg,lock=self.case();before=config.read_bytes()
        with patch.dict(sys.modules,{'portable_config':cfg,'platform_lock':lock}),patch.dict('os.environ'):
            result=module.update(target)
        self.assertEqual((core/'sample.py').read_text(),'new');self.assertEqual(config.read_bytes(),before)
        self.assertEqual((Path(result['backup'])/'official-web-replay/sample.py').read_text(),'old')
        self.assertFalse(result['network_changed'])

    def test_bad_hash_rejected_before_any_replacement(self):
        module,target,core,config,cfg,lock=self.case()
        (module.ROOT/'project/official-web-replay/sample.py').write_text('changed')
        with patch.dict(sys.modules,{'portable_config':cfg,'platform_lock':lock}),patch.dict('os.environ'):
            with self.assertRaises(ValueError):module.update(target)
        self.assertEqual((core/'sample.py').read_text(),'old')

    def test_active_lock_refuses_update(self):
        module,target,core,config,cfg,lock=self.case()
        def busy(*args):raise BlockingIOError()
        lock.flock=busy
        with patch.dict(sys.modules,{'portable_config':cfg,'platform_lock':lock}),patch.dict('os.environ'):
            with self.assertRaises(RuntimeError):module.update(target)
        self.assertEqual((core/'sample.py').read_text(),'old')
