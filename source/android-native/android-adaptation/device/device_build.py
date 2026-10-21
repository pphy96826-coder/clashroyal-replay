"""Compile the real, initialization-only replay component ON the phone.

No component loading, game attach, queue publication, simulation or scene change.
Fresh code/worker pins and locally verified map resources are mandatory.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import traceback
import zipfile

from bootstrap_input import render
from device_session import ReadOnlySession, installed_library, start_time
from device_tools import compiler_flags, needed
from elf_contract import Elf

FUNCTIONS=(0x1365bf0,0x1366114,0xabea80,0x1366bb4,0x1470500,0x146f060,0x1052df0,0x1090a7c,
    0x16cb4d8,0x16cb3c8,0x1537d58,0x1b34938,0x1b34940,
    0x152cd44,0x152ceec,0x152d824,0x152d81c,0x152dcdc,0x152db84,0x152db5c,
    0x10da32c,0x10da44c,0x10da3b8,0x10da758,0x104b1d4,0x103864c,
    0x12085b4,0x10cebe0,0x10ce6a4,0xf9ce00,0xf9d5e0,0xf9d368,
    0xf96dcc,0xf96cf4,0xf96de8,0xf9ce58,0xf9ab04,0xf9d370,0x1366f64,
    0xf5603c,0xf9fcac,0xf9fd0c,0xf9ff78,0x120f614,0x89d3e0,0x120c810,0xf9baac)


def run(preparation, destination, prefix, *, run_source=False, native_replay=None, scene=False, speed=1):
    destination.mkdir(exist_ok=False, mode=0o700)
    try:
        temporary=destination/'tmp';temporary.mkdir(mode=0o700)
        os.environ['TMPDIR']=str(temporary);os.environ['HOME']=str(destination)
        doc=json.loads(preparation.read_text())
        observation=json.loads((preparation.parent/'runtime/runtime-observation.json').read_text())
        identity=observation['identity'];installed_library(identity['apk'])
        with zipfile.ZipFile(identity['apk']) as archive:elf=Elf(archive.read('lib/arm64-v8a/libg.so'))
        session=ReadOnlySession(identity);base=session.base
        def verify_resources():
            root=session.raw_pointer(base+0x1d34ae0)
            if (root!=int(observation['root_raw'],0) or session.raw_pointer(root+0x20)!=int(observation['services_raw'],0)
                    or session.raw_pointer(base+0x1d88820)!=int(observation['worker_handle'],0)):
                raise ValueError('runtime owner changed; prepare again, never rebind an old component')
            worker=int(observation['worker_handle'],0)
            if struct.unpack('<i',session.read(worker+0x10,4))[0]!=observation['worker_tid']:
                raise ValueError('worker changed')
            task=Path('/proc')/str(session.pid)/'task'/str(observation['worker_tid'])/'stat'
            if start_time(task.read_text())!=observation['worker_start_time']:raise ValueError('worker generation changed')
            session.verify()
        verify_resources()
        native=json.loads(native_replay.read_text())['native_replay'] if native_replay else None
        if scene:
            from scene_input import render_scene
            if not run_source or native is None:raise ValueError('scene requires fully verified native replay')
            input_text=render_scene(doc,native,speed)
        else:input_text=render(doc,run_source=run_source,native_replay=native)
        code=Path(__file__).parent/'native-src';workspace=destination/'workspace'
        shutil.copytree(code,workspace)
        for name in ('offline-private-map/build/assets.h','offline-private-layout/build/objects.h'):
            target=workspace/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(preparation.parent/'runtime'/name,target)
        root=workspace/'official-web-replay';build=root/'build';build.mkdir()
        contract=json.loads((Path(__file__).parent/'native-code-contract.json').read_text())
        if contract['library_sha256']!=identity['library_sha256'] or contract['contains_process_handles']:
            raise ValueError('wrong audited runtime code contract')
        expected={int(pin['va'],0):pin for pin in contract['pins']}
        transforms=0
        kind='scene' if scene else 'bootstrap'
        functions=list(FUNCTIONS)
        pins=[];header='#pragma once\nstruct '+kind.title()+'Pin{uintptr_t va;const unsigned char* bytes;size_t size;};\n'
        if scene:
            functions.extend((0xed2438,0xec8f1c,0xecb348,0xecb554,0xed1f40,0xed22b4,0xdb3ee8,0x9a7b54,0x8d9460,0x8d9738,0x8d6bc4,0xed2560))
            for name,slot in (('frame',0xb10),('interpolate',0xb08)):
                va=session.pointer(base+0x1bd3cb0+slot)-base
                if va not in expected:raise ValueError('unaudited scene callback')
                functions.append(va)
                header+='static constexpr uintptr_t scene_'+name+'_va='+hex(va)+';\n'
        ranges=[(base+va,32) for va in functions]
        values=session.read_many(ranges)
        if session.read_many(ranges)!=values:raise ValueError('native code changed during binding')
        for index,(va,raw) in enumerate(zip(functions,values)):
            pin=expected[va]
            if pin['size']!=32 or hashlib.sha256(elf.at(va,32)).hexdigest()!=pin['file_sha256']:
                raise ValueError('installed function fingerprint differs at '+hex(va))
            if hashlib.sha256(raw).hexdigest()!=pin['runtime_sha256']:
                raise ValueError('loaded function fingerprint differs at '+hex(va))
            if pin['runtime_sha256']!=pin['file_sha256']:transforms+=1
            pins.append(dict(va=hex(va),address=hex(base+va),size=32,sha256=hashlib.sha256(raw).hexdigest(),raw_hex=raw.hex()))
            header+='static const unsigned char bp%d[]={%s};\n'%(index,','.join(hex(v) for v in raw))
        header+='static const '+kind.title()+'Pin '+kind+'_pins[]={'+','.join('{%sULL,bp%d,32}'%(hex(va),n) for n,va in enumerate(functions))+'};\n'
        header+='static constexpr uintptr_t '+kind+'_base=%sULL,bootstrap_lookup_va=0x104b1d4;\n'%hex(base)
        (build/(kind+'_bindings.h')).write_text(header)
        (build/(kind+'_input.h')).write_text(input_text)
        flags,static_runtime=compiler_flags(prefix)
        binary=build/('libphone_replay_'+kind+'.so')
        command=[*flags,'-fPIC','-shared',
            '-DWEB_'+kind.upper()+'_BINDINGS="'+str(build/(kind+'_bindings.h'))+'"',
            '-DWEB_'+kind.upper()+'_INPUT="'+str(build/(kind+'_input.h'))+'"',
            str(root/('native_'+kind+'_probe.cpp')),str(workspace/'offline-queue-runtime/empty_publisher.cpp'),
            str(workspace/'offline-task-prototype/noop_task.cpp'),*static_runtime,'-o',str(binary)]
        with (destination/'compile.log').open('x') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
        wanted={'cr_web_bootstrap_start','cr_web_bootstrap_done_address',
            'cr_web_bootstrap_result_address','cr_web_bootstrap_release','cr_web_source_text_address',
            'cr_web_source_text_size','cr_web_bootstrap_towers_address'}
        if scene:wanted={'cr_web_scene_'+n for n in ('start','cleanup','return_lobby','done_address','result_address','release','trace_address','trace_size')}
        raw=binary.read_bytes();exports=Elf(raw).exports(wanted)
        dependencies=needed(raw)
        if 'libc++_shared.so' in dependencies:raise ValueError('component unexpectedly depends on shared C++ runtime')
        verify_resources()
        if session.read_many(ranges)!=values:raise ValueError('native code changed during compile')
        binding=dict(identity=identity,pins=pins,worker_tid=observation['worker_tid'],worker_handle=observation['worker_handle'],
                     root_raw=observation['root_raw'],services_raw=observation['services_raw'],
                     preparation_sha256=hashlib.sha256(preparation.read_bytes()).hexdigest(),
                     binary_sha256=hashlib.sha256(raw).hexdigest(),binary_path=str(binary),exports=exports,
                     source_execution=run_source,scene=scene,playback_speed=speed,source_event_count=len(doc['events']),preparation_path=str(preparation),
                     source_html_sha256=doc['source_sha256'],native_calls=False,component_loaded=False)
        with (destination/'binding.json').open('x') as stream:json.dump(binding,stream,indent=2)
        report=dict(schema='royale-replay.android-component-build.v1',state='compiled_not_loaded',
                    processing_location='android',desktop_backend_used=False,source_sha256=doc['source_sha256'],
                    retained_events=len(doc['events']),component_sha256=binding['binary_sha256'],
                    compiled_on_phone=True,initialization_only=not run_source,code_pin_count=len(pins),
                    loaded_code_transforms_verified=transforms,
                    export_count=len(exports),cpp_shared_runtime_required=False,dependencies=dependencies,
                    native_game_calls=False,game_memory_written=False,debugger_attached=False,
                    component_loaded=False,standalone_playback_ready=False)
        with (destination/'result.json').open('x') as stream:json.dump(report,stream,indent=2)
        return report
    except Exception:
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        raise
    finally:
        owner=destination.parent.stat()
        for path in sorted(destination.rglob('*'),reverse=True):
            if path.is_symlink():raise ValueError('unexpected link in private component build')
            os.chown(path,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)
