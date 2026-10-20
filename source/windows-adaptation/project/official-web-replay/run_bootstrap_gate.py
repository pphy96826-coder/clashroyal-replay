"""One initialization-only native task; retain exact failure owners, detach.

No scene/controller replacement and no online match. A failed or timed-out task
must be observed through its existing handle, never republished.
"""
import hashlib,json,re,struct,sys,time
from pathlib import Path
import lldb
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vendor'))
from client_session import ReadOnlySession
from source_completion import source_completed,source_failure

def run(debugger,attempt='bootstrap'):
    if not re.fullmatch(r'bootstrap(?:-v(?:[2-9]|[1-9][0-9]+))?',attempt):raise ValueError('invalid attempt')
    output=ROOT/(attempt+'-result.json')
    if output.exists():raise FileExistsError('preserve original native attempt')
    binding=json.loads((ROOT/(attempt+'-binding.json')).read_text(encoding="utf-8"));identity=binding['identity']
    comp=json.loads((ROOT/(attempt+'-component.json')).read_text(encoding="utf-8"))
    loader=json.loads((ROOT/(attempt+'-loader-binding.json')).read_text(encoding="utf-8"))
    target=debugger.GetSelectedTarget();process=target.GetProcess();base=int(identity['base'],0)
    r={'errors':[],'publication':None,'native_calls':False,'initialization_only':not binding.get('source_execution',False),
       'source_replay_submitted':False,'scene_attached':False,'detached':False,
       'component_unloaded':False,'network_settings_changed':False,'online_match_started':False}
    functions={};regions=[];handle=0
    def save():output.write_text(json.dumps(r,indent=2)+'\n')
    def memory(p,n):
        error=lldb.SBError();raw=process.ReadMemory(p&0x00ffffffffffffff,n,error)
        if not error.Success() or len(raw)!=n:raise RuntimeError('short native observation')
        return raw
    def ptr(p):return struct.unpack('<Q',memory(p,8))[0]
    def public():
        root=ptr(base+0x1d34ae0)
        if root!=int(binding['root_raw'],0) or ptr(root+0x20)!=int(binding['services_raw'],0):
            raise RuntimeError('public resource generation changed')
    expression=None
    def call(name,args=''):
        signature='int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)' if name.endswith('_start') else 'int(*)()' if name.endswith('_release') else 'unsigned long long(*)()'
        return expression(functions[name],signature,args,not name.endswith('_start'))
    debugger.SetAsync(False)
    try:
        from native_expression import NativeExpression
        expression=NativeExpression(debugger,identity,loader,comp)
        if process.GetProcessID()!=identity['pid']:raise RuntimeError('wrong process')
        if loader['identity']!=identity:raise RuntimeError('wrong loader generation')
        for pin in identity['jni_exports']:
            if hashlib.sha256(memory(base+int(pin['va'],0),pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('JNI changed')
        for pin in binding['pins']:
            if hashlib.sha256(memory(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('native code changed')
        for pin in loader['exports'].values():
            if hashlib.sha256(memory(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('loader changed')
        public();r['native_calls']=True
        handle=expression(int(loader['exports']['dlopen']['address'],0),'void*(*)(const char*,int)',json.dumps(comp['device_path'])+',2',False)
        r['owned_loader_handle']=hex(handle);save()
        if not handle:raise RuntimeError('native component load failed')
        maps=ReadOnlySession(identity).verify();headers=[]
        for line in maps.splitlines():
            fields=line.split()
            if len(fields)<6 or fields[-1]!=comp['device_path']:continue
            lo,hi=(int(v,16) for v in fields[0].split('-'));regions.append((lo,hi))
            if int(fields[2],16)==0 and 'r' in fields[1]:headers.append(lo)
        from mapped_elf import load_bias
        from elf_contract import Elf
        module=load_bias(maps.splitlines(),comp['device_path'],Elf(Path(comp['local_path']).read_bytes()))
        if memory(module,64)!=Path(comp['local_path']).read_bytes()[:64]:raise RuntimeError('component ELF differs')
        for name,pin in comp['exports'].items():
            address=module+int(pin['va'],0)
            if hashlib.sha256(memory(address,pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('component code differs')
            functions[name]=address
        expression.authorize_component(functions)
        public()
        r['publication']=call('cr_web_bootstrap_start','%sULL,%d,%dULL,%sULL,%sULL'%(
            identity['base'],identity['pid'],binding['worker_tid'],binding['worker_handle'],binding['services_raw']))
        save()
        if r['publication']!=1:raise RuntimeError('task rejected; do not resubmit')
        done=call('cr_web_bootstrap_done_address');r['completion_address']=hex(done);save()
        if not done:raise RuntimeError('missing original completion handle')
        debugger.SetAsync(True)
        if not process.Continue().Success():raise RuntimeError('resume failed')
        complete=False
        for _ in range(60):
            time.sleep(.5)
            if process.GetState()!=lldb.eStateRunning:raise RuntimeError('native process stopped; preserve failure graph')
            session=ReadOnlySession(identity);finished=struct.unpack('<I',session.read(done,4))[0];session.verify()
            if finished not in (0,1):raise RuntimeError('invalid completion flag')
            if finished:complete=True;break
        if not process.Stop().Success():raise RuntimeError('cannot stop for observation')
        until=time.monotonic()+3
        while process.GetState()==lldb.eStateRunning and time.monotonic()<until:time.sleep(.02)
        debugger.SetAsync(False)
        if not complete or process.GetState()!=lldb.eStateStopped:raise RuntimeError('original task pending; retain handle')
        result=call('cr_web_bootstrap_result_address')
        f=list(struct.unpack('<96Q',memory(result,768)));r['fields']=f;save()
        if 'cr_web_bootstrap_towers_address' in functions:
            address=call('cr_web_bootstrap_towers_address')
            if not address:raise RuntimeError('missing initial tower evidence')
            values=struct.unpack('<48Q',memory(address,384))
            r['initial_towers']=[dict(zip(('owner','data_id','x','y','hp','max_hp','level_index','king'),values[i:i+8])) for i in range(0,48,8)]
            save()
        if binding.get('source_execution') and f[4]==0:
            source_address=call('cr_web_source_text_address');source_size=call('cr_web_source_text_size')
            if not source_address or not 0<source_size<262144:raise RuntimeError('missing bounded source execution report')
            source=json.loads(memory(source_address,source_size).decode())
            with (ROOT/(attempt+'-source-execution.json')).open('x',encoding='utf-8') as stream:json.dump(source,stream,indent=2)
            r['source_execution']={k:v for k,v in source.items() if k not in ('commands','diagnostics','dispatch')}
            r['source_commands_generated']=len(source['commands'])
        rejected=f[:5]==[1,1,1,1,30] and f[87]==1 and not any(f[80:87])
        initialized=f[:4]==[1,1,1,1] and f[4]==0 and f[6:8]==[1,4] and f[9:16]==[1,2,1,1,1,1,6] and not any(f[80:83]) and f[83]==1 and f[88:94]==[5,0,0,2,4,0]
        clean_deal_failure=f[:4]==[1,1,1,1] and f[4] in (41,42,43,44) and f[6:8]==[1,4] and f[12:15]==[1,1,1] and not any(f[80:83]) and f[83]==1 and f[88:94]==[5,0,0,2,4,0]
        if not rejected and not initialized and not clean_deal_failure:
            raise RuntimeError('source native initialization/cleanup verification failed')
        r['resource_preflight_rejected']=rejected
        public()
        r['component_frames']=[{'tid':t.GetThreadID(),'pc':hex(frame.GetPC())} for t in process for frame in t if any(lo<=frame.GetPC()<hi for lo,hi in regions)]
        if r['component_frames']:raise RuntimeError('component still on a worker stack')
        r['observer_released']=call('cr_web_bootstrap_release')==1
        if not r['observer_released']:raise RuntimeError('release refused')
        if expression.translated:
            # ARM return addresses are invisible to the host-only backtrace.
            # Keep code mapped through process exit after releasing data owners.
            r.update(mumu_module_retained_safe=True,module_retained_for_translated_return_safety=True,
                retained_component_path=comp['device_path'],retained_component_sha256=comp['sha256'])
        else:
            close=expression(int(loader['exports']['dlclose']['address'],0),'int(*)(void*)','(void*)'+hex(handle)+'ULL')
            if close!=0:raise RuntimeError('owned loader release failed')
            r['owned_loader_reference_released']=True
            if comp['device_path'] in ReadOnlySession(identity).verify():raise RuntimeError('component remains mapped')
            r['component_unloaded']=True
        r['source_bootstrap_verified']=initialized
        if clean_deal_failure:r['errors'].append('原生初始牌序校验失败；已释放私有对局数据')
        if binding.get('source_execution') and initialized:
            r['private_source_execution_complete']=source_completed(source,binding['source_event_count'])
            if not r['private_source_execution_complete']:
                r['errors'].append(source_failure(source))
                if source.get('error')==112 and source.get('native_code',0)>1:
                    r['source_search_candidate_released']=True
        if rejected:r['errors'].append('Typed Location15000061 cache lease precondition rejected; parser not called')
    except BaseException as error:
        r['errors'].append(type(error).__name__+': '+str(error))
        if process.IsValid() and process.GetState()==lldb.eStateStopped:
            r['stopped_threads']=[{'tid':t.GetThreadID(),'reason':t.GetStopDescription(256),
                'frames':[{'pc':hex(f.GetPC()),'function':f.GetFunctionName()} for f in list(t)[:12]]}
                for t in process if t.GetStopReason() not in (lldb.eStopReasonNone,lldb.eStopReasonInvalid)]
            if 'cr_web_bootstrap_result_address' in functions:
                try:
                    address=call('cr_web_bootstrap_result_address')
                    f=list(struct.unpack('<96Q',memory(address,768)));r['failure_fields']=f
                    if f[80]:
                        d=f[80];battle=ptr(d+0xa8)
                        graph={'domain_mode':struct.unpack('<i',memory(d+0x20,4))[0],
                               'tick':struct.unpack('<i',memory(d+0x60,4))[0],'battle':hex(battle)}
                        if battle:
                            graph['side_count']=struct.unpack('<i',memory(battle+0x60,4))[0]
                            graph['roots']=[hex(ptr(battle+0xe0+i*8)) for i in (0,1)]
                            graph['decks']=[]
                            for side in (0,1):
                                deck=ptr(battle+0x88+side*8)
                                graph['decks'].append({'deck':hex(deck),
                                    'aux_count':struct.unpack('<i',memory(deck+0x4c,4))[0] if deck else None})
                        r['private_failure_graph']=graph
                except Exception as capture_error:r['failure_capture_error']=str(capture_error)
    finally:
        debugger.SetAsync(False)
        if process.IsValid() and process.GetState()==lldb.eStateRunning:process.Stop()
        if process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):
            r['detached']=process.Detach().Success()
        save();print(json.dumps({'errors':r['errors'],'publication':r['publication'],
            'source_bootstrap_verified':r.get('source_bootstrap_verified',False),'detached':r['detached']}))
