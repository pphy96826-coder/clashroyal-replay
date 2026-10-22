"""Canonical local native replay scene; keep resource/module owners until exit.

Start publishes exactly once. Observe never republishes. Cleanup is a separate
native-worker task, refused until ordinary lobby owns no replay/fade graph.
"""
import hashlib
import json
from pathlib import Path
import struct
import time
import lldb
from client_session import ReadOnlySession
from scene_start_contract import require_idle_lobby,battle_observation_ready
from tower_profiles import bindings
from signal_policy import foreign_signal

ROOT=Path(__file__).resolve().parent


def run(debugger,attempt,action,receipt):
    output=ROOT/(receipt+'-result.json')
    if output.exists():raise FileExistsError('preserve original scene receipt')
    binding=json.loads((ROOT/(attempt+'-binding.json')).read_text())
    comp=json.loads((ROOT/(attempt+'-component.json')).read_text())
    loader=json.loads((ROOT/(attempt+'-loader-binding.json')).read_text())
    identity=binding['identity'];base=int(identity['base'],0)
    tower_types={e['data_id']&0xffffffff for row in bindings(json.loads(Path(binding['preparation_path']).read_text())) for e in row['spawn_entries']}
    target=debugger.GetSelectedTarget();process=target.GetProcess()
    result={'errors':[],'action':action,'publication':None,'detached':False,
            'scene_playback_verified':False,'network_settings_changed':False,'online_match_started':False}
    functions={};regions=[];handle=0

    def save():output.write_text(json.dumps(result,indent=2)+'\n')
    def memory(address,size):
        error=lldb.SBError();data=process.ReadMemory(address&0x00ffffffffffffff,size,error)
        if not error.Success() or len(data)!=size:raise RuntimeError('short bounded scene observation')
        return data
    def pointer(address):return struct.unpack('<Q',memory(address,8))[0]
    def expression(address,signature,args='',stop_others=True):
        if process.GetProcessID()!=identity['pid'] or process.GetState()!=lldb.eStateStopped:
            raise RuntimeError('native expression requires the bound stopped process')
        thread=process.GetThreadByID(identity['pid'])
        if not thread.IsValid():raise RuntimeError('main thread absent')
        if not process.SetSelectedThread(thread):raise RuntimeError('native expression main thread selection failed')
        frame=thread.GetFrameAtIndex(0)
        if not frame.IsValid() or frame.GetThread().GetThreadID()!=identity['pid']:
            raise RuntimeError('native expression bound main-thread frame absent')
        options=lldb.SBExpressionOptions();options.SetLanguage(lldb.eLanguageTypeC);options.SetAllowJIT(True)
        options.SetTimeoutInMicroSeconds(5000000);options.SetIgnoreBreakpoints(True)
        options.SetUnwindOnError(True);options.SetStopOthers(stop_others)
        result['native_expression']={'process_state':process.GetState(),'target_triple':target.GetTriple(),
                                     'thread_id':identity['pid'],'frame_pc':hex(frame.GetPC()),'native_call_completed':False}
        value=frame.EvaluateExpression('((%s)%dULL)(%s)'%(signature,address,args),options)
        if not value.GetError().Success():
            result['native_expression']['error']=str(value.GetError())[:2000];save()
            raise RuntimeError('native expression failed: '+str(value.GetError()))
        result['native_expression']['native_call_completed']=True
        return value.GetValueAsUnsigned()
    def call(name,args=''):
        signature='int(*)(unsigned long long,int,unsigned long long,unsigned long long,unsigned long long)' if name=='start' else 'int(*)()' if name in ('cleanup','release','return_lobby') else 'unsigned long long(*)()'
        return expression(functions['cr_web_scene_'+name],signature,args,name not in ('start','cleanup','return_lobby'))
    def snapshot():
        address=call('result_address')
        if not address:raise RuntimeError('original scene owner is absent')
        fields=list(struct.unpack('<48Q',memory(address,384)));result['fields']=fields
        result['scene_state']={
            'controller':hex(fields[15]),'auxiliary_controller':hex(fields[16]),
            'manager_state':fields[17],'pending_request':fields[18],
            'kind':fields[20],'state':fields[21],'scene':hex(fields[22]),
            'domain':hex(fields[23]),'domain_mode':fields[24],'tick':fields[25],
            'battle':hex(fields[26]),'observed_replay_controller':hex(fields[27])}
        # Snapshot evidence is not proof of displayed pixels or whole playback.
        result['native_replay_scene_present']=battle_observation_ready(fields)
        result['local_driver']={'bound':fields[28],'error':fields[29],'frames':fields[30],'terminal_tick':fields[31]}
        if fields[38]:result['diagnostic_preview']={'diagnostic_only':True,'frozen':bool(fields[37]),'stop_tick':fields[38],'complete_replay_verified':False}
        result['playback_clock']={'speed':struct.unpack('<f',struct.pack('<I',fields[35]))[0],
                                  'pause_flag':bool(fields[36])}
        result['battlefield_presentation']={'frames':fields[32],'handle':fields[33],'object':hex(fields[34])}
        if 'cr_web_scene_trace_address' in functions:
            trace=call('trace_address');size=call('trace_size')
            if not trace or not 0<size<65536:raise RuntimeError('invalid bounded source execution trace')
            result['source_dispatch']=json.loads(memory(trace,size).decode())
        if battle_observation_ready(fields):
            battle=fields[26];objects=pointer(fields[23]+0x40)
            result['battle_object_count']=struct.unpack('<i',memory(objects+0x14,4))[0]
            result['battle_terminal']=bool(expression(base+0xf5603c,'int(*)(void*)','(void*)'+hex(battle)+'ULL'))
            count=result['battle_object_count']
            if not 0<=count<=1024:raise RuntimeError('invalid bounded battle object count')
            entries=struct.unpack('<'+str(count)+'Q',memory(pointer(objects+8),count*8)) if count else ()
            towers=[]
            for obj in entries:
                definition=pointer(obj+0x48)
                data_id=struct.unpack('<I',memory(definition+0x40,4))[0] if definition else 0
                if data_id not in tower_types:continue
                owner,x,y=struct.unpack('<iii',memory(obj+0x78,12))
                size=struct.unpack('<i',memory(obj+0x24,4))[0]
                if owner not in (0,1) or not 0<size<=64:raise RuntimeError('invalid native tower graph')
                components=struct.unpack('<'+str(size)+'Q',memory(pointer(obj+0x18),size*8))
                health=[p for p in components if p and pointer(p)==base+0x1c26f70]
                if len(health)!=1:raise RuntimeError('ambiguous native tower health')
                hp=struct.unpack('<i',memory(health[0]+0x10,4))[0]
                maximum=struct.unpack('<i',memory(health[0]+0x20,4))[0]
                towers.append(dict(owner=owner,data_id=data_id,x=x,y=y,hp=hp,max_hp=maximum))
            result['active_towers']=towers
            result['tower_snapshot_note']='Active native objects only; an absent tower is not silently assigned zero HP.'
        save()
        if fields[29]:raise RuntimeError('local replay driver stopped at guard '+str(fields[29]))
        return fields
    debugger.SetAsync(False)
    try:
        if not binding.get('scene') or loader['identity']!=identity or process.GetProcessID()!=identity['pid']:
            raise RuntimeError('wrong scene/client generation')
        for pin in identity['jni_exports']:
            if hashlib.sha256(memory(base+int(pin['va'],0),pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('JNI changed')
        for group in (binding['pins'],list(loader['exports'].values())):
            for pin in group:
                if hashlib.sha256(memory(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('native binding changed')
        root=pointer(base+0x1d34ae0)
        services=pointer(root+0x20)
        result['resource_binding']={'expected_root':binding['root_raw'],'actual_root':hex(root),
                                    'expected_services':binding['services_raw'],'actual_services':hex(services)}
        if root!=int(binding['root_raw'],0) or services!=int(binding['services_raw'],0):raise RuntimeError('resource generation changed')
        maps=ReadOnlySession(identity).verify()
        if action=='start':
            manager=pointer(base+0x1d46bd0);controller=pointer(manager+0x28)
            kind=struct.unpack('<i',memory(controller+0x58,4))[0]
            state=struct.unpack('<i',memory(controller+0x30,4))[0]
            domain=pointer(controller+0x90)
            mode=struct.unpack('<i',memory(domain+0x20,4))[0] if domain else None
            battle=pointer(domain+0xa8) if domain else 0
            result['start_precondition']={'controller_vtable_va':hex(pointer(controller)-base),
                'kind':kind,'state':state,'domain_mode':mode,'battle_present':bool(battle),
                'pending_request':struct.unpack('<i',memory(manager+0x3c,4))[0],
                'auxiliary_present':bool(pointer(manager+0x20))}
            require_idle_lobby(result['start_precondition'])
            if comp['device_path'] in maps:raise RuntimeError('scene already loaded; never restart original task')
            handle=expression(int(loader['exports']['dlopen']['address'],0),'void*(*)(const char*,int)',json.dumps(comp['device_path'])+',2',False)
            result['owned_loader_handle']=hex(handle);save()
            if not handle:raise RuntimeError('scene component load failed')
            maps=ReadOnlySession(identity).verify()
        else:
            original=json.loads((ROOT/(attempt+'-result.json')).read_text())
            handle=int(original['owned_loader_handle'],0)
            result['owned_loader_handle']=hex(handle)
        headers=[]
        for line in maps.splitlines():
            parts=line.split()
            if len(parts)<6 or parts[-1]!=comp['device_path']:continue
            low,high=(int(v,16) for v in parts[0].split('-'));regions.append((low,high))
            if int(parts[2],16)==0 and 'r' in parts[1]:headers.append(low)
        if len(headers)!=1:raise RuntimeError('original scene component mapping absent or ambiguous')
        module=headers[0]
        if memory(module,64)!=Path(comp['local_path']).read_bytes()[:64]:raise RuntimeError('component ELF changed')
        for name,pin in comp['exports'].items():
            address=module+int(pin['va'],0)
            if hashlib.sha256(memory(address,pin['size'])).hexdigest()!=pin['sha256']:raise RuntimeError('component export changed')
            functions[name]=address
        if action=='start':
            result['publication']=call('start','%sULL,%d,%dULL,%sULL,%sULL'%(
                identity['base'],identity['pid'],binding['worker_tid'],binding['worker_handle'],binding['services_raw']))
        elif action in ('cleanup','return-lobby'):
            prior=snapshot()
            if prior[2]!=1:raise RuntimeError('original task pending; do not publish cleanup')
            if action=='return-lobby' and not result.get('battle_terminal'):raise RuntimeError('terminal replay required before lobby return')
            result['publication']=call('return_lobby' if action=='return-lobby' else 'cleanup')
        else:snapshot()
        save()
        if action!='observe':
            if result['publication']!=1:raise RuntimeError('scene task rejected; do not resubmit')
            done=call('done_address');result['completion_address']=hex(done);save()
            debugger.SetAsync(True)
            if not process.Continue().Success():raise RuntimeError('resume failed')
            complete=False
            # Phone VMs load the battle scene far slower than MuMu (seen >15 s).
            passed=result.setdefault('passed_signals',[])
            for _ in range(180):
                time.sleep(.5)
                # A game-runtime signal on a thread outside our component is
                # handed back unchanged; anything else still fails closed.
                if process.GetState()==lldb.eStateStopped and len(passed)<256:
                    stop=foreign_signal(lldb,process,regions)
                    if stop is not None:
                        passed.append(stop);save()
                        if not process.Continue().Success():raise RuntimeError('resume after game signal failed')
                        until=time.monotonic()+3
                        while process.GetState()==lldb.eStateStopped and time.monotonic()<until:time.sleep(.02)
                        continue
                if process.GetState()!=lldb.eStateRunning:raise RuntimeError('native scene stopped; preserve ownership')
                session=ReadOnlySession(identity)
                finished=struct.unpack('<I',session.read(done,4))[0];session.verify()
                if finished not in (0,1):raise RuntimeError('invalid original completion flag')
                if finished:complete=True;break
            if not process.Stop().Success():raise RuntimeError('cannot stop for scene observation')
            until=time.monotonic()+3
            while process.GetState()==lldb.eStateRunning and time.monotonic()<until:time.sleep(.02)
            debugger.SetAsync(False)
            if not complete or process.GetState()!=lldb.eStateStopped:raise RuntimeError('original scene task pending; retain module')
            fields=snapshot()
            if fields[4]:raise RuntimeError('native scene task failure '+str(fields[4]))
            if action=='cleanup':
                if fields[7]!=1:raise RuntimeError('replay/fade graph still owned; cleanup correctly deferred')
                frames=[{'tid':t.GetThreadID(),'pc':hex(f.GetPC())} for t in process for f in t if any(lo<=f.GetPC()<hi for lo,hi in regions)]
                if frames:raise RuntimeError('scene component still on native stack')
                if call('release')!=1:raise RuntimeError('scene owner release refused')
                if expression(int(loader['exports']['dlclose']['address'],0),'int(*)(void*)','(void*)'+hex(handle)+'ULL')!=0:raise RuntimeError('owned reference close failed')
                if comp['device_path'] in ReadOnlySession(identity).verify():raise RuntimeError('scene component remains mapped')
                result['component_unloaded']=True
    except BaseException as error:
        result['errors'].append(type(error).__name__+': '+str(error))
        if process.IsValid() and process.GetState()==lldb.eStateStopped:
            result['stopped_threads']=[{'tid':t.GetThreadID(),'reason':t.GetStopDescription(256),
                'frames':[{'pc':hex(f.GetPC()),'name':f.GetFunctionName()} for f in list(t)[:16]]}
                for t in process if t.GetStopReason() not in (lldb.eStopReasonNone,lldb.eStopReasonInvalid)]
    finally:
        debugger.SetAsync(False)
        if process.IsValid() and process.GetState()==lldb.eStateRunning:process.Stop()
        if process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):result['detached']=process.Detach().Success()
        save();print(json.dumps({'errors':result['errors'],'publication':result['publication'],
                               'native_replay_scene_present':result.get('native_replay_scene_present',False),'detached':result['detached']}))
