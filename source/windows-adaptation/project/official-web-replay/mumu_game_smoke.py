"""Attach once to the user's exact game; handshake only owned native modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker-binding',type=Path);args=parser.parse_args()
    from portable_config import runtime_profile,runtime_dir,translated,debug_port,lldb_command
    from client_session import ensure_current_device_binding,ReadOnlySession
    from mapped_elf import game_mapping,load_bias
    from elf_contract import Elf
    from mumu_runtime import validate_device
    if not translated():raise ValueError('explicit MuMu backend required')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    profile=runtime_profile();device=ensure_current_device_binding();adb=['adb','-s',device['serial']]
    def text(*args):return subprocess.check_output(adb+list(args),text=True,timeout=15).strip()
    validate_device(adb)
    if text('shell','id','-u')!='0':raise RuntimeError('root debugging required')
    pid=int(text('shell','pidof',profile['package']))
    apk=text('shell','pm','path',profile['package']).removeprefix('package:')
    stat=text('shell','cat',f'/proc/{pid}/stat');maps=text('shell','cat',f'/proc/{pid}/maps')
    low,high,row=game_mapping(maps.splitlines(),apk,profile,True)
    identity={key:profile[key] for key in ('library_bytes','library_sha256','jni_exports')}
    identity.update(apk=apk,serial=device['serial'],device_binding=device,pid=pid,base=hex(low),executable_end=hex(high),mapping=row,
        process_start_time=stat[stat.rfind(')')+2:].split()[19])
    session=ReadOnlySession(identity)
    old=json.loads((runtime_dir()/'loader-profile.json').read_text(encoding='utf-8'))
    def bound_exports(path,local,machine,exports):
        # NativeBridge can map the same proxy into multiple namespaces.
        # Select the game's own instance using its hash-bound dlopen import.
        anchor=(int(exports['dlopen']['va'],0),session.pointer(low+0x1c73138)) if local=='loader-libdl.so' else None
        base=load_bias(maps.splitlines(),path,Elf((runtime_dir()/local).read_bytes(),machine=machine),anchor=anchor)
        bound={}
        for name,pin in exports.items():
            address=base+int(pin['va'],0)
            if hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:raise ValueError('loader export changed: '+name)
            bound[name]=dict(pin,address=hex(address))
        return base,bound
    guest_base,guest=bound_exports(old['library'],'loader-libdl.so',183,old['exports'])
    host_profile=profile['mumu_bridge']['host_loader']
    _,host=bound_exports(host_profile['library'],'host-libdl.so',62,host_profile['exports'])
    loader=dict(old,identity=identity,base=hex(guest_base),exports=guest,mumu_bridge=dict(host_loader_exports=host))
    payload=dict(identity=identity,loader=loader)
    if args.worker_binding:
        payload['worker']=json.loads(args.worker_binding.read_text(encoding='utf-8'))
        if payload['worker']['observation']['identity']!=identity:raise ValueError('worker binding is stale')
    binding=output/'binding.json';binding.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    session.verify()
    if 'TracerPid:\t0' not in text('shell','cat',f'/proc/{pid}/status'):raise RuntimeError('another debugger owns game')
    server=profile['debug_server'];port=debug_port()
    if text('shell','sha256sum',server).split()[0]!=profile['debugger_sha256']:raise ValueError('debugger server changed')
    forwards=subprocess.check_output(['adb','forward','--list'],text=True,timeout=10).splitlines()
    same=[line.split() for line in forwards if len(line.split())==3 and line.split()[1]==f'tcp:{port}']
    expected=[device['serial'],f'tcp:{port}',f'tcp:{port}']
    if same and same!=[expected]:raise RuntimeError('debug port is owned by another forwarding')
    created=not same
    if created:subprocess.run(adb+['forward','--no-rebind',f'tcp:{port}',f'tcp:{port}'],check=True,timeout=10)
    result_path=output/'result.json'
    try:
        with (output/'server.log').open('wb') as log:
            server_process=subprocess.Popen(adb+['shell',server,'gdbserver',f'127.0.0.1:{port}','--attach',str(pid)],stdout=log,stderr=subprocess.STDOUT)
            until=time.monotonic()+15;ready=False
            while time.monotonic()<until:
                if server_process.poll() is not None:raise RuntimeError('owned debugger server exited')
                status=text('shell','cat',f'/proc/{pid}/status')
                fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status.splitlines() if ':' in line}
                tracer=fields.get('TracerPid','0')
                if tracer!='0' and fields.get('State','').startswith('t'):
                    argv=subprocess.check_output(adb+['exec-out','cat',f'/proc/{tracer}/cmdline'],timeout=10).split(b'\0')
                    if argv[:5]!=[server.encode(),b'gdbserver',f'127.0.0.1:{port}'.encode(),b'--attach',str(pid).encode()]:raise RuntimeError('unexpected tracer')
                    ready=True;break
                time.sleep(.2)
            if not ready:raise RuntimeError('owned attach pending; inspect server log before continuing')
            gate='mumu_worker_gate' if args.worker_binding else 'mumu_smoke_gate'
            commands=['platform select remote-android','target create --arch x86_64 '+json.dumps(str(runtime_dir()/'host-linker64')),
                f'gdb-remote 127.0.0.1:{port}',
                'script import sys;sys.path.insert(0,'+repr(str(ROOT))+');import '+gate+';'+gate+'.run(lldb.debugger,'+repr(str(binding))+','+repr(str(result_path))+')','quit']
            command=lldb_command()+['-b']
            for item in commands:command+=['-o',item]
            with (output/'lldb.log').open('wb') as log:
                done=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,ANDROID_SERIAL=device['serial']))
            if not result_path.exists():raise RuntimeError('debugger produced no receipt; inspect exact owned session')
            result=json.loads(result_path.read_text(encoding='utf-8'))
            result['lldb_exit']=done.returncode;result['pid_alive']=text('shell','pidof',profile['package'])==str(pid)
            result['tracer_cleared']='TracerPid:\t0' in text('shell','cat',f'/proc/{pid}/status')
            session.verify()
            result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if result['errors'] or not result.get('detached') or not result.get('tracer_cleared'):raise RuntimeError('game bridge handshake did not complete safely')
            server_process.wait(timeout=10)
    finally:
        if created:subprocess.run(adb+['forward','--remove',f'tcp:{port}'],timeout=10)


if __name__=='__main__':main()
