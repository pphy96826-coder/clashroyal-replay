"""Audited bootstrap gate with an explicit observe-original recovery path.

Observation never dlopens or publishes the original task a second time.
"""
import hashlib
import json
from pathlib import Path
import struct
import time
import lldb
from device_session import ReadOnlySession
from source_completion import source_completed,source_failure
from device_expression import evaluate
from debugger_compatibility import snapshot as compatibility_snapshot


def run(debugger,directory,attempt,*,observe_original=False,receipt=None):
    output=directory/((receipt or attempt)+'-result.json')
    if output.exists():raise FileExistsError('preserve original receipt')
    binding=json.loads((directory/(attempt+'-binding.json')).read_text())
    comp=json.loads((directory/(attempt+'-component.json')).read_text())
    loader=json.loads((directory/(attempt+'-loader-binding.json')).read_text())
    identity=binding['identity'];base=int(identity['base'],0)
    target=debugger.GetSelectedTarget();process=target.GetProcess()
    result=dict(errors=[],publication=None,native_calls=False,detached=False,component_unloaded=False,
                initialization_only=not binding['source_execution'],observation_only=observe_original,
                desktop_backend_used=False,network_settings_changed=False,online_match_started=False)
    functions={};regions=[]
    translated_expression=None
    if identity.get('native_transport')=='mumu-nativebridge-v1':
        from mumu_expression import NativeExpression
        translated_expression=NativeExpression(debugger,identity,loader,comp)
    def save():output.write_text(json.dumps(result,indent=2))
    def memory(address,size):
        if not 0<size<=262144:raise ValueError('excessive observation')
        error=lldb.SBError();data=process.ReadMemory(address&0x00ffffffffffffff,size,error)
        if not error.Success() or len(data)!=size:raise RuntimeError('short local native observation')
        return data
    def ptr(address):return struct.unpack('<Q',memory(address,8))[0]
    def public():
        root=ptr(base+0x1d34ae0)
        if root!=int(binding['root_raw'],0) or ptr(root+0x20)!=int(binding['services_raw'],0):raise RuntimeError('public resource owner changed')
    def expression(address,signature,args='',stop_others=True):
        evidence={};result['native_expression']=evidence
        # Our debugger instance only. Keep the allocation/CanJIT reason when
        # a virtual ROM rejects native execution, without overriding that
        # decision, retrying the call, or changing SELinux/device settings.
        log=directory/(attempt+'-expression.log')
        logging=False
        logging_error=''
        try:
            # Full thread/step logging on every successful MuMu call adds
            # unnecessary JIT/IO work. Keep result/error evidence and allow an
            # explicit app-private diagnostic flag on a fresh attempt.
            verbose=not translated_expression or (directory/'debug-native-calls.json').is_file()
            if verbose:
                command=lldb.SBCommandReturnObject()
                debugger.GetCommandInterpreter().HandleCommand(
                    'log enable -f '+json.dumps(str(log))+' lldb process thread step',command)
                logging=command.Succeeded()
                logging_error='' if logging else str(command.GetError())[:500]
            evidence['verbose_logging_requested']=bool(verbose)
            if translated_expression:
                try:value=translated_expression(address,signature,args,stop_others)
                finally:evidence.update(translated_expression.evidence)
                return value
            return evaluate(lldb,target,process,identity['pid'],
                            '((%s)%dULL)(%s)'%(signature,address,args),
                            stop_others=stop_others,evidence=evidence)
        finally:
            if logging:
                debugger.GetCommandInterpreter().HandleCommand('log disable lldb process thread step',lldb.SBCommandReturnObject())
            if logging_error:evidence['logging_error']=logging_error
            if evidence.get('error'):
                try:
                    # Read only AFTER the failed call. Never retry an expression
                    # or insert an extra allocation into the target as a test.
                    current=ReadOnlySession(identity).verify()
                    evidence['compatibility']=compatibility_snapshot(lldb,target,process,identity['pid'],current)
                except Exception as error:evidence['compatibility_error']=str(error)[:500]
                try:
                    with log.open('rb') as stream:
                        stream.seek(0,2);stream.seek(max(0,stream.tell()-12000))
                        evidence['debugger_process_log_tail']=stream.read(12000).decode(errors='replace')
                except OSError:pass
            save()
    def call(name,args=''):
        signature='int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)' if name=='start' else 'int(*)()' if name=='release' else 'unsigned long long(*)()'
        return expression(functions['cr_web_bootstrap_'+name],signature,args,name!='start')
    debugger.SetAsync(False)
    try:
        if process.GetProcessID()!=identity['pid'] or loader['identity']!=identity:raise RuntimeError('wrong native generation')
        for group in (identity['jni_exports'],binding['pins'],list(loader['exports'].values())):
            for pin in group:
                address=int(pin.get('address',hex(base+int(pin['va'],0))),0)
                if hashlib.sha256(memory(address,pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('native code fingerprint changed')
        public();maps=ReadOnlySession(identity).verify()
        if observe_original:
            original=json.loads((directory/(attempt+'-result.json')).read_text())
            if original.get('publication')!=1 or not original.get('detached'):raise RuntimeError('no detached original published task')
            handle=int(original['owned_loader_handle'],0)
            done=int(original['completion_address'],0)
            if struct.unpack('<I',memory(done,4))[0]!=1:raise RuntimeError('original task still pending; retain it')
        else:
            if comp['device_path'] in maps:raise RuntimeError('component already loaded; never republish')
            result['native_calls']=True
            handle=expression(int(loader['exports']['dlopen']['address'],0),'void*(*)(const char*,int)',json.dumps(comp['device_path'])+',2',False)
            result['owned_loader_handle']=hex(handle);save()
            if not handle:raise RuntimeError('component load failed')
            maps=ReadOnlySession(identity).verify()
        result['owned_loader_handle']=hex(handle)
        headers=[]
        for line in maps.splitlines():
            fields=line.split()
            if len(fields)<6 or fields[-1]!=comp['device_path']:continue
            low,high=(int(v,16) for v in fields[0].split('-'));regions.append((low,high))
            if int(fields[2],16)==0 and 'r' in fields[1]:headers.append(low)
        if len(headers)!=1:raise RuntimeError('original component mapping not unique')
        module=headers[0]
        if memory(module,64)!=Path(comp['local_path']).read_bytes()[:64]:raise RuntimeError('component ELF differs')
        for name,pin in comp['exports'].items():
            address=module+int(pin['va'],0)
            if hashlib.sha256(memory(address,pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('component export differs')
            functions[name]=address
        if translated_expression:translated_expression.authorize_component(functions)
        if not observe_original:
            public()
            result['publication']=call('start','%sULL,%d,%dULL,%sULL,%sULL'%(identity['base'],identity['pid'],binding['worker_tid'],binding['worker_handle'],binding['services_raw']))
            save()
            if result['publication']!=1:raise RuntimeError('publication rejected; never retry')
            done=call('done_address');result['completion_address']=hex(done);save()
            debugger.SetAsync(True)
            if not process.Continue().Success():raise RuntimeError('resume failed')
            complete=False
            for _ in range(60):
                time.sleep(.5)
                state=process.GetState()
                if state!=lldb.eStateRunning:raise RuntimeError('native process state '+str(state)+'; retain original task')
                session=ReadOnlySession(identity);finished=struct.unpack('<I',session.read(done,4))[0]
                if finished not in (0,1):raise RuntimeError('invalid completion flag')
                if finished:complete=True;break
            if not process.Stop().Success():raise RuntimeError('stop for observation failed')
            deadline=time.monotonic()+3
            while process.GetState()==lldb.eStateRunning and time.monotonic()<deadline:time.sleep(.02)
            debugger.SetAsync(False)
            if not complete or process.GetState()!=lldb.eStateStopped:raise RuntimeError('original task remains pending')
        result['native_calls']=True
        batch=None
        if translated_expression and 'cr_web_bootstrap_snapshot_address' in functions:
            batch=struct.unpack('<4Q',memory(call('snapshot_address'),32))
            result['native_snapshot_calls_batched']=True
        f=list(struct.unpack('<96Q',memory(batch[0] if batch else call('result_address'),768)));result['fields']=f;save()
        initialized=(f[:4]==[1,1,1,1] and f[4]==0 and f[6:8]==[1,4] and f[9:16]==[1,2,1,1,1,1,6]
                     and not any(f[80:83]) and f[83]==1 and f[88:94]==[5,0,0,2,4,0])
        clean_deal_failure=(f[:4]==[1,1,1,1] and f[4] in (41,42,43,44) and f[6:8]==[1,4] and f[12:15]==[1,1,1]
                            and not any(f[80:83]) and f[83]==1 and f[88:94]==[5,0,0,2,4,0])
        if not initialized and not clean_deal_failure:raise RuntimeError('native initialization/cleanup did not verify')
        address=batch[1] if batch else call('towers_address');values=struct.unpack('<48Q',memory(address,384))
        result['initial_towers']=[dict(zip(('owner','data_id','x','y','hp','max_hp','level_index','king'),values[i:i+8])) for i in range(0,48,8)]
        if binding['source_execution'] and initialized:
            address=batch[2] if batch else expression(functions['cr_web_source_text_address'],'unsigned long long(*)()')
            size=batch[3] if batch else expression(functions['cr_web_source_text_size'],'unsigned long long(*)()')
            source=json.loads(memory(address,size).decode())
            with (directory/(attempt+'-source-execution.json')).open('x') as stream:json.dump(source,stream,indent=2)
            result['private_source_execution_complete']=source_completed(source,binding['source_event_count'])
            result['source_commands_generated']=len(source['commands'])
        public()
        # ARM devices must prove no component frames remain before dlclose.
        # MuMu retains all code until process exit; x86 unwinds cannot prove
        # translated ARM return-address absence and are not an unload gate.
        # Completed/destroyed task and native release resource guards above
        # remain mandatory. No translated code is unloaded in this branch.
        if not translated_expression and any(low<=frame.GetPC()<high for thread in process for frame in thread for low,high in regions):raise RuntimeError('component still on a worker stack')
        if call('release')!=1:raise RuntimeError('observer release refused')
        if translated_expression:
            # Keep this idle module's loader reference until the owned client exits.
            # Houdini may retain translated blocks on other threads after dlclose.
            # Resources/task are already released above; never report an unload.
            from mumu_runtime import component_code_ranges
            component_code_ranges(ReadOnlySession(identity),comp)
            result.update(observer_released=True,mumu_module_retained_safe=True,
                module_retained_for_translated_return_safety=True,retained_component_path=comp['device_path'],
                retained_component_sha256=comp['sha256'],component_retained_idle=True,resource_cleanup_verified=True,
                retained_code_verified=True,requires_process_exit_for_unload=True,
                native_transport='mumu-nativebridge-v1')
        else:
            if expression(int(loader['exports']['dlclose']['address'],0),'int(*)(void*)','(void*)'+hex(handle)+'ULL')!=0:raise RuntimeError('loader reference release failed')
            if comp['device_path'] in ReadOnlySession(identity).verify():raise RuntimeError('component remains mapped')
            result['component_unloaded']=True
        result['source_bootstrap_verified']=initialized
        if clean_deal_failure:raise RuntimeError('native deal mismatch; private initialization safely released')
        if binding['source_execution'] and not result['private_source_execution_complete']:
            result.update(source_rejected_after_cleanup=True,source_failure_detail=source_failure(source),
                source_execution_sha256=hashlib.sha256((directory/(attempt+'-source-execution.json')).read_bytes()).hexdigest())
            raise RuntimeError(source_failure(source))
    except BaseException as error:
        result['errors'].append(type(error).__name__+': '+str(error))
        result['process_state']=process.GetState()
    finally:
        debugger.SetAsync(False)
        if process.IsValid() and process.GetState()==lldb.eStateRunning:process.Stop()
        if process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):result['detached']=process.Detach().Success()
        save()
    return result
