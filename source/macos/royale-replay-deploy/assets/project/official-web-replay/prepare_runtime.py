"""Prepare locally owned binaries; no game attach, patch, replay or rooting."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zipfile


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);a=parser.parse_args()
    os.environ['ROYALE_REPLAY_CONFIG']=str(a.config.resolve())
    from portable_config import config,ndk_bin,runtime_dir
    from client_session import ensure_current_device_binding
    from elf_contract import Elf
    from local_assets import generate
    cfg=config();workspace=a.config.resolve().parent
    if workspace!=Path(__file__).resolve().parent.parent:raise ValueError('configuration belongs to another deployment')
    contract=json.loads((workspace/'profiles/native-contract.json').read_text())
    binding=ensure_current_device_binding();adb=['adb','-s',binding['serial']]
    def command(*args):return subprocess.check_output(adb+list(args),text=True,timeout=20).strip()
    if command('shell','getprop','ro.product.cpu.abi')!='arm64-v8a':raise ValueError('existing emulator is not ARM64')
    if command('shell','id','-u')!='0':raise RuntimeError('existing privileged debugging access is required; no rooting or access bypass performed')
    remote=command('shell','pm','path',contract['package']).splitlines()
    apks=[line.removeprefix('package:') for line in remote if line.startswith('package:') and line.endswith('/base.apk')]
    if len(apks)!=1 or not re.fullmatch(r'/data/app/[A-Za-z0-9_=./+~\-]+/base\.apk',apks[0]):
        raise ValueError('one installed official base APK required')
    servers=sorted(ndk_bin().parent.glob('lib/clang/*/lib/linux/aarch64/lldb-server'))
    if len(servers)!=1:raise ValueError('one NDK AArch64 lldb-server required')
    server=servers[0];server_raw=server.read_bytes();Elf(server_raw)
    out=runtime_dir()
    if out.exists():raise FileExistsError('preserve existing runtime preparation; inspect it or choose a new deployment')
    out.mkdir(parents=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='own-apk-',dir=out) as temp:
        apk=Path(temp)/'base.apk'
        subprocess.run(adb+['pull',apks[0],str(apk)],check=True,timeout=180)
        with zipfile.ZipFile(apk) as z:
            entry=z.getinfo('lib/arm64-v8a/libg.so')
            if entry.file_size!=contract['library_bytes'] or entry.compress_type!=zipfile.ZIP_STORED:
                raise ValueError('installed native library layout differs from the audited build')
            raw=z.read(entry)
            if sha(raw)!=contract['library_sha256']:raise ValueError('unsupported game binary; native adapter not run')
            asset_receipt=generate(z,workspace,contract['map_asset_sha256'])
        elf=Elf(raw)
        for pin in contract['jni_exports']:
            if sha(elf.at(int(pin['va'],0),pin['size']))!=pin['sha256']:raise ValueError('JNI identity differs')
        with apk.open('rb') as f:
            f.seek(entry.header_offset);header=f.read(30)
        if header[:4]!=b'PK\x03\x04':raise ValueError('invalid ZIP local header')
        name_length,extra_length=struct.unpack_from('<HH',header,26)
        mapping_offset=entry.header_offset+30+name_length+extra_length
        if mapping_offset%4096:raise ValueError('native APK mapping not page-aligned')
        (out/'libg.so').write_bytes(raw)
    loader_path='/apex/com.android.runtime/lib64/bionic/libdl.so'
    for name in ('libc','libdl'):
        remote_lib='/apex/com.android.runtime/lib64/bionic/'+name+'.so'
        subprocess.run(adb+['pull',remote_lib,str(out/('loader-'+name+'.so'))],check=True,timeout=30)
        Elf((out/('loader-'+name+'.so')).read_bytes())
    loader=Elf((out/'loader-libdl.so').read_bytes())
    (out/'loader-profile.json').write_text(json.dumps(dict(library=loader_path,
        library_sha256=sha(loader.raw),exports=loader.exports({'dlclose','dlopen','dlerror'})),indent=2)+'\n')
    remote_dir='/data/local/tmp/royale_replay_skill_'+sha(server_raw)[:16]
    remote_server=remote_dir+'/lldb-server'
    exists=subprocess.run(adb+['shell','test','-e',remote_dir],timeout=10).returncode
    if exists==1:
        subprocess.run(adb+['shell','mkdir',remote_dir],check=True,timeout=10)
        subprocess.run(adb+['push',str(server),remote_server],check=True,timeout=30)
        subprocess.run(adb+['shell','chmod','700',remote_server],check=True,timeout=10)
    elif exists!=0:raise RuntimeError('cannot determine existing local debugger directory')
    if command('shell','sha256sum',remote_server).split()[0]!=sha(server_raw):
        raise ValueError('existing debugger differs; not overwritten')
    profile=dict(contract,mapping_file_offset=mapping_offset,debug_server=remote_server,
                 debugger_sha256=sha(server_raw),system_libdl_sha256=sha(loader.raw),assets=asset_receipt)
    (out/'runtime-profile.json').write_text(json.dumps(profile,indent=2)+'\n')
    print(json.dumps(dict(runtime_prepared=True,serial=binding['serial'],library_sha256=sha(raw),
        native_game_calls=False,game_patched=False,network_settings_changed=False),ensure_ascii=False))


if __name__=='__main__':main()
