"""Phone compiler/debugger self-check against OUR synthetic child only.

Never attaches to the game, makes game calls, or changes network settings.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback
import subprocess
import struct
from elf_contract import Elf
from device_expression import evaluate
from mumu_compiler import run as compiler_run
from mumu_platform import enabled as mumu_enabled, host_binary


def needed(raw):
    elf=Elf(raw)
    dynamic=[p for p in elf.programs if p[0]==2]
    if len(dynamic)!=1:raise ValueError('one bounded dynamic table required')
    p=dynamic[0];data=elf.slice(p[2],p[5]);entries=[]
    if len(data)>65536 or len(data)%16:raise ValueError('invalid dynamic table')
    for offset in range(0,len(data),16):
        tag,value=struct.unpack_from('<QQ',data,offset)
        if not tag:break
        entries.append((tag,value))
    strings=[value for tag,value in entries if tag==5];sizes=[value for tag,value in entries if tag==10]
    if len(strings)!=1 or len(sizes)!=1 or sizes[0]>1048576:raise ValueError('invalid dynamic strings')
    text=elf.at(strings[0],sizes[0]);names=[]
    for tag,value in entries:
        if tag!=1:continue
        end=text.find(b'\0',value)
        if end<value:raise ValueError('invalid needed library name')
        names.append(text[value:end].decode('ascii'))
    return names


def compiler_flags(prefix):
    flags=[str(prefix/'bin/clang++'),'--target=aarch64-linux-android24','--sysroot='+str(prefix),
           '-isystem',str(prefix/'include/c++/v1'),'-isystem',str(prefix/'include/aarch64-linux-android'),'-isystem',str(prefix/'include'),
           '-resource-dir='+str(prefix/'lib/clang/21'),'-B'+str(prefix/'bin'),'--ld-path='+str(prefix/'bin/ld.lld'),
           '-L'+str(prefix/'lib'),'-L'+str(prefix/'lib/stubs'),
           '-std=c++17','-O2','-g','-Wall','-Wextra','-Werror','-nostdlib++',
           '-fvisibility=hidden','-Wl,--exclude-libs,ALL','-Wl,-z,defs']
    runtime=['-Wl,--start-group',str(prefix/'lib/libc++_static.a'),str(prefix/'lib/libc++abi.a'),
             str(prefix/'lib/libunwind.a'),'-Wl,--end-group','-lm','-ldl']
    return flags,runtime


def compile_check(prefix, destination):
    code=destination/'compiler-check.cpp'
    code.write_text('#include <vector>\n#include <string>\n#include <algorithm>\n'
                    'extern "C" __attribute__((visibility("default"))) int cr_phone_compiler_check(int n) '
                    '{std::vector<int> v{n,2,5}; std::sort(v.begin(),v.end()); std::string s="test"; return v[0]+v[1]+v[2]+int(s.size())-4;}\n')
    flags,runtime=compiler_flags(prefix)
    library=destination/'libcompiler_check.so'
    with (destination/'compile.log').open('x') as log:
        compiler_run([*flags,'-fPIC','-shared',str(code),*runtime,'-o',str(library)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
        child_source=destination/'child.cpp'
        child_source.write_text('#include <unistd.h>\nextern "C" __attribute__((visibility("default"),noinline)) int cr_phone_test_value(int n){return n+7;}\nint main(){for(;;)usleep(10000);}\n')
        executable=destination/'debug-child'
        compiler_run([*flags,'-fPIE','-pie','-Wl,--export-dynamic',str(child_source),*runtime,'-o',str(executable)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
    if 'libc++_shared.so' in needed(library.read_bytes()):raise ValueError('phone component must not depend on shared C++ runtime')
    module=ctypes.CDLL(str(library));function=module.cr_phone_compiler_check
    function.argtypes=[ctypes.c_int];function.restype=ctypes.c_int
    if function(37)!=44:raise ValueError('phone-compiled C++ library result differs')
    return executable,hashlib.sha256(library.read_bytes()).hexdigest()


def check_own_child(lldb, debugger, executable, destination):
    environment=dict(os.environ)
    if mumu_enabled():
        for key in ('LD_LIBRARY_PATH','LD_PRELOAD'):environment.pop(key,None)
    child=subprocess.Popen([str(executable)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=environment)
    process=None;target=None;attachment=None
    try:
        if child.poll() is not None:raise RuntimeError('owned synthetic child exited before attach')
        target=debugger.CreateTarget(str(executable))
        if not target.IsValid():raise ValueError('synthetic ELF target could not be created')
        error=lldb.SBError()
        # This PID comes only from the child we just created, never input HTML,
        # user text, a process search, or the official game package.
        if mumu_enabled():
            from mumu_debugger import Attachment
            with (destination/'server.log').open('x') as log:
                attachment=Attachment(lldb,target,debugger.GetListener(),child.pid,log)
            process=attachment.process
        else:process=target.AttachToProcessWithID(debugger.GetListener(),child.pid,error)
        if not error.Success() or not process.IsValid():raise RuntimeError('own-child attach failed: '+str(error))
        if process.GetProcessID()!=child.pid:raise ValueError('synthetic child identity differs')
        found=target.FindFunctions('cr_phone_test_value')
        if found.GetSize()!=1:raise ValueError('synthetic function is not unique')
        address=found.GetContextAtIndex(0).GetFunction().GetStartAddress().GetLoadAddress(target)
        if address==lldb.LLDB_INVALID_ADDRESS:raise ValueError('synthetic function not mapped')
        evidence={}
        try:value=evaluate(lldb,target,process,child.pid,'((int(*)(int))%dULL)(37)'%address,evidence=evidence)
        finally:
            with (destination/'native-expression.json').open('x') as stream:json.dump(evidence,stream,indent=2)
        if value!=44:raise RuntimeError('own-child native expression result differs')
        if attachment:attachment.close();attachment=None
        elif not process.Detach().Success():raise RuntimeError('own-child debugger detach failed')
        return True
    finally:
        if attachment:attachment.close()
        if process and process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):process.Detach()
        if target and target.IsValid():debugger.DeleteTarget(target)
        if child.poll() is None:child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=5)  # only our exact synthetic child


def run(prefix, destination):
    destination.mkdir(exist_ok=False, mode=0o700)
    try:
        temporary=destination/'tmp';temporary.mkdir(mode=0o700)
        os.environ['TMPDIR']=str(temporary)
        os.environ['HOME']=str(destination)
        executable,compiled_sha=compile_check(prefix,destination)
        site=prefix/'lib/python3.14/site-packages'
        sys.path.insert(0,str(site))
        # Termux's SOABI filename differs from PSF's Android SOABI. Loading the
        # exact same verified ELF explicitly avoids modifying it or another app.
        binary=prefix/'lib/liblldb.so'
        spec=importlib.util.spec_from_file_location('_lldb',str(binary))
        native=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        sys.modules['_lldb']=native
        sys.modules['lldb._lldb']=native
        import lldb
        version=lldb.SBDebugger.GetVersionString()
        if not version or 'lldb' not in version.lower():raise ValueError('debugger version missing')
        translated=mumu_enabled()
        os.environ['LLDB_DEBUGSERVER_PATH']=str(host_binary('lldb-server') if translated else prefix/'bin/lldb-server')
        lldb.SBDebugger.Initialize()
        debugger=lldb.SBDebugger.Create()
        debugger.SetAsync(False)
        try:
            if not debugger.IsValid() or debugger.GetNumTargets()!=0:raise ValueError('debugger self-check created an unexpected target')
            child_ok=check_own_child(lldb,debugger,host_binary('debug-child') if translated else executable,destination)
            report=dict(schema='royale-replay.android-debugger-check.v1',processing_location='android',
                        debugger_version=version,python_version=sys.version.split()[0],
                        debugger_loaded=True,empty_debugger_created=True,targets=0,
                        cpp_compiled_on_phone=True,cpp_static_runtime_verified=True,compiled_library_sha256=compiled_sha,
                        own_child_native_call_verified=child_ok,
                        own_child_arch='x86_64' if translated else 'aarch64',
                        own_child_built_on_phone=not translated,
                        game_attached=False,game_memory_written=False,native_game_calls=False,
                        termux_app_directory_modified=False,desktop_backend_used=False,
                        standalone_playback_ready=False)
        finally:
            lldb.SBDebugger.Destroy(debugger)
            lldb.SBDebugger.Terminate()
        with (destination/'result.json').open('x') as stream:json.dump(report,stream,indent=2)
        return report
    except Exception:
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        raise
    finally:
        owner=destination.parent.stat()
        for file in sorted(destination.rglob('*'),reverse=True):
            if file.is_symlink():raise ValueError('unexpected link in private tools check')
            os.chown(file,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)
