"""Isolated source/import/build checks. No emulator, browser, login or network."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SKILL=Path(__file__).resolve().parents[1]

SMOKE=r'''
import sys,json,copy,hashlib,ast,os
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'official-web-replay'),str(root/'vendor')]
import console_backend,desktop_worker,bridge_queue,build_bootstrap_probe,deploy_bootstrap_probe
import observe_card_levels,observe_current_client,observe_tower_catalog,prepare_runtime
from native_runner.royaleapi_replay import resolve_native_card
from native_runner.tools.royaleapi_hog_il import parse_royaleapi_replay_html
from import_replay import convert
from prepare_native_replay import prepare
from timing_policy import apply_offset,offset_for,recipe_for
from bootstrap_input import render
from scene_input import render_scene
from portable_config import bridge_queue as queue,operation_lock
worker_tree=ast.parse((root/'official-web-replay/desktop_worker.py').read_text())
worker_main=next(n for n in worker_tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
path_assignment=next(n for n in worker_main.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=="os.environ['PATH']")
previous_path=os.environ.get('PATH','');os.environ['PATH']='/configured-adb-first:/usr/bin'
exec(compile(ast.Module(body=[path_assignment],type_ignores=[]),'<path-priority-test>','exec'),{'os':os})
assert os.environ['PATH'].startswith('/configured-adb-first:')
os.environ['PATH']=previous_path
assert resolve_native_card('hog-rider').card_id==26000021
assert resolve_native_card('ice-golem').card_id==26000038
try:parse_royaleapi_replay_html('<html>not a replay</html>',preserve_all_events=True)
except ValueError:pass
else:raise AssertionError('missing timeline accepted')
for filename in console_backend.RECIPE_FILES:assert (console_backend.ROOT/filename).is_file(),filename
assert len(console_backend.recipe_digest())==64
assert offset_for('NEVER-SEEN-BEFORE')==20
assert recipe_for('base',20)!=recipe_for('base',0)
keys=('hog-rider','ice-golem','musketeer','cannon','fireball','the-log','skeletons','ice-spirit')
cards=[dict(card_key=k,level=16) for k in keys]
battle={side:dict(players=[dict(name='Synthetic '+side,tag='TEST0001' if side=='team' else 'TEST0002',
            deck=copy.deepcopy(cards),tower_card=dict(card_key='tower-princess',level=16))]) for side in ('team','opponent')}
events=[]
for i in range(4):
 for side in ('team','opponent'):
  tick=100+len(events)*30;x,y=(3500,14500) if side=='team' else (14500,17500)
  events.append(dict(kind='play_card',side=side,replay_tick_20hz=tick,card_key=keys[i],position=dict(x=x,y=y),
                     source_fields=dict(data_t=tick,data_i=1,data_x=x,data_y=y,data_s='blue' if side=='team' else 'red')))
payload=dict(source=dict(source_data_i=1,replay_tag='SYNTHETIC',dropped_pre_policy_event_count=0),
             battle=battle,events=events,replay=dict(duration=dict(timeline_seconds=300),outcome='unknown'))
source=convert(payload,source_path=Path('synthetic-only.html'),source_bytes=b'synthetic',parser_digest='synthetic')
prep=prepare(source);shifted=apply_offset(prep,20)
assert all(new['source_tick_20hz']==old['source_tick_20hz']+20 and new['source_fields']==old['source_fields'] for old,new in zip(prep['events'],shifted['events']))
try:apply_offset(shifted,20)
except ValueError:pass
else:raise AssertionError('delay compounded')
(root/'bootstrap_input.h').write_text(render(shifted,True))
native=copy.deepcopy(shifted['initialization_only']);native['cmd']=[]
for e in shifted['events']:
 identity=shifted['participants'][e['source_side']]['synthetic_native_identity'];t=e['source_tick_20hz']
 native['cmd'].append(dict(ct=153,c=dict(t=t,t2=t,idHi=identity['hi'],idLo=identity['lo'],sel=dict(os=e['base_data_id']),
                                        px=e['source_position']['x'],py=e['source_position']['y'])))
(root/'scene_input.h').write_text(render_scene(shifted,native))
assert not any(m=='torch' or m.startswith(('torch.','pandas','pyarrow')) for m in sys.modules)
print(json.dumps(dict(isolated_stdlib_imports=True,source_recipe_files_present=True,global_delay_verified=True,configured_adb_priority=True,synthetic_events=len(events))))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--compile-native',action='store_true')
    p.add_argument('--ndk-bin',type=Path);p.add_argument('--local-apk',type=Path);args=p.parse_args()
    spec=importlib.util.spec_from_file_location('skill_deployment',SKILL/'scripts/deploy.py')
    deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
    report=deploy.verify_package();payload=deploy.PAYLOAD
    for path in payload.rglob('*'):
        if not path.is_file():continue
        if path.suffix in ('.apk','.so','.dylib','.mp4','.mov','.log','.pem'):raise ValueError('runtime/binary material in source package')
        if re.search(rb'/Users/'+rb'[\w.-]+/',path.read_bytes()):raise ValueError('personal home path leaked into payload')
        if path.suffix=='.py':
            tree=ast.parse(path.read_text(),str(path))
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='command' and node.args:
                    value=node.args[0]
                    if isinstance(value,ast.Constant) and isinstance(value.value,str) and value.value.endswith('.py'):
                        if not (payload/'official-web-replay'/value.value).is_file():raise ValueError('missing called script '+value.value)
    with tempfile.TemporaryDirectory(prefix='royale skill isolated ') as directory:
        target=Path(directory)/'relocated project';shutil.copytree(payload,target)
        result=subprocess.check_output([sys.executable,'-I','-S','-c',SMOKE,str(target)],text=True,timeout=30)
        report.update(json.loads(result))
        if args.compile_native:
            ndk=args.ndk_bin or deploy.ndk_default();compiler=ndk/'aarch64-linux-android24-clang++'
            if not compiler.is_file():raise FileNotFoundError('native compiler missing')
            if args.local_apk:
                import zipfile
                sys.path.insert(0,str(target/'official-web-replay'))
                from local_assets import generate
                contract=json.loads((target/'profiles/native-contract.json').read_text())
                with zipfile.ZipFile(args.local_apk) as archive:report['local_resource_generation']=generate(archive,target,contract['map_asset_sha256'])
            else:
                for relative,text in (
                    ('offline-private-map/build/assets.h','static const char asset_0[]={0},asset_1[]={0};\nstatic const int asset_0_size=1,asset_1_size=1;\nstatic const int expected_cells[]={0};\nstatic const unsigned map_width=1,map_height=1;\n'),
                    ('offline-private-layout/build/objects.h','static constexpr private_layout::ExpectedObject expected_objects[]={{"synthetic",0,0}};\nstatic constexpr unsigned expected_object_count=1;\n')):
                    path=target/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                report['compile_only_synthetic_resources']=True
            common=[str(compiler),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-static-libstdc++','-Wl,-z,defs']
            for kind in ('bootstrap','scene'):
                title=kind.title();binding=target/(kind+'_bindings.h')
                binding.write_text('struct '+title+'Pin{uintptr_t va;const unsigned char* bytes;size_t size;};\nstatic const '+title+'Pin '+kind+'_pins[]={{0,nullptr,0}};\n'+
                    ('static constexpr uintptr_t bootstrap_base=0,bootstrap_lookup_va=0;\n' if kind=='bootstrap' else
                     'static constexpr uintptr_t scene_base=0,scene_frame_va=0,scene_interpolate_va=0;\n'))
                command=common+['-DWEB_'+kind.upper()+'_INPUT="'+str(target/(kind+'_input.h'))+'"',
                    '-DWEB_'+kind.upper()+'_BINDINGS="'+str(binding)+'"',str(target/'official-web-replay'/('native_'+kind+'_probe.cpp')),
                    str(target/'offline-queue-runtime/empty_publisher.cpp'),str(target/'offline-task-prototype/noop_task.cpp'),'-o',str(target/(kind+'.so'))]
                subprocess.run(command,check=True,timeout=90)
            subprocess.run([str(compiler),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static-libstdc++',
                str(target/'official-web-replay/readonly_memory_reader.cpp'),'-o',str(target/'reader')],check=True,timeout=45)
            report['native_compile_and_link']=True
    report.update(device_contacted=False,network_requests=False,native_execution=False)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
