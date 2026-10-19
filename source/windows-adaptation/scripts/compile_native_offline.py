"""Compile-only Android source closure; synthetic fixtures; zero device calls."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'project/official-web-replay'),str(ROOT/'tests')]
from bootstrap_input import render
from scene_input import render_scene
from test_source_pipeline import fixture


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--ndk-bin',type=Path,required=True);args=parser.parse_args()
    compiler=args.ndk_bin/('clang++.exe' if sys.platform=='win32' else 'clang++')
    if not compiler.is_file():raise FileNotFoundError(compiler)
    with tempfile.TemporaryDirectory(prefix='Windows port 空格 ') as directory:
        target=Path(directory)/'project';shutil.copytree(ROOT/'project',target,ignore=shutil.ignore_patterns('__pycache__','console-runs'))
        _,_,shifted=fixture();native=copy.deepcopy(shifted['initialization_only']);native['cmd']=[]
        for event in shifted['events']:
            identity=shifted['participants'][event['source_side']]['synthetic_native_identity'];tick=event['source_tick_20hz']
            native['cmd'].append(dict(ct=153,c=dict(t=tick,t2=tick,idHi=identity['hi'],idLo=identity['lo'],
                sel=dict(os=event['base_data_id']),px=event['source_position']['x'],py=event['source_position']['y'])))
        (target/'bootstrap_input.h').write_text(render(shifted,True),encoding='utf-8')
        (target/'scene_input.h').write_text(render_scene(shifted,native),encoding='utf-8')
        for relative,text in (
            ('offline-private-map/build/assets.h','static const char asset_0[]={0},asset_1[]={0};\nstatic const int asset_0_size=1,asset_1_size=1;\nstatic const int expected_cells[]={0};\nstatic const unsigned map_width=1,map_height=1;\n'),
            ('offline-private-layout/build/objects.h','static constexpr private_layout::ExpectedObject expected_objects[]={{"synthetic",0,0}};\nstatic constexpr unsigned expected_object_count=1;\n')):
            path=target/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
        common=[str(compiler),'--target=aarch64-linux-android24','-std=c++17','-O2','-Wall','-Wextra','-Werror','-static-libstdc++']
        for kind in ('bootstrap','scene'):
            title=kind.title();binding=target/(kind+'_bindings.h')
            binding.write_text('struct '+title+'Pin{uintptr_t va;const unsigned char* bytes;size_t size;};\nstatic const '+title+'Pin '+kind+'_pins[]={{0,nullptr,0}};\n'+
                ('static constexpr uintptr_t bootstrap_base=0,bootstrap_lookup_va=0;\n' if kind=='bootstrap' else
                 'static constexpr uintptr_t scene_base=0,scene_frame_va=0,scene_interpolate_va=0;\n'),encoding='utf-8')
            command=common+['-shared','-fPIC','-Wl,-z,defs',
                '-DWEB_'+kind.upper()+'_INPUT="'+(target/(kind+'_input.h')).as_posix()+'"',
                '-DWEB_'+kind.upper()+'_BINDINGS="'+binding.as_posix()+'"',
                str(target/'official-web-replay'/('native_'+kind+'_probe.cpp')),
                str(target/'offline-queue-runtime/empty_publisher.cpp'),str(target/'offline-task-prototype/noop_task.cpp'),
                '-o',str(target/(kind+'.so'))]
            subprocess.run(command,check=True,timeout=90)
        subprocess.run(common+[str(target/'official-web-replay/readonly_memory_reader.cpp'),'-o',str(target/'reader')],check=True,timeout=45)
    print(json.dumps(dict(android_native_compilation=True,host=sys.platform,windows_native_tested=sys.platform=='win32',
        fixture='synthetic compile-only, not game state',device_contacted=False,native_code_executed=False),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
