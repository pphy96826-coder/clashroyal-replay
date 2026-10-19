"""Run only in LLDB against our own translated-call fixture."""
import json
from pathlib import Path
import lldb


def run(debugger,core,output):
    import sys
    sys.path.insert(0,core)
    import portable_config
    portable_config.runtime_profile=lambda:dict(native_transport='mumu-nativebridge-v1')
    from native_expression import NativeExpression
    target=debugger.GetSelectedTarget();process=target.GetProcess()
    report=dict(ok=False,game_calls=False,process_pid=process.GetProcessID())
    try:
        if process.GetState()!=lldb.eStateStopped:raise RuntimeError('fixture did not stop at its ready breakpoint')
        identity=dict(pid=process.GetProcessID(),base='0x0')
        path='/data/local/tmp/royale_replay_probe/fixture.so'
        call=NativeExpression(debugger,identity,dict(exports={}),dict(device_path=path))
        def evaluate(text):return call._evaluate(text)
        functions={i:evaluate('(unsigned long long)rr_mumu_test_address(%dULL)'%i) for i in range(1,7)}
        call.functions={'rr_mumu_call':evaluate('(unsigned long long)&rr_mumu_call')}
        call.authorize_component(functions)
        assert call(functions[1],'unsigned long long(*)()')==0xfedcba9876543210
        assert call(functions[2],'int(*)()')==(1<<64)-7
        values=[0x1122334455667788,123456789,0x8877665544332211,0xfedcba9876543210,0x8000000100000001]
        signature='int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)'
        assert call(functions[3],signature,','.join(hex(value)+'ULL' for value in values),False)==1
        import struct
        error=lldb.SBError();raw=process.ReadMemory(functions[6],40,error)
        assert error.Success() and struct.unpack('<5Q',raw)==tuple(values)
        assert call(functions[4],'int(*)(void*)','(void*)'+hex(functions[6])+'ULL')==1
        assert call(functions[5],'void*(*)(const char*,int)',json.dumps(path)+',2',False)==functions[6]
        try:call(functions[1]+1,'unsigned long long(*)()')
        except ValueError:pass
        else:raise AssertionError('unbound guest address accepted')
        report.update(ok=True,typed_calls=5,wide_arguments=True,shared_memory=True,invalid_address_rejected=True)
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error)
    finally:
        report['detached']=process.Detach().Success()
        Path(output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))
