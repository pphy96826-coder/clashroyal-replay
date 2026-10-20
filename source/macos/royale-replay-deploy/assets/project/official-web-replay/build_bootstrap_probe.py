"""Fresh-bind and compile the initialization-only source replay probe."""
import argparse,hashlib,json,re,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vendor'))
from client_session import ReadOnlySession
from bootstrap_input import render
from scene_input import render_scene
from portable_config import ndk_bin
NDK=ndk_bin()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resume-build',action='store_true')
    parser.add_argument('--client-observation',type=Path,required=True);parser.add_argument('--attempt',default='bootstrap')
    parser.add_argument('--preparation',type=Path,required=True)
    parser.add_argument('--native-replay',type=Path)
    parser.add_argument('--scene',action='store_true')
    parser.add_argument('--playback-speed',type=float,choices=(.25,.5,1,2,4),default=1)
    parser.add_argument('--source-execution',action='store_true');args=parser.parse_args()
    if not re.fullmatch(r'scene-v[1-9][0-9]*' if args.scene else r'bootstrap(?:-v(?:[2-9]|[1-9][0-9]+))?',args.attempt):raise ValueError('invalid immutable attempt name')
    source=args.preparation;doc=json.loads(source.read_text())
    # Reject malformed input before creating output or touching the device.
    loaded=json.loads(args.native_replay.read_text())['native_replay'] if args.native_replay else None
    input_text=render(doc,args.source_execution,loaded)
    if args.scene:
        if loaded is None:raise ValueError('visible scene requires the full native replay')
        input_text=render_scene(doc,loaded,args.playback_speed)
    elif args.playback_speed!=1:raise ValueError('playback speed is only for a visible scene')
    suffix=args.attempt.removeprefix('bootstrap');build_name='build-'+args.attempt if args.scene else 'build'+suffix
    out=ROOT/build_name;out.mkdir(exist_ok=args.resume_build)
    def generated(path,text):
        if path.exists():
            if not args.resume_build or path.read_text()!=text:raise ValueError('preserve differing build input: '+str(path))
        else:
            with path.open('x') as f:f.write(text)
    if args.client_observation:
        client=json.loads(args.client_observation.read_text());identity=client['identity'];worker={
            'worker_handle':client['worker_handle'],'worker_tid':client['worker_tid'],
            'worker_task_start_time':client['worker_start_time']}
    s=ReadOnlySession(identity);base=s.base
    root_raw=struct.unpack('<Q',s.read(base+0x1d34ae0,8))[0];root=root_raw&0x00ffffffffffffff
    services=s.read(root+0x20,8);services_raw=struct.unpack('<Q',services)[0]
    handle=s.pointer(base+0x1d88820)
    if handle!=int(worker['worker_handle'],0) or struct.unpack('<i',s.read(handle+0x10,4))[0]!=worker['worker_tid']:
        raise ValueError('worker identity changed')
    stat=subprocess.check_output(s.adb+['shell',f"cat /proc/{s.pid}/task/{worker['worker_tid']}/stat"],text=True,timeout=10)
    if stat[stat.rfind(')')+2:].split()[19]!=worker['worker_task_start_time']:raise ValueError('worker start changed')
    pins=[];kind='scene' if args.scene else 'bootstrap'
    header='#pragma once\nstruct '+kind.title()+'Pin{uintptr_t va;const unsigned char* bytes;size_t size;};\n'
    functions=[0x1365bf0,0x1366114,0xabea80,0x1366bb4,0x1470500,0x146f060,0x1052df0,0x1090a7c,
        0x16cb4d8,0x16cb3c8,0x1537d58,0x1b34938,0x1b34940,
        0x152cd44,0x152ceec,0x152d824,0x152d81c,0x152dcdc,0x152db84,0x152db5c,
        0x10da32c,0x10da44c,0x10da3b8,0x10da758,0x104b1d4,0x103864c,
        0x12085b4,0x10cebe0,0x10ce6a4,0xf9ce00,0xf9d5e0,0xf9d368,
        0xf96dcc,0xf96cf4,0xf96de8,0xf9ce58,0xf9ab04,0xf9d370,0x1366f64,
        0xf5603c,0xf9fcac,0xf9fd0c,0xf9ff78,0x120f614,0x89d3e0,0x120c810,0xf9baac]
    if args.scene:
        functions.extend([0xed2438,0xec8f1c,0xecb348,0xecb554,0xed1f40,0xed22b4,0xdb3ee8,0x9a7b54,
                          0x8d9460,0x8d9738,0x8d6bc4,0xed2560])
        # Both rendering callbacks are separately read-bound. Never call a
        # guessed frame API or reuse an address from another client generation.
        scene_methods={name:s.pointer(base+0x1bd3cb0+slot) for name,slot in (('frame',0xb10),('interpolate',0xb08))}
        for address in scene_methods.values():functions.append(address-base)
        header+=''.join('static constexpr uintptr_t scene_'+name+'_va='+hex(address-base)+';\n' for name,address in scene_methods.items())
    pin_ranges=[(base+va,32) for va in functions]
    pin_values=s.read_many(pin_ranges)
    if s.read_many(pin_ranges)!=pin_values:raise ValueError('code changed')
    for n,(va,raw) in enumerate(zip(functions,pin_values)):
        pins.append({'va':hex(va),'address':hex(base+va),'size':32,'sha256':hashlib.sha256(raw).hexdigest(),'raw_hex':raw.hex()})
        header+=f'static const unsigned char bp{n}[]={{'+','.join(hex(v) for v in raw)+'};\n'
    header+='static const '+kind.title()+'Pin '+kind+'_pins[]={'+','.join('{'+p['va']+f'ULL,bp{n},32'+'}' for n,p in enumerate(pins))+'};\n'
    header+=f'static constexpr uintptr_t {kind}_base={hex(base)}ULL,bootstrap_lookup_va=0x104b1d4;\n'
    generated(out/(kind+'_bindings.h'),header)
    generated(out/(kind+'_input.h'),input_text)
    binary=out/('libcr_web_bootstrap_20261014'+suffix.replace('-','_')+'.so')
    cmd=[str(NDK/'aarch64-linux-android24-clang++'),'-std=c++17','-O2','-g','-Wall','-Wextra','-Werror','-fPIC','-fvisibility=hidden',
        '-shared','-static-libstdc++','-Wl,--exclude-libs,ALL','-Wl,--build-id=sha1','-Wl,-z,defs',
        '-DWEB_'+kind.upper()+'_BINDINGS="'+build_name+'/'+kind+'_bindings.h"',
        '-DWEB_'+kind.upper()+'_INPUT="'+build_name+'/'+kind+'_input.h"',str(ROOT/('native_scene_probe.cpp' if args.scene else 'native_bootstrap_probe.cpp')),
        str(ROOT.parent/'offline-queue-runtime/empty_publisher.cpp'),str(ROOT.parent/'offline-task-prototype/noop_task.cpp'),'-o',str(binary)]
    subprocess.run(cmd,check=True,timeout=45)
    s.verify()
    binding={'identity':identity,'worker_tid':worker['worker_tid'],'worker_handle':hex(handle),'root_raw':hex(root_raw),
        'services_raw':hex(services_raw),'pins':pins,'preparation_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'binary_path':str(binary),
        'source_sha256':hashlib.sha256((ROOT/('native_scene_probe.cpp' if args.scene else 'native_bootstrap_probe.cpp')).read_bytes()).hexdigest(),
        'source_execution_sha256':hashlib.sha256((ROOT/'source_execution.h').read_bytes()).hexdigest(),
        'bootstrap_input_sha256':hashlib.sha256((ROOT/'bootstrap_input.py').read_bytes()).hexdigest(),
        'cache_lease_sha256':hashlib.sha256((ROOT/'cache_lease.h').read_bytes()).hexdigest(),
        'tower_check_sha256':hashlib.sha256((ROOT/'native_tower_check.h').read_bytes()).hexdigest(),
        'tower_profiles_sha256':hashlib.sha256((ROOT/'tower_profiles.py').read_bytes()).hexdigest(),
        'source_execution':args.source_execution,'native_calls':False,'scene':args.scene,
        'source_event_count':len(doc['events']),'preparation_path':str(source.resolve()),
        'source_html_sha256':doc['source_sha256'],'playback_speed':args.playback_speed}
    if args.native_replay:
        binding.update(loaded_replay=True,native_replay_sha256=hashlib.sha256(args.native_replay.read_bytes()).hexdigest())
    with (ROOT/(args.attempt+'-binding.json')).open('x') as f:json.dump(binding,f,indent=2)
    old_loader=json.loads((ROOT.parent/'runtime/native/loader-profile.json').read_text())
    maps=s.verify().splitlines()
    def library_base(path):
        rows=[v.split()[0].split('-')[0] for v in maps if len(v.split())>=6 and v.split()[-1]==path and int(v.split()[2],16)==0]
        if len(rows)!=1:raise ValueError('ambiguous system library base')
        return int(rows[0],16)
    dlbase=library_base(old_loader['library']);exports={}
    for name,pin in old_loader['exports'].items():
        address=dlbase+int(pin['va'],0)
        if hashlib.sha256(s.read(address,pin['size'])).hexdigest()!=pin['sha256']:raise ValueError('loader code changed')
        exports[name]=dict(pin,address=hex(address))
    loader=dict(old_loader,identity=identity,base=hex(dlbase),exports=exports,
        bionic_base=hex(library_base('/apex/com.android.runtime/lib64/bionic/libc.so')))
    with (ROOT/(args.attempt+'-loader-binding.json')).open('x') as f:json.dump(loader,f,indent=2)
    print(json.dumps({'built':True,'native_calls':False,'source_events_retained':len(doc['events']),
                      'initialization_only':not args.source_execution,'private_source_execution':args.source_execution,'scene_attached':False}))

if __name__=='__main__':main()
