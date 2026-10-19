import importlib.util
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import patch

CORE=Path(__file__).resolve().parents[1]/'project/official-web-replay'
sys.path.insert(0,str(CORE))
import mumu_runtime
from elf_contract import Elf


def expression_module():
    spec=importlib.util.spec_from_file_location('mumu_expression_unit',CORE/'native_expression.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'lldb':types.SimpleNamespace()}):spec.loader.exec_module(module)
    return module


class MuMuAdapterTests(unittest.TestCase):
    def test_native_call_input_cannot_inject_debugger_expressions(self):
        module=expression_module()
        for value in ('1ULL);system("x")','(void*)0x123+4','-1','0x1<<8','18446744073709551616'):
            with self.assertRaises(ValueError):module.integer(value)
        self.assertEqual(module.integer('(void*)0xfedcba9876543210ULL'),0xfedcba9876543210)

    def test_component_load_is_bounded_to_owned_directory(self):
        module=expression_module()
        for path in ('/system/lib64/libc.so','/data/local/tmp/royale_replay_x/../../evil.so','/data/local/tmp/royale_replay_x/a.so/evil.so'):
            import json
            with self.assertRaises(ValueError):module.arguments('void*(*)(const char*,int)',json.dumps(path)+',2')
        with self.assertRaises(ValueError):module.arguments('void*(*)(const char*,int)','"/data/local/tmp/royale_replay_x/a.so",258')

    def test_unknown_signatures_and_invalid_pid_rejected(self):
        module=expression_module()
        with self.assertRaises(ValueError):module.arguments('void(*)()','')
        with self.assertRaises(ValueError):module.arguments('int(*)()','1')
        with self.assertRaises(ValueError):module.arguments('int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)','1,2147483648,2,3,4')

    def test_bridge_build_change_rejected_before_injection(self):
        def output(command,**kwargs):
            suffix=command[4:]
            if suffix==['getprop','ro.product.cpu.abi']:return 'x86_64\n'
            if suffix==['getprop','ro.dalvik.vm.native.bridge']:return 'libnb.so\n'
            if suffix==['sha256sum','/system/lib64/libnb.so']:return '0'*64+'  /system/lib64/libnb.so\n'
            raise AssertionError('unexpected device mutation: '+repr(command))
        with patch('mumu_runtime.subprocess.check_output',side_effect=output):
            with self.assertRaisesRegex(ValueError,'unvalidated MuMu'):mumu_runtime.validate_device(['adb','-s','127.0.0.1:16384'])

    def test_host_elf_requires_explicit_machine(self):
        raw=bytearray(64);raw[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',raw,18,62);struct.pack_into('<H',raw,54,56)
        with self.assertRaises(ValueError):Elf(raw)
        Elf(raw,machine=62)
        with self.assertRaises(ValueError):Elf(raw,machine=3)


if __name__=='__main__':unittest.main()
