"""Bounded read-only SB API evidence; never evaluates or runs target code.

This is not an execution-capability test or authorization to release a task.
Register *availability* is recorded, never the register contents.
"""
from pathlib import PurePosixPath


def snapshot(lldb, target, process, pid, maps):
    result=dict(schema='royale-replay.debugger-compatibility.v1',read_only=True,
                target_code_executed=False,register_contents_collected=False,errors=[])
    errors=result['errors']
    def error(area,exc):
        if len(errors)<16:errors.append(dict(area=area,error=str(exc)[:400]))
    try:
        if not process.IsValid() or process.GetProcessID()!=pid:
            raise ValueError('process identity differs')
        bound=target.GetProcess()
        if not bound.IsValid() or bound.GetProcessID()!=pid:
            raise ValueError('target identity differs')
        result.update(process_state=process.GetState(),target_triple=target.GetTriple(),
                      address_bytes=target.GetAddressByteSize())
        if process.GetState()!=lldb.eStateStopped:
            result['observation_skipped']='process is not stopped; not interrupted or resumed'
            return result
    except Exception as exc:
        error('identity',exc);return result
    regions=[]
    for line in maps.splitlines()[:8192]:
        fields=line.split(maxsplit=5)
        try:
            if len(fields)<5:continue
            low,high=(int(v,16) for v in fields[0].split('-'))
            if low>=high:continue
            regions.append((low,high,fields[1],fields[5] if len(fields)==6 else ''))
        except (ValueError,IndexError):continue
    def location(address):
        rows=[dict(permissions=mode,path=path[:600]) for low,high,mode,path in regions if low<=address<high]
        return rows[:4]
    def path(spec):
        directory=spec.GetDirectory() or '';name=spec.GetFilename() or ''
        return str(PurePosixPath(directory)/name)[:600] if name else ''
    result['modules']=[]
    try:
        count=target.GetNumModules();result['module_count']=count
        result['modules_scan_truncated']=count>256
        for index in range(min(count,256)):
            module=target.GetModuleAtIndex(index)
            local=path(module.GetFileSpec());platform=path(module.GetPlatformFileSpec())
            names={PurePosixPath(v).name for v in (local,platform)}
            if not names.intersection({'libc.so','libdl.so','linker64','app_process64'}):continue
            if len(result['modules'])<16:
                result['modules'].append(dict(local_path=local,platform_path=platform,triple=module.GetTriple()))
    except Exception as exc:error('modules',exc)
    result['symbols']={}
    for name in ('mmap','munmap','dlopen'):
        entry=dict(candidates=[],name_lookup_only=True)
        result['symbols'][name]=entry
        try:
            found=target.FindFunctions(name,lldb.eFunctionNameTypeFull)
            count=found.GetSize();entry['count']=count;entry['truncated']=count>8
            for index in range(min(count,8)):
                context=found.GetContextAtIndex(index)
                function=context.GetFunction();symbol=context.GetSymbol()
                if function.IsValid():address=function.GetStartAddress()
                elif symbol.IsValid():address=symbol.GetStartAddress()
                else:
                    entry['candidates'].append(dict(load_address_valid=False));continue
                loaded=address.GetLoadAddress(target)
                row=dict(load_address_valid=loaded!=lldb.LLDB_INVALID_ADDRESS)
                if row['load_address_valid']:
                    row.update(address=hex(loaded),mappings=location(loaded))
                entry['candidates'].append(row)
        except Exception as exc:error('symbol:'+name,exc)
    result['register_availability']={}
    try:
        thread=process.GetThreadByID(pid)
        if not thread.IsValid() or thread.GetThreadID()!=pid:raise ValueError('bound main thread absent')
        frame=thread.GetFrameAtIndex(0)
        if not frame.IsValid() or frame.GetThread().GetThreadID()!=pid:raise ValueError('bound main-thread frame absent')
        for name in ('x0','x8','sp','pc','cpsr','v0','fpsr','fpcr'):
            value=frame.FindRegister(name)
            row=dict(valid=value.IsValid())
            if row['valid']:
                # Force a bounded register read but never serialize its value.
                data=value.GetData();status=value.GetError();size=value.GetByteSize()
                row.update(readable=status.Success() and 0<size<=32 and data.GetByteSize()==size,byte_size=size)
                if not row['readable']:row['error']=str(status)[:300]
            result['register_availability'][name]=row
        result['register_note']='Individual reads do not prove full checkpoint/save/restore support.'
    except Exception as exc:error('registers',exc)
    mmap=result['symbols'].get('mmap',{})
    if mmap.get('count')==0:
        result['finding']='mmap_symbol_not_found_in_debugger'
    elif mmap.get('count',0)>0:
        executable=any('x' in region['permissions'] for row in mmap['candidates'] for region in row.get('mappings',[]))
        result['finding']='mmap_found_in_executable_mapping' if executable else 'mmap_symbol_mapping_not_verified'
    else:result['finding']='mmap_lookup_unknown'
    return result
