"""Deploy only the freshly hash-bound source initialization probe, once."""
import argparse,hashlib,json,re,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vendor'))
from client_session import ReadOnlySession
from portable_config import readelf_command

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='bootstrap');args=parser.parse_args()
    if not re.fullmatch(r'(?:scene-v[1-9][0-9]*|bootstrap(?:-v(?:[2-9]|[1-9][0-9]+))?)',args.attempt):raise ValueError('invalid attempt')
    binding=json.loads((ROOT/(args.attempt+'-binding.json')).read_text(encoding="utf-8"));s=ReadOnlySession(binding['identity'])
    maps=s.verify()
    from portable_config import translated
    if translated():
        from mumu_lifecycle import verify_retained
        verify_retained(ROOT,maps,binding['identity'])
    elif any(v in maps for v in ('libcr_private_','libcr_direct_','libcr_web_')):raise ValueError('previous experiment still mapped')
    status=subprocess.check_output(s.adb+['shell',f'cat /proc/{s.pid}/status'],text=True,timeout=10)
    if any(l.startswith('TracerPid:') and l.split()[1]!='0' for l in status.splitlines()):raise ValueError('debugger already attached')
    for pin in binding['pins']:
        if hashlib.sha256(s.read(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:raise ValueError('binding stale')
    path=Path(binding.get('binary_path',ROOT/'build/libcr_web_bootstrap_20261014.so'));raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=binding['binary_sha256']:raise ValueError('binary changed since binding')
    phoff=struct.unpack_from('<Q',raw,32)[0];phsize,phcount=struct.unpack_from('<HH',raw,54)
    segments=[struct.unpack_from('<II6Q',raw,phoff+i*phsize) for i in range(phcount)]
    listing=subprocess.check_output(readelf_command()+['--dyn-syms',str(path)],text=True,timeout=10)
    wanted={'cr_web_bootstrap_start','cr_web_bootstrap_done_address','cr_web_bootstrap_result_address','cr_web_bootstrap_release',
            'cr_web_source_text_address','cr_web_source_text_size','cr_web_bootstrap_towers_address'};exports={}
    if binding.get('scene'):wanted={'cr_web_scene_'+name for name in ('start','cleanup','return_lobby','done_address','result_address','release','trace_address','trace_size')}
    for line in listing.splitlines():
        parts=line.split()
        if len(parts)!=8 or parts[-1] not in wanted:continue
        va=int(parts[1],16);size=int(parts[2]);matches=[p for p in segments if p[0]==1 and p[3]<=va and va+size<=p[3]+p[5]]
        if len(matches)!=1 or not 0<size<=4096:raise ValueError('invalid export')
        p=matches[0];code=raw[p[2]+va-p[3]:p[2]+va-p[3]+size]
        exports[parts[-1]]={'va':hex(va),'size':size,'sha256':hashlib.sha256(code).hexdigest()}
    if set(exports)!=wanted:raise ValueError('missing export')
    suffix=args.attempt.removeprefix('bootstrap') or '-v1'
    folder='/data/local/tmp/cr_web_'+args.attempt.replace('-','_') if binding.get('scene') else '/data/local/tmp/cr_web_bootstrap_20261014'+suffix.replace('-','_')
    from portable_config import deployment_id
    folder='/data/local/tmp/royale_replay_'+deployment_id()+'_'+args.attempt.replace('-','_')
    device=folder+'/'+path.name
    if subprocess.run(s.adb+['shell','test','-e',folder],timeout=10).returncode!=1:raise ValueError('preserve previous device experiment')
    subprocess.run(s.adb+['shell','mkdir',folder],check=True,timeout=10)
    subprocess.run(s.adb+['push',str(path),device],check=True,timeout=15)
    if subprocess.check_output(s.adb+['shell','sha256sum',device],text=True,timeout=10).split()[0]!=digest:raise ValueError('device binary mismatch')
    from portable_config import translated
    if translated():
        from mumu_runtime import allow_client_read
        allow_client_read(s.adb,[device])
    s.verify()
    with (ROOT/(args.attempt+'-component.json')).open('x',encoding='utf-8') as f:json.dump({'local_path':str(path),'device_path':device,
        'sha256':digest,'exports':exports,'native_calls':False},f,indent=2)
    print(json.dumps({'deployed':True,'native_calls':False,'initialization_only':True}))

if __name__=='__main__':main()
