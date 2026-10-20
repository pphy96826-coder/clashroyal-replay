"""Build an offline embedded-Python payload from the hash-pinned PSF Android release.

No downloads, game APK, personal HTML, cookies, old native handles or addresses.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='11324313957da3736f44e90257304d288864321a4dd376ed0cc35a54eacf9a33'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--payload',type=Path,required=True)
    parser.add_argument('--ndk-bin',type=Path,required=True)
    args=parser.parse_args()
    if hashlib.sha256(args.archive.read_bytes()).hexdigest()!=EXPECTED:
        raise ValueError('official Android Python archive hash differs; not extracted')
    native=ROOT/'build/embedded-native';native.mkdir(parents=True,exist_ok=True)
    extracted=ROOT/'toolchain/python-3.14.8';extracted.mkdir(exist_ok=True)
    with tarfile.open(args.archive,'r:gz') as archive:
        for member in archive.getmembers():
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe archive member')
            if member.issym() or member.islnk():
                # Headers and the explicit SONAME libraries below are ordinary
                # files. Alias symlinks are not necessary for this embedding.
                continue
            if member.isfile():
                target=extracted.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(member) as source, target.open('wb') as output:shutil.copyfileobj(source,output)
    prefix=extracted/'prefix'
    libraries=[prefix/'lib/libpython3.14.so',*sorted((prefix/'lib').glob('lib*_python.so'))]
    for library in libraries:shutil.copyfile(library,native/library.name)
    subprocess.run([str(args.ndk_bin/'clang++'),'--target=aarch64-linux-android24','-std=c++17','-O2','-Wall','-Wextra','-Werror',
        '-fPIC','-shared','-static-libstdc++','-Wl,-z,defs','-I'+str(prefix/'include/python3.14'),
        str(ROOT/'native/python_bridge.cpp'),'-L'+str(prefix/'lib'),'-lpython3.14','-o',str(native/'libreplay_python.so')],check=True,timeout=60)
    subprocess.run([str(args.ndk_bin/'clang++'),'--target=aarch64-linux-android24','-std=c++17','-O2','-Wall','-Wextra','-Werror',
        '-fPIE','-pie','-static-libstdc++','-Wl,-z,defs','-Wl,-rpath,$ORIGIN','-I'+str(prefix/'include/python3.14'),
        str(ROOT/'native/phone_runtime.cpp'),'-L'+str(prefix/'lib'),'-lpython3.14','-o',str(native/'libphone_runtime.so')],check=True,timeout=60)
    bundle=ROOT/'build/python-bundle';bundle.mkdir(exist_ok=True)
    package=bundle/'python-runtime.zip'
    files={}
    for file in sorted((prefix/'lib/python3.14').rglob('*')):
        relative=file.relative_to(prefix)
        if not file.is_file() or file.is_symlink() or any(part in ('test','tests','idlelib','tkinter','turtledemo','__pycache__') for part in relative.parts):continue
        files[relative.as_posix()]=file
    vendor=args.payload/'vendor'
    for relative in ('native_runner/__init__.py','native_runner/royaleapi_replay.py','native_runner/card-aliases.json',
                     'native_runner/tools/__init__.py','native_runner/tools/royaleapi_hog_il.py'):
        files['app/'+relative]=vendor/relative
    files['app/import_replay.py']=args.payload/'official-web-replay/import_replay.py'
    for file in (ROOT/'device').glob('*.py'):files['app/'+file.name]=file
    for name in ('observe_card_levels.py','observe_tower_catalog.py','prepare_native_replay.py','tower_profiles.py','elf_contract.py','local_assets.py','bootstrap_input.py',
                 'run_bootstrap_gate.py','run_scene_gate.py','align_native_deal.py','finalize_replay.py','source_completion.py',
                 'scene_input.py','scene_start_contract.py','timing_policy.py','timing_experiment.py','failure_recovery.py','ability_search.py','diagnostic_prefix.py'):
        files['app/'+name]=args.payload/'official-web-replay'/name
    sources=('official-web-replay/native_bootstrap_probe.cpp','official-web-replay/cache_lease.h',
             'official-web-replay/source_execution.h','official-web-replay/native_tower_check.h',
             'official-web-replay/native_scene_probe.cpp','official-web-replay/replay_frame_clock.h',
             'offline-private-layout/layout_cycle.h','offline-private-map/map_cycle.h',
             'runtime-audit-20261014-direct-route-v12/build/runtime_probe.cpp',
             'offline-queue-runtime/empty_publisher.cpp','offline-queue-runtime/empty_publisher.h',
             'offline-task-prototype/noop_task.cpp','offline-task-prototype/noop_task.h')
    for name in sources:files['app/native-src/'+name]=args.payload/name
    files['app/native-contract.json']=args.payload/'profiles/native-contract.json'
    files['app/native-code-contract.json']=ROOT/'profiles/native-code-contract.json'
    for name in ('FIRSTLIGHT-LICENSE','FIRSTLIGHT-NOTICE'):files['app/'+name]=vendor/name
    manifest={name:hashlib.sha256(file.read_bytes()).hexdigest() for name,file in files.items()}
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,file in files.items():archive.write(file,name)
        archive.writestr('runtime-files.json',json.dumps(manifest,sort_keys=True))
    (bundle/'python-runtime.sha256').write_text(hashlib.sha256(package.read_bytes()).hexdigest())
    report=dict(python_archive_sha256=EXPECTED,python_version='3.14.8',runtime_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
                runtime_files=len(files),native_libraries=[p.name for p in native.glob('*.so')],native_playback_implemented=False)
    (bundle/'embedded-build.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
