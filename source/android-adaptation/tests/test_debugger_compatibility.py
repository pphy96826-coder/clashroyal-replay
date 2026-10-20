"""Read-only compatibility evidence using a strict synthetic SB API."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('compatibility_test',ROOT/'device/debugger_compatibility.py')
compat=importlib.util.module_from_spec(spec);spec.loader.exec_module(compat)


class CompatibilityTests(unittest.TestCase):
    def case(self):
        api=Mock(eStateStopped=5,eFunctionNameTypeFull=2,LLDB_INVALID_ADDRESS=(1<<64)-1)
        process=Mock();process.IsValid.return_value=True;process.GetProcessID.return_value=42;process.GetState.return_value=5
        target=Mock();target.GetProcess.return_value=process;target.GetTriple.return_value='aarch64-linux-android';target.GetAddressByteSize.return_value=8
        target.GetNumModules.return_value=0
        symbols=Mock();symbols.GetSize.return_value=0;target.FindFunctions.return_value=symbols
        thread=process.GetThreadByID.return_value;thread.IsValid.return_value=True;thread.GetThreadID.return_value=42
        frame=thread.GetFrameAtIndex.return_value;frame.IsValid.return_value=True;frame.GetThread.return_value=thread
        register=frame.FindRegister.return_value;register.IsValid.return_value=True
        register.GetError.return_value.Success.return_value=True;register.GetByteSize.return_value=8;register.GetData.return_value.GetByteSize.return_value=8
        return api,target,process,frame

    def check_read_only(self,target,process,frame):
        for obj,name in ((target,'EvaluateExpression'),(frame,'EvaluateExpression'),(process,'Continue'),
                         (process,'Stop'),(process,'AllocateMemory'),(process,'WriteMemory'),(process,'SetSelectedThread')):
            getattr(obj,name).assert_not_called()
        register=frame.FindRegister.return_value
        register.GetValue.assert_not_called();register.GetValueAsUnsigned.assert_not_called()
        register.SetValueFromCString.assert_not_called()

    def test_missing_mmap_is_distinguished_and_no_values_exported(self):
        api,target,process,frame=self.case()
        result=compat.snapshot(api,target,process,42,'')
        self.assertEqual(result['finding'],'mmap_symbol_not_found_in_debugger')
        self.assertTrue(result['register_availability']['x0']['readable'])
        self.assertFalse(result['register_contents_collected']);json.dumps(result)
        self.check_read_only(target,process,frame)

    def test_found_symbol_must_be_in_current_executable_mapping(self):
        for mode,expected in [('r-xp','mmap_found_in_executable_mapping'),('r--p','mmap_symbol_mapping_not_verified')]:
            api,target,process,frame=self.case()
            symbols=target.FindFunctions.return_value;symbols.GetSize.return_value=1
            context=symbols.GetContextAtIndex.return_value
            context.GetFunction.return_value.IsValid.return_value=True
            context.GetFunction.return_value.GetStartAddress.return_value.GetLoadAddress.return_value=0x1800
            result=compat.snapshot(api,target,process,42,'1000-2000 '+mode+' 00000000 00:00 1 /system/lib64/libc.so')
            self.assertEqual(result['finding'],expected);self.check_read_only(target,process,frame)

    def test_invalid_address_is_not_a_mapped_function(self):
        api,target,process,frame=self.case();symbols=target.FindFunctions.return_value;symbols.GetSize.return_value=1
        ctx=symbols.GetContextAtIndex.return_value;ctx.GetFunction.return_value.IsValid.return_value=True
        ctx.GetFunction.return_value.GetStartAddress.return_value.GetLoadAddress.return_value=api.LLDB_INVALID_ADDRESS
        result=compat.snapshot(api,target,process,42,'')
        self.assertFalse(result['symbols']['mmap']['candidates'][0]['load_address_valid'])
        self.assertEqual(result['finding'],'mmap_symbol_mapping_not_verified')

    def test_missing_process_or_running_process_is_not_probed(self):
        for mode in ('foreign','running','invalid'):
            api,target,process,frame=self.case()
            if mode=='foreign':process.GetProcessID.return_value=43
            elif mode=='running':process.GetState.return_value=6
            else:process.IsValid.return_value=False
            result=compat.snapshot(api,target,process,42,'')
            target.FindFunctions.assert_not_called();frame.FindRegister.assert_not_called()
            self.check_read_only(target,process,frame);json.dumps(result)

    def test_bad_symbol_query_is_unknown_not_proof_of_missing_symbol(self):
        api,target,process,frame=self.case();target.FindFunctions.side_effect=RuntimeError('SB lookup unavailable')
        result=compat.snapshot(api,target,process,42,'')
        self.assertEqual(result['finding'],'mmap_lookup_unknown');self.assertEqual(len(result['errors']),3)

    def test_register_failure_is_recorded_not_treated_as_permission_denial(self):
        api,target,process,frame=self.case();frame.FindRegister.return_value.GetError.return_value.Success.return_value=False
        result=compat.snapshot(api,target,process,42,'')
        self.assertFalse(result['register_availability']['v0']['readable'])
        self.assertIn('do not prove full checkpoint',result['register_note'])
        self.check_read_only(target,process,frame)

    def test_symbol_and_module_enumeration_is_bounded(self):
        api,target,process,frame=self.case();target.GetNumModules.return_value=10000
        module=target.GetModuleAtIndex.return_value
        for name in ('GetFileSpec','GetPlatformFileSpec'):
            value=getattr(module,name).return_value;value.GetDirectory.return_value='/system/lib64';value.GetFilename.return_value='libc.so'
        module.GetTriple.return_value='aarch64-linux-android'
        symbols=target.FindFunctions.return_value;symbols.GetSize.return_value=10000
        ctx=symbols.GetContextAtIndex.return_value;ctx.GetFunction.return_value.IsValid.return_value=False;ctx.GetSymbol.return_value.IsValid.return_value=False
        result=compat.snapshot(api,target,process,42,'')
        self.assertEqual(target.GetModuleAtIndex.call_count,256);self.assertEqual(len(result['modules']),16)
        self.assertEqual(len(result['symbols']['mmap']['candidates']),8);self.assertTrue(result['symbols']['mmap']['truncated'])

    def test_gate_keeps_failure_evidence_without_retry_or_extra_allocation(self):
        source=(ROOT/'device/phone_bootstrap_gate.py').read_text()
        self.assertIn('compatibility_snapshot(lldb,target,process',source)
        module_source=(ROOT/'device/debugger_compatibility.py').read_text()
        for forbidden in ('EvaluateExpression(', 'AllocateMemory(', 'Continue(', 'WriteMemory(', 'SetValueFromCString('):
            self.assertNotIn(forbidden,module_source)


if __name__=='__main__':unittest.main()
