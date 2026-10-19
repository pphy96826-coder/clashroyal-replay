"""One empty native task, with retained module and an exact ownership receipt."""
import hashlib
import json
from pathlib import Path
import struct
import time
import traceback
import lldb

def run(debugger,binding_path,result_path):
    process=debugger.GetSelectedTarget().GetProcess()
    result=dict(errors=[],publication=None,game_functions_called=False,replay_submitted=False,
        online_match_started=False,detached=False,component_unloaded=False,module_retained_for_translated_return_safety=True)
    path=Path(result_path)
    def save():path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    def memory(address,size):
        error=lldb.SBError();raw=process.ReadMemory(address,size,error)
        if not error.Success() or len(raw)!=size:raise RuntimeError('short diagnostic observation')
        return raw
    debugger.SetAsync(False)
    try:
        data=json.loads(Path(binding_path).read_text(encoding='utf-8'))
        identity=data['identity'];worker=data['worker'];obs=worker['observation'];comp=worker['component']
        if identity!=obs['identity'] or process.GetProcessID()!=identity['pid']:raise RuntimeError('worker generation changed')
        from client_session import ReadOnlySession
        session=ReadOnlySession(identity);session.verify()
        stat=__import__('subprocess').check_output(session.adb+['shell','cat',f"/proc/{session.pid}/task/{obs['worker_tid']}/stat"],text=True,timeout=10)
        if stat[stat.rfind(')')+2:].split()[19]!=obs['worker_start_time']:raise RuntimeError('worker thread changed')
        raw=Path(comp['local_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=comp['sha256']:raise RuntimeError('diagnostic binary changed')
        remote=__import__('subprocess').check_output(session.adb+['shell','sha256sum',comp['device_path']],text=True,timeout=10).split()[0]
        if remote!=comp['sha256']:raise RuntimeError('uploaded diagnostic changed')
        for pin in obs['pins']:
            # Scene/domain state is rechecked separately; these are stable resource/worker bindings.
            if pin['name'] in ('services-root','services','mainloop-handle','mainloop-tid'):
                if hashlib.sha256(memory(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:
                    raise RuntimeError('resource or worker changed')
        from native_expression import NativeExpression
        call=NativeExpression(debugger,identity,data['loader'],comp)
        handle=call(int(data['loader']['exports']['dlopen']['address'],0),'void*(*)(const char*,int)',json.dumps(comp['device_path'])+',2',False)
        result['owned_loader_handle']=hex(handle);result['component_path']=comp['device_path'];save()
        if not handle:raise RuntimeError('diagnostic load failed')
        from mapped_elf import load_bias
        from elf_contract import Elf
        maps=ReadOnlySession(identity).verify().splitlines();base=load_bias(maps,comp['device_path'],Elf(raw))
        functions={}
        for name,pin in comp['exports'].items():
            address=base+int(pin['va'],0)
            if hashlib.sha256(memory(address,pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('diagnostic export changed')
            functions[name]=address
        call.authorize_component(functions)
        def snapshot():
            address=call(functions['rr_mumu_worker_snapshot'],'unsigned long long(*)()')
            result['snapshot_address']=hex(address)
            values=list(struct.unpack('<16Q',memory(address,128)))
            names=('publisher_result','attempted','request_present','phase','submitted','entered','returned','destroyed',
                'expected_tid','execution_tid','destruction_tid','reserved','validation_stage','observed_import','expected_import','reserved2')
            result['snapshot']=dict(zip(names,values));save();return values
        # Persist the attempt BEFORE the irreversible queue publication.
        result['start_attempted']=True;save()
        result['publication']=call(functions['rr_mumu_worker_start'],
            'int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)',
            f"{identity['base']}ULL,{identity['pid']},{obs['worker_tid']}ULL,{obs['worker_handle']}ULL,{obs['services_raw']}ULL",False)
        save();values=snapshot()
        if result['publication']!=1:raise RuntimeError('empty task rejected; never republish')
        # Only poll the one existing request. All engine work remains resumed.
        until=time.monotonic()+15
        while not values[7] and time.monotonic()<until:
            debugger.SetAsync(True)
            if not process.Continue().Success():raise RuntimeError('cannot resume existing request')
            time.sleep(.25)
            if process.GetState()!=lldb.eStateRunning:raise RuntimeError('client stopped while empty task pending')
            if not process.Stop().Success():raise RuntimeError('cannot observe original request')
            deadline=time.monotonic()+3
            while process.GetState()==lldb.eStateRunning and time.monotonic()<deadline:time.sleep(.02)
            debugger.SetAsync(False)
            if process.GetState()!=lldb.eStateStopped:raise RuntimeError('stop did not finish')
            values=snapshot()
        if values[3:8]!=[2,1,1,1,1] or values[8:11]!=[obs['worker_tid']]*3:
            raise RuntimeError('original empty task execution or ownership incomplete')
        result['observer_released']=call(functions['rr_mumu_worker_release'],'int(*)()')==1
        if not result['observer_released']:raise RuntimeError('observer release refused')
        result['worker_integration_verified']=True
    except BaseException as error:
        result['errors'].append(type(error).__name__+': '+str(error));result['traceback']=traceback.format_exc()
    finally:
        debugger.SetAsync(False)
        if process.IsValid() and process.GetState()==lldb.eStateRunning:process.Stop()
        if process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):
            result['detached']=process.Detach().Success()
        save();print(json.dumps(result))
