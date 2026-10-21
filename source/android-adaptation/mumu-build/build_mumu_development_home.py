from pathlib import Path
import zipfile,hashlib,json,io
root=Path.cwd();out=root/'work/android-mumu-support';apk=root/'work/android-hotfix10/Android-Replay-20261020-hotfix10.apk';device=root/'work/android-mumu-adaptation/source/android-adaptation/device'
with zipfile.ZipFile(apk) as a:
 raw=a.read('assets/python-runtime.zip');assert hashlib.sha256(raw).hexdigest()==a.read('assets/python-runtime.sha256').decode().strip()
with zipfile.ZipFile(io.BytesIO(raw)) as base:
 files={n:base.read(n) for n in base.namelist() if n!='runtime-files.json'}
for name in ['device_tools.py','device_build.py','device_import.py','device_init_check.py','device_session.py','device_runtime.py','device_playback.py','phone_bootstrap_gate.py','run_scene_gate.py','mumu_expression.py','mumu_runtime.py','mumu_platform.py','mumu_compiler.py','mumu_debugger.py','mumu_compile.py','mumu_ownership.py','proc_maps.py']:files['app/'+name]=(device/name).read_bytes()
files['app/mapped_elf.py']=(root/'work/android-mumu-adaptation/source/windows-adaptation/project/official-web-replay/mapped_elf.py').read_bytes()
files['app/device_metadata.py']=(device/'device_metadata.py').read_bytes()
files['app/preparation_hint.py']=(device/'preparation_hint.py').read_bytes()
files['app/seed_search_control.py']=(device/'seed_search_control.py').read_bytes()
files['app/native_runtime_check.py']=(device/'native_runtime_check.py').read_bytes()
files['app/mumu_elf.py']=(root/'work/android-mumu-adaptation/source/windows-adaptation/project/official-web-replay/elf_contract.py').read_bytes()
stubs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'arm-stubs').glob('*.so')}
for name in stubs:files['app/mumu-support/arm-stubs/'+name]=(out/'arm-stubs'/name).read_bytes()
files['app/mumu-support/arm-stubs/manifest.json']=json.dumps(stubs,sort_keys=True).encode()
for p in (out/'host').iterdir():
 if p.is_file():files['app/mumu-support/host/'+p.name]=p.read_bytes()
for p in (out/'helpers').iterdir():
 if p.is_file():files['app/mumu-support/helpers/'+p.name]=p.read_bytes()
compiler=root/'work/android-native-compiler/selected'
for p in compiler.rglob('*'):
 if p.is_file():files['app/mumu-support/compiler/'+p.relative_to(compiler).as_posix()]=p.read_bytes()
native_runtime=root/'work/android-native-runtime/selected'
for p in native_runtime.rglob('*'):
    if p.is_file():files['app/mumu-support/runtime/'+p.relative_to(native_runtime).as_posix()]=p.read_bytes()
manifest={n:hashlib.sha256(b).hexdigest() for n,b in files.items()};files['runtime-files.json']=json.dumps(manifest,sort_keys=True).encode()
archive=out/'mumu-development-python.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
 for n,b in files.items():z.writestr(n,b)
sha=hashlib.sha256(archive.read_bytes()).hexdigest();(out/'development-bundle.json').write_text(json.dumps({'sha256':sha,'bytes':archive.stat().st_size,'files':len(files),'home':'mumu-python-dev-'+sha[:16]},indent=2),encoding='utf-8')
print(json.dumps({'sha256':sha,'bytes':archive.stat().st_size,'files':len(files)}))
