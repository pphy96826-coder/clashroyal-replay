"""Attach to existing Android1 client and execute one isolated load check."""
import argparse,json,os,re,subprocess,time
from pathlib import Path
from client_session import validate_device_binding
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='bootstrap')
    parser.add_argument('--action',choices=('start','observe','cleanup','return-lobby'),default='start')
    parser.add_argument('--receipt');args=parser.parse_args()
    attempt=args.attempt
    scene=bool(re.fullmatch(r'scene-v[1-9][0-9]*',attempt))
    if not scene and not re.fullmatch(r'bootstrap(?:-v(?:[2-9]|[1-9][0-9]+))?',attempt):raise ValueError('invalid attempt')
    if not scene and (args.action!='start' or args.receipt):raise ValueError('bootstrap only supports a single start')
    receipt=args.receipt or attempt
    if not re.fullmatch(re.escape(attempt)+r'(?:-(?:observe|cleanup|return-lobby)-v[1-9][0-9]*)?',receipt):raise ValueError('invalid immutable receipt')
    if (ROOT/(receipt+'-result.json')).exists():raise FileExistsError('existing task must be observed, never restarted')
    if args.action=='start' and receipt!=attempt:raise ValueError('start requires original receipt')
    binding=json.loads((ROOT/(attempt+'-binding.json')).read_text(encoding="utf-8"));identity=binding['identity']
    validate_device_binding(identity)  # A native handle never migrates to a new port/process.
    from portable_config import debug_server,debug_port,lldb_command
    DEBUG_SERVER=debug_server();DEBUG_PORT=debug_port()
    old=ROOT.parent/'runtime/native'
    loader=json.loads((ROOT/(attempt+'-loader-binding.json')).read_text(encoding="utf-8"))
    adb=['adb','-s',identity['serial']]
    if subprocess.check_output(adb+['shell','pidof com.tencent.tmgp.supercell.clashroyale'],text=True).strip()!=str(identity['pid']):raise ValueError('client generation changed')
    status=subprocess.check_output(adb+['shell',f"cat /proc/{identity['pid']}/status"],text=True)
    if any(l.startswith('TracerPid:') and l.split()[1]!='0' for l in status.splitlines()):raise ValueError('existing debugger; do not duplicate')
    if not 1024<=DEBUG_PORT<=65535:raise ValueError('invalid local debugger port')
    from portable_config import translated,runtime_profile
    is_mumu=translated()
    target_file=ROOT.parent/'runtime/native'/('host-linker64' if is_mumu else 'libg.so')
    architecture='x86_64' if is_mumu else 'aarch64'
    preflight=lldb_command()+['-b','-o','target create --arch '+architecture+' '+json.dumps(str(target_file),ensure_ascii=False)]
    for name in (() if is_mumu else ('loader-libc.so','loader-libdl.so')):
        preflight+=['-o','target modules add '+json.dumps(str(old/name),ensure_ascii=False)]
    subprocess.run(preflight+['-o','quit'],check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    forwards=subprocess.check_output(['adb','forward','--list'],text=True,timeout=10).splitlines()
    same=[line.split() for line in forwards if len(line.split())==3 and line.split()[1]==f'tcp:{DEBUG_PORT}']
    expected=[identity['serial'],f'tcp:{DEBUG_PORT}',f'tcp:{DEBUG_PORT}']
    if same and same!=[expected]:raise RuntimeError('debug port belongs to another forwarding; not replaced')
    if not same:subprocess.run(adb+['forward','--no-rebind',f'tcp:{DEBUG_PORT}',f'tcp:{DEBUG_PORT}'],check=True,timeout=10)
    with (ROOT/(receipt+'-server.log')).open('x',encoding='utf-8') as server_log,(ROOT/(receipt+'-debugger.log')).open('x',encoding='utf-8') as debugger_log:
        server=subprocess.Popen(adb+['shell',DEBUG_SERVER,
            'gdbserver',f'127.0.0.1:{DEBUG_PORT}','--attach',str(identity['pid'])],stdout=server_log,stderr=subprocess.STDOUT)
        # Attaching ~135 native threads can take more than one second. Wait on
        # this exact server/client's kernel state, not a guessed sleep or a test
        # TCP connection (which would consume its single debugger connection).
        ready=False
        for _ in range(20):
            time.sleep(.5)
            if server.poll() is not None:raise RuntimeError('original debugger server exited; inspect retained log')
            state=subprocess.check_output(adb+['shell',f"cat /proc/{identity['pid']}/status"],text=True,timeout=10)
            fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in state.splitlines() if ':' in line}
            tracer=fields.get('TracerPid','0')
            if tracer!='0' and fields.get('State','').startswith('t'):
                argv=subprocess.check_output(adb+['shell',f'cat /proc/{tracer}/cmdline'],timeout=10).split(b'\0')
                if argv[:5]!=[DEBUG_SERVER.encode(),b'gdbserver',f'127.0.0.1:{DEBUG_PORT}'.encode(),b'--attach',str(identity['pid']).encode()]:
                    raise RuntimeError('unexpected debugger owns client')
                with (ROOT/(receipt+'-server-handle.json')).open('x',encoding='utf-8') as f:json.dump({'pid':int(tracer),'client_pid':identity['pid'],'published':False},f)
                ready=True;break
        if not ready:raise RuntimeError('original attach still pending; retain server handle, no replacement')
        commands=['platform select remote-android',
            'target create --arch '+architecture+' '+json.dumps(str(target_file),ensure_ascii=False),
            f'gdb-remote 127.0.0.1:{DEBUG_PORT}',
            *([] if is_mumu else [
                'target modules add '+json.dumps(str(old/'loader-libc.so'),ensure_ascii=False),
                'target modules load --file loader-libc.so --slide '+loader['bionic_base'],
                'target modules add '+json.dumps(str(old/'loader-libdl.so'),ensure_ascii=False),
                'target modules load --file loader-libdl.so --slide '+loader['base']]),
            'script import sys; sys.path.insert(0,'+repr(str(ROOT))+'); import '+('run_scene_gate' if scene else 'run_bootstrap_gate')+'; '+('run_scene_gate.run(lldb.debugger,'+repr(attempt)+','+repr(args.action)+','+repr(receipt)+')' if scene else 'run_bootstrap_gate.run(lldb.debugger,'+repr(attempt)+')'),
            'quit']
        command=lldb_command()+['-b']
        for item in commands:command+=['-o',item]
        result=subprocess.run(command,stdout=debugger_log,stderr=subprocess.STDOUT,
                              env=dict(os.environ,ANDROID_SERIAL=identity['serial']))
        print(json.dumps({'debugger_exit':result.returncode,'result_path':str(ROOT/(receipt+'-result.json'))}))

if __name__=='__main__':main()
