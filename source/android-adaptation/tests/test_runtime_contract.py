import ast
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RuntimeFingerprintTests(unittest.TestCase):
    def setUp(self):self.contract=json.loads((ROOT/'profiles/native-code-contract.json').read_text())

    def test_pinned_library_and_unique_fingerprints(self):
        self.assertEqual(self.contract['library_sha256'],'c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55')
        pins=self.contract['pins'];self.assertEqual(len(pins),61)
        self.assertEqual(len({p['va'] for p in pins}),61)
        for pin in pins:
            self.assertEqual(pin['size'],32);self.assertEqual(int(pin['va'],0)%4,0)
            self.assertRegex(pin['file_sha256'],r'^[a-f0-9]{64}$');self.assertRegex(pin['runtime_sha256'],r'^[a-f0-9]{64}$')

    def test_no_old_process_handles_or_code_bytes(self):
        self.assertFalse(self.contract['contains_process_handles'])
        forbidden={'pid','address','serial','worker_handle','raw_hex','process_start_time','source_player'}
        def inspect(value):
            if isinstance(value,dict):
                self.assertFalse(forbidden&value.keys())
                for child in value.values():inspect(child)
            elif isinstance(value,list):
                for child in value:inspect(child)
        inspect(self.contract)

    def test_all_compiler_entry_points_are_audited(self):
        tree=ast.parse((ROOT/'device/device_build.py').read_text())
        functions=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                       and any(isinstance(t,ast.Name) and t.id=='FUNCTIONS' for t in node.targets))
        pins={int(p['va'],0):p for p in self.contract['pins']}
        self.assertEqual(len(functions),47);self.assertTrue(set(functions)<=pins.keys())
        self.assertEqual(sum(pins[v]['file_sha256']!=pins[v]['runtime_sha256'] for v in functions),11)


if __name__=='__main__':unittest.main()
