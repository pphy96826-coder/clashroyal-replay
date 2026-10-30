import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
selector=load('windows_selector',ROOT/'device/device_variant.py');generator=load('windows_generator',ROOT/'scripts/runtime_variants.py')
NEW='0849d86b8a3689589e81fa2c50173e92f2ebf5fa0984c36ed4b448723d833fe2';OLD='c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55'
class Tests(unittest.TestCase):
 def test_no_adapter_is_selected_for_unknown_or_pending_full_hash(self):
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);(home/'app').mkdir();(home/'app/native-contract.json').write_text(json.dumps(dict(library_sha256=OLD)))
   self.assertEqual(selector.adapter_path(home,OLD),home/'app')
   for value in (NEW,'F'*64,NEW[:16],'../'+NEW):
    with self.assertRaises(ValueError):selector.adapter_path(home,value)
   folder=home/'variants'/NEW/'app';folder.mkdir(parents=True)
   (folder/'native-contract.json').write_text(json.dumps(dict(library_sha256=NEW,supported=True,native_execution_allowed=False)))
   with self.assertRaises(ValueError):selector.adapter_path(home,NEW)
 def test_native_actions_choose_before_import_and_tools_stay_base(self):
  for action in ('import-source','check-native-tools','check-tools','reset','release-preparation'):
   self.assertIsNone(selector.installed_apk(action,Path('/missing'),Path('/missing')))
  with self.assertRaises(ValueError):selector.library_hash(Path('/not-an-installed-apk'))
 def test_windows_slots_and_mapping_are_exact_and_heavy_tools_shared(self):
  files={'app/mumu_runtime.py':(ROOT/'device/mumu_runtime.py').read_bytes(),
         'app/mumu_platform.py':(ROOT/'device/mumu_platform.py').read_bytes(),
         'app/device_session.py':(ROOT/'device/device_session.py').read_bytes(),
         'app/native-src/official-web-replay/client_layout.h':(ROOT.parent/'windows-adaptation/project/official-web-replay/client_layout.h').read_bytes(),
         'app/mumu-support/runtime/bin/phone_runtime':b'preserve-original-executable'}
  expanded=generator.expand(files,ROOT);prefix='variants/'+NEW+'/app/'
  runtime=expanded[prefix+'mumu_runtime.py'].decode()
  for value in ('0x1d857d0','0x1d857d8','0x1d85a00','0x1d85a18','0x1d85a88','0x1d85dc8','0x1d85d48'):self.assertIn(value,runtime)
  self.assertIn('0x1c46000',expanded[prefix+'device_session.py'].decode())
  self.assertIn('active_avatar=avatar_3852',expanded[prefix+'native-src/official-web-replay/client_layout.h'].decode())
  self.assertNotIn(prefix+'mumu-support/runtime/bin/phone_runtime',expanded)
  self.assertEqual(expanded['app/mumu_runtime.py'],files['app/mumu_runtime.py'])
  self.assertEqual(expanded,generator.expand(expanded,ROOT))
if __name__=='__main__':unittest.main()
