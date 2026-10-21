"""Build the same fixed-purpose phone CLI for the native MuMu host ISA."""
from pathlib import Path
import hashlib,json,subprocess
area=Path('work/android-native-runtime');out=area/'selected';source=Path('work/android-mumu-adaptation/source/android-adaptation/native/phone_runtime.cpp')
text=source.read_text().replace('local.royale.replay.android','local.royale.replay.mumu')
text=text.replace('    return result?4:0;','    PyRun_SimpleString("import sys;sys.stdout.flush();sys.stderr.flush()");\n    return result?4:0;')
cpp=area/'phone_runtime_x86.cpp';cpp.write_text(text)
clang=Path('work/package/WinReplay/tools/android-ndk-r27d/toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe')
binary=out/'bin/phone_runtime';binary.parent.mkdir(exist_ok=True)
subprocess.run([str(clang),'--target=x86_64-linux-android24','-DRR_MUMU_NATIVE_X86','-std=c++17','-O2','-Wall','-Wextra','-Werror','-static-libstdc++','-fPIE','-pie','-Wl,-z,defs','-Iwork/android-mumu-support/prefix/include/python3.14',str(cpp),'-L'+str(out/'lib'),'-lpython3.14','-o',str(binary)],check=True)
manifest_path=out/'manifest.json';manifest=json.loads(manifest_path.read_text())
manifest['files']['bin/phone_runtime']=hashlib.sha256(binary.read_bytes()).hexdigest()
manifest['fixed_cli_source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
manifest_path.write_text(json.dumps(manifest,indent=2))
print('built native fixed-purpose Android CLI; no device/game execution',binary.stat().st_size)
