"""Refresh explicitly listed owned replay sources in a verified offline build.

No downloads or unrelated dependency changes. Full builds use stage_python.py.
"""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    bundle=ROOT/'build/python-bundle'
    package=bundle/'python-runtime.zip'
    if hashlib.sha256(package.read_bytes()).hexdigest()!=(bundle/'python-runtime.sha256').read_text().strip():
        raise ValueError('input runtime hash differs')
    with zipfile.ZipFile(package) as archive:
        contents={name:archive.read(name) for name in archive.namelist()}
    manifest=json.loads(contents['runtime-files.json'])
    if set(contents)!=(set(manifest)|{'runtime-files.json'}):raise ValueError('unexpected input members')
    for name,digest in manifest.items():
        if hashlib.sha256(contents[name]).hexdigest()!=digest:raise ValueError('input member differs: '+name)
    updates={'app/device_playback.py':ROOT/'device/device_playback.py',
             'app/phone_bootstrap_gate.py':ROOT/'device/phone_bootstrap_gate.py',
             'app/device_build.py':ROOT/'device/device_build.py',
             'app/native-code-contract.json':ROOT/'profiles/native-code-contract.json'}
    project=ROOT.parent/'official-web-replay'
    for name in ('align_native_deal.py','tower_profiles.py','bootstrap_input.py','prepare_native_replay.py','source_completion.py','scene_input.py','run_scene_gate.py','finalize_replay.py','failure_recovery.py','ability_search.py','diagnostic_prefix.py'):
        updates['app/'+name]=project/name
    for name in ('native_bootstrap_probe.cpp','native_scene_probe.cpp','native_tower_check.h','source_execution.h'):
        updates['app/native-src/official-web-replay/'+name]=project/name
    for name,path in updates.items():
        if name not in manifest and name not in ('app/failure_recovery.py','app/ability_search.py','app/diagnostic_prefix.py'):raise ValueError('unexpected update path: '+name)
        contents[name]=path.read_bytes();manifest[name]=hashlib.sha256(contents[name]).hexdigest()
    contents['runtime-files.json']=json.dumps(manifest,sort_keys=True).encode()
    temporary=package.with_suffix('.new.zip')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,content in sorted(contents.items()):archive.writestr(name,content)
    temporary.replace(package)
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    (bundle/'python-runtime.sha256').write_text(digest)
    report=json.loads((bundle/'embedded-build.json').read_text())
    report['runtime_sha256']=digest
    (bundle/'embedded-build.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(runtime_sha256=digest,changed_members=sorted(updates)+['runtime-files.json'])))

if __name__=='__main__':main()
