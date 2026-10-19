"""Build and run owned fixtures through the selected MuMu and Windows LLDB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--port',type=int,default=50359)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('invalid explicit debug port')
    os.environ['ROYALE_REPLAY_CONFIG']=str(args.config.resolve())
    sys.path.insert(0,str(ROOT/'project/official-web-replay'))
    from portable_config import compiler_command,host_compiler_command,ndk_bin,lldb_command
    from portable_config import translated
    if not translated():raise ValueError('select native_transport=mumu-nativebridge-v1 explicitly')
    from client_session import ensure_current_device_binding
    from mumu_runtime import validate_device
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    adb=['adb','-s',ensure_current_device_binding()['serial']]
    device=validate_device(adb)
    core=ROOT/'project/official-web-replay'
    host=out/'mumu_transport_fixture';guest=out/'libmumu_transport_fixture.so'
    common=['-std=c++17','-O1','-g','-Wall','-Wextra','-Werror']
    subprocess.run(host_compiler_command()+common+['-DRR_MUMU_STANDALONE_TEST','-static-libstdc++',str(core/'mumu_bridge_host.cpp'),'-ldl','-o',str(host)],check=True,timeout=45)
    subprocess.run(compiler_command()+common+['-shared','-fPIC','-nostdlib',str(core/'mumu_bridge_guest.cpp'),str(ROOT/'tests/mumu_bridge_fixture.cpp'),'-o',str(guest)],check=True,timeout=45)
    identity=hashlib.sha256(host.read_bytes()+guest.read_bytes()).hexdigest()[:20]
    remote='/data/local/tmp/royale_replay_transporttest_'+identity
    subprocess.run(adb+['shell','mkdir','-p',remote+'/cache'],check=True,timeout=10)
    server=next(ndk_bin().parent.glob('lib/clang/*/lib/linux/x86_64/lldb-server'))
    for path in (host,guest,server):
        subprocess.run(adb+['push',str(path),remote+'/'+path.name],check=True,timeout=30)
        subprocess.run(adb+['shell','chmod','700',remote+'/'+path.name],check=True,timeout=10)
    done=subprocess.run(adb+['shell',remote+'/'+host.name,remote+'/'+guest.name,remote+'/cache'],capture_output=True,timeout=30)
    (out/'direct.log').write_bytes(done.stdout+done.stderr)
    if done.returncode:raise RuntimeError('direct MuMu fixture failed (exit %d): '%done.returncode+done.stderr.decode(errors='replace'))
    print(done.stdout.decode(errors='replace'))
    forwards=subprocess.check_output(['adb','forward','--list'],text=True,timeout=10).splitlines()
    if any(len(row.split())==3 and row.split()[1]=='tcp:'+str(args.port) for row in forwards):
        raise RuntimeError('explicit test port is already forwarded; no existing mapping replaced')
    subprocess.run(adb+['forward','--no-rebind','tcp:'+str(args.port),'tcp:'+str(args.port)],check=True,timeout=10)
    try:
        with (out/'server.log').open('wb') as log:
            process=subprocess.Popen(adb+['shell',remote+'/'+server.name,'gdbserver','127.0.0.1:'+str(args.port),remote+'/'+host.name,remote+'/'+guest.name,remote+'/cache'],stdout=log,stderr=subprocess.STDOUT)
            # No test TCP connection: lldb-server accepts one owning debugger.
            until=time.monotonic()+5
            while time.monotonic()<until:
                if process.poll() is not None:raise RuntimeError('fixture debugger server exited; inspect server.log')
                if 'Listening' in (out/'server.log').read_text(errors='replace'):break
                time.sleep(.1)
            report=out/'lldb-result.json'
            commands=['target create --arch x86_64 '+json.dumps(str(host)),
                'gdb-remote 127.0.0.1:'+str(args.port),
                'breakpoint set --name rr_mumu_test_ready',
                'continue',
                'script import sys;sys.path.insert(0,'+repr(str(ROOT/'tests'))+');import mumu_lldb_probe;mumu_lldb_probe.run(lldb.debugger,'+repr(str(core))+','+repr(str(report))+')',
                'quit']
            command=lldb_command()+['-b']
            for text in commands:command+=['-o',text]
            with (out/'lldb.log').open('wb') as log:
                checked=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60)
            if not report.is_file():raise RuntimeError('LLDB fixture did not produce a result; inspect lldb.log')
            result=json.loads(report.read_text(encoding='utf-8'))
            result.update(device=device,lldb_exit=checked.returncode,fixture_host_sha256=hashlib.sha256(host.read_bytes()).hexdigest(),
                fixture_guest_sha256=hashlib.sha256(guest.read_bytes()).hexdigest(),native_replay_verified=False)
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if not result.get('ok') or not result.get('detached'):raise RuntimeError('LLDB typed-call transport validation failed')
            process.wait(timeout=10)
    finally:
        subprocess.run(adb+['forward','--remove','tcp:'+str(args.port)],timeout=10)


if __name__=='__main__':main()
