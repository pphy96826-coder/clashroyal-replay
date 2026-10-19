"""Debugger-side handshake of only our bridge modules; no game functions."""
import json
import traceback
from pathlib import Path
import lldb


def run(debugger,binding_path,result_path):
    process=debugger.GetSelectedTarget().GetProcess()
    result=dict(errors=[],game_functions_called=False,replay_submitted=False,detached=False)
    try:
        data=json.loads(Path(binding_path).read_text(encoding='utf-8'))
        if process.GetProcessID()!=data['identity']['pid']:raise RuntimeError('game process changed')
        from native_expression import NativeExpression
        call=NativeExpression(debugger,data['identity'],data['loader'],dict(device_path='/data/local/tmp/royale_replay_smoke/not_loaded.so'))
        call._bind()
        magic=call._host_call(call.functions['rr_mumu_call'],
            'unsigned long long(*)(unsigned long long,unsigned long long,unsigned long long,unsigned long long,unsigned long long,unsigned long long,unsigned long long)',
            '0ULL,0ULL,0ULL,0ULL,0ULL,0ULL,0ULL')
        if magic!=0x41524d3634425247:raise RuntimeError('guest relay handshake differs')
        result.update(bridge_bound=True,magic=hex(magic),host_target=debugger.GetSelectedTarget().GetTriple())
    except BaseException as error:
        result['errors'].append(type(error).__name__+': '+str(error))
        result['traceback']=traceback.format_exc()
    finally:
        if process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):
            if process.GetState()==lldb.eStateRunning:process.Stop()
            result['detached']=process.Detach().Success()
        Path(result_path).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
