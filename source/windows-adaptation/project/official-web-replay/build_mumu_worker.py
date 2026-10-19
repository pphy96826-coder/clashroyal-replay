"""Build an immutable MuMu empty-task probe bound to one observed process."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--observation',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    from portable_config import translated,compiler_command,deployment_id
    from client_session import ReadOnlySession
    from elf_contract import Elf
    from mumu_runtime import allow_client_read
    if not translated():raise ValueError('explicit MuMu backend required')
    doc=json.loads(a.observation.read_text(encoding='utf-8'));identity=doc['identity']
    scene=doc['scene_state']
    if scene.get('state')!=9 or scene.get('battle_present') or scene.get('domain_mode')!=1:
        raise ValueError('an idle lobby is required')
    if identity['library_sha256']!='c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55':
        raise ValueError('unaudited game revision')
    session=ReadOnlySession(identity);session.verify()
    # Proxy functions are namespace-local addresses. Bind the actual game GOT,
    # then verify the matching complete ELF geometry and function bytes.
    from portable_config import runtime_dir
    from mapped_elf import load_bias
    slots=dict(malloc=0x1c72ba8,free=0x1c72bb0,pthread_mutex_lock=0x1c72de0,
        pthread_mutex_unlock=0x1c72df8,pthread_cond_signal=0x1c72e68,pthread_mutex_trylock=0x1c731b8)
    libc=Elf((runtime_dir()/'loader-libc.so').read_bytes());pins=libc.exports(set(slots))
    pointers={name:session.pointer(session.base+va) for name,va in slots.items()}
    libc_base=load_bias(session.verify().splitlines(),'/system/lib64/arm64/nb/libc.so',libc,
        anchor=(int(pins['malloc']['va'],0),pointers['malloc']))
    for name,pin in pins.items():
        address=libc_base+int(pin['va'],0)
        if address!=pointers[name] or hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:
            raise ValueError('game libc import differs: '+name)
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    header=out/'binding.h'
    values=dict(base=identity['base'],pid=str(identity['pid']),tid=str(doc['worker_tid']),
        handle=doc['worker_handle'],services=doc['services_raw'],root=doc['root_raw'])
    values.update({name:hex(address) for name,address in pointers.items()})
    header.write_text('#pragma once\n'+''.join('static constexpr uint64_t expected_'+k+'='+v+'ULL;\n' for k,v in values.items())+
        'static constexpr const char* expected_apk='+json.dumps(identity['apk'])+';\n',encoding='utf-8')
    binary=out/'librr_mumu_worker.so'
    cmd=compiler_command()+['-std=c++17','-O2','-g','-Wall','-Wextra','-Werror','-fPIC','-fvisibility=hidden',
        '-shared','-static-libstdc++','-Wl,--exclude-libs,ALL','-Wl,-z,defs',
        '-DMUMU_WORKER_BINDINGS='+json.dumps(header.as_posix()),str(ROOT/'mumu_worker_probe.cpp'),
        str(ROOT.parent/'offline-task-prototype/noop_task.cpp'),'-o',str(binary)]
    subprocess.run(cmd,check=True,timeout=45)
    raw=binary.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    exports=Elf(raw).exports({'rr_mumu_worker_'+n for n in ('start','snapshot','release')})
    folder='/data/local/tmp/royale_replay_'+deployment_id()+'_worker_'+digest[:12]
    if subprocess.run(session.adb+['shell','test','-e',folder],timeout=10).returncode!=1:
        raise RuntimeError('preserve existing diagnostic; never republish it')
    subprocess.run(session.adb+['shell','mkdir',folder],check=True,timeout=10)
    device=folder+'/'+binary.name
    subprocess.run(session.adb+['push',str(binary),device],check=True,timeout=15)
    if subprocess.check_output(session.adb+['shell','sha256sum',device],text=True,timeout=10).split()[0]!=digest:
        raise RuntimeError('diagnostic upload changed')
    allow_client_read(session.adb,[device]);session.verify()
    component=dict(local_path=str(binary),device_path=device,sha256=digest,exports=exports,game_imports=pointers)
    (out/'worker-binding.json').write_text(json.dumps(dict(observation=doc,component=component),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(built=True,binding=str(out/'worker-binding.json'),native_calls=False)))

if __name__=='__main__':main()
