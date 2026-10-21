"""Explicit, recorded translation-only build shims; upstream sources stay intact."""
import hashlib
import json
from pathlib import Path

from mumu_runtime import bound_imports

def adapt(session,out,source):
    root=source.parent;imports=bound_imports(session)
    runtime=(root.parent/'runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp').read_text(encoding='utf-8')
    old='unsigned long long low{},high{}; char mode[5]{};'
    new='unsigned long long low{},high{},offset{}; char mode[5]{},path[1536]{};'
    if runtime.count(old)!=1:raise ValueError('upstream runtime map declaration changed')
    runtime=runtime.replace(old,new)
    for name,address in imports.items():
        token='reinterpret_cast<uintptr_t>(&'+name+')'
        runtime=runtime.replace(token,hex(address)+'ULL')
    old='if (std::sscanf(line,"%llx-%llx %4s",&low,&high,mode)!=3) continue;'
    new='if (std::sscanf(line,"%llx-%llx %4s %llx %*s %*s %1535s",&low,&high,mode,&offset,path)<4) continue;'
    if runtime.count(old)!=1:raise ValueError('upstream runtime map parser changed')
    runtime=runtime.replace(old,new).replace('char line[1024]','char line[2048]')
    old='for (const char* r=required;*r;++r) if (!std::strchr(mode,*r)) permitted=false;'
    new='''const bool guest_code=!std::strcmp(required,"rx") && low==mumu_base && high-low==0x1b3d000 &&
            offset==0x284d000 && !std::strcmp(path,mumu_apk) && !std::strcmp(mode,"r--p") &&
            p>=mumu_base && p+size<=mumu_base+0x1b3d000;
        for (const char* r=required;*r;++r) if (!std::strchr(mode,*r) && !(guest_code && *r=='x')) permitted=false;'''
    if runtime.count(old)!=1:raise ValueError('upstream runtime permission guard changed')
    runtime=runtime.replace(old,new)
    prefix='#include <stdint.h>\nstatic constexpr uintptr_t mumu_base='+hex(session.base)+'ULL;\nstatic const char* mumu_apk='+json.dumps(session.identity['apk'])+';\n'
    runtime_path=out/'mumu_runtime_probe.cpp';runtime_path.write_text(prefix+runtime,encoding='utf-8')
    original=source.read_text(encoding='utf-8')
    include='#include "../runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp"'
    if original.count(include)!=1:raise ValueError('upstream runtime include changed')
    adapted=original.replace(include,'#include '+json.dumps(runtime_path.as_posix()))
    if source.name=='native_bootstrap_probe.cpp':
        # Combine four existing completed-task getters into one typed bridge
        # call. The audited task/engine and its cleanup guards stay unchanged.
        adapted+='''
extern "C" __attribute__((visibility("default"))) uintptr_t cr_web_bootstrap_snapshot_address(){
    static uintptr_t values[4]{};
    if(!probe||!probe->destroyed)return 0;
    values[0]=cr_web_bootstrap_result_address();
    values[1]=cr_web_bootstrap_towers_address();
    values[2]=cr_web_source_text_address();
    values[3]=cr_web_source_text_size();
    return reinterpret_cast<uintptr_t>(values);
}
'''
    compiled=out/('mumu_'+source.name);compiled.write_text(adapted,encoding='utf-8')
    wrappers=out/'mumu_libc_wrappers.cpp'
    declarations=['#include <stdlib.h>','#include <pthread.h>']
    for name,address in imports.items():
        result,arg,arg_type=('void*','size_t n','size_t') if name=='malloc' else ('void','void* p','void*') if name=='free' else (
            'int','pthread_cond_t* p','pthread_cond_t*') if name=='pthread_cond_signal' else ('int','pthread_mutex_t* p','pthread_mutex_t*')
        value='n' if name=='malloc' else 'p'
        declarations.append('extern "C" __attribute__((visibility("hidden"))) '+result+' __wrap_'+name+'('+arg+') {return reinterpret_cast<'+result+'(*)('+arg_type+')>('+hex(address)+'ULL)('+value+');}')
    wrappers.write_text('\n'.join(declarations)+'\n',encoding='utf-8')
    flags=['-I',str(root),str(wrappers)]+['-Wl,--wrap='+name for name in imports]
    evidence=dict(game_imports=imports,original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        adapted_sha256=hashlib.sha256(compiled.read_bytes()).hexdigest(),runtime_shim_sha256=hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        mapping_policy='exact-pinned-game-mapping-only',libc_binding='verified-game-import-typed-wrappers',
        libc_wrappers_sha256=hashlib.sha256(wrappers.read_bytes()).hexdigest())
    return compiled,flags,evidence
