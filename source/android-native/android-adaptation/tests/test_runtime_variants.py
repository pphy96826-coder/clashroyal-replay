import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
variant=load('variant_test',ROOT/'device/device_variant.py')
generator=load('variant_generator_test',ROOT/'scripts/runtime_variants.py')
NEW='0849d86b8a3689589e81fa2c50173e92f2ebf5fa0984c36ed4b448723d833fe2'
OLD='c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55'

class RuntimeVariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)
        (self.home/'app').mkdir();(self.home/'app/native-contract.json').write_text(json.dumps({'library_sha256':OLD}))

    def test_previous_adapter_is_kept_separate(self):
        self.assertEqual(variant.adapter_path(self.home,OLD),self.home/'app')
        with self.assertRaises(ValueError):variant.adapter_path(self.home,NEW)

    def test_pending_or_different_contract_never_approves(self):
        dest=self.home/'variants'/NEW/'app';dest.mkdir(parents=True)
        for extra in ({'supported':False,'native_execution_allowed':True},{'supported':True,'native_execution_allowed':False},
                      {'supported':True,'native_execution_allowed':True,'library_sha256':OLD}):
            data=dict(library_sha256=NEW,**{k:v for k,v in extra.items() if k!='library_sha256'})
            if 'library_sha256' in extra:data['library_sha256']=extra['library_sha256']
            (dest/'native-contract.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):variant.adapter_path(self.home,NEW)

    def test_selection_precedes_adapter_import_and_does_not_reuse_old_path(self):
        dest=self.home/'variants'/NEW/'app';dest.mkdir(parents=True)
        (dest/'native-contract.json').write_text(json.dumps(dict(library_sha256=NEW,supported=True,native_execution_allowed=True)))
        request=self.home/'request.json';request.write_text(json.dumps({'apk':'/data/app/installed/base.apk'}))
        with patch.object(variant,'library_hash',return_value=NEW),patch.object(sys,'path',[str(self.home/'app')]):
            self.assertEqual(variant.select(self.home,'play',request,self.home),dest)
            self.assertEqual(sys.path[0],str(dest))

    def test_recovery_uses_original_bound_apk_and_build_uses_fresh_observation(self):
        binding=self.home/'binding.json';binding.write_text(json.dumps({'identity':{'apk':'/data/app/original/base.apk'}}))
        self.assertEqual(str(variant.installed_apk('recover',binding,self.home)),'/data/app/original/base.apk')
        (self.home/'runtime').mkdir();(self.home/'runtime/runtime-observation.json').write_text(binding.read_text())
        self.assertEqual(str(variant.installed_apk('build-component',binding,self.home)),'/data/app/original/base.apk')
        self.assertIsNone(variant.installed_apk('check-tools',self.home,self.home))

    def test_unknown_hash_or_path_cannot_be_selected(self):
        for digest in ('../'+NEW,NEW[:16],'F'*64):
            with self.assertRaises(ValueError):variant.adapter_path(self.home,digest)
        with self.assertRaises(ValueError):variant.library_hash(self.home/'base.apk')

    def test_generated_source_has_exact_new_fields_and_real_import_slots(self):
        original={
            'app/native-src/official-web-replay/client_layout.h':(ROOT/'runtime-source/official-web-replay/client_layout.h').read_bytes(),
            'app/native-src/runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp':(ROOT/'runtime-source/runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp').read_bytes(),
            'app/device_build.py':(ROOT/'device/device_build.py').read_bytes(),
            'app/prepare_native_replay.py':(ROOT/'runtime-source/official-web-replay/prepare_native_replay.py').read_bytes(),
        }
        expanded=generator.expand(original,ROOT);prefix='variants/'+NEW+'/app/'
        self.assertEqual(original['app/native-src/official-web-replay/client_layout.h'],expanded['app/native-src/official-web-replay/client_layout.h'])
        header=expanded[prefix+'native-src/official-web-replay/client_layout.h'].decode()
        self.assertIn('active_avatar=avatar_3852',header)
        worker=expanded[prefix+'native-src/runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp'].decode()
        for value in ('0x1d857d0','0x1d857d8','0x1d85a00','0x1d85a18','0x1d85a88'):self.assertIn(value,worker)
        self.assertNotIn('0x1d85a90',worker)
        preparation=expanded[prefix+'prepare_native_replay.py'].decode()
        self.assertIn(NEW,preparation);self.assertNotIn(OLD,preparation)
        self.assertEqual(expanded,generator.expand(expanded,ROOT))

if __name__=='__main__':unittest.main()
