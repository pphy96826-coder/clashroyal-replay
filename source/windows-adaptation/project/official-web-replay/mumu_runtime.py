"""Explicit MuMu 6.6.4/Android 12 bridge backend; no permission changes."""
import hashlib
import json
import re
from pathlib import Path
import struct
import subprocess

ROOT=Path(__file__).resolve().parent
BRIDGE_SHA='24d0054a8ea291ece0206f17e8fcdff06f7427a316f6c7133ab89f963c55f8d6'
API_SHA='1ce757b34548a939d3f8bed53565703e77ae821dae1919ebf1b1a0d344a61ff3'
TRANSLATOR_SHA='00d3e51de8666b8cc8f79b529f40dcbe596c7c1b2b0cf508ede96ce2513a2d4a'
PROXY_DL_SHA='38720b762efe9c7f58951a46fb2a47e58f6eb73b295e06e8165d064d1fe9e432'
PROXY_C_SHA='339e9d365ae791793b5e69a4b90855bde4cbfc7c293c37ef4ef2234208a385c2'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def allow_client_read(adb,paths,package='com.tencent.tmgp.supercell.clashroyale'):
    listing=subprocess.check_output(adb+['shell','pm','list','packages','-U',package],text=True,timeout=15)
    rows=[line for line in listing.splitlines() if line.startswith('package:'+package+' uid:')]
    if len(rows)!=1:raise ValueError('one installed game UID required')
    uid=rows[0].split(' uid:',1)[1]
    if not uid.isdigit() or not 10000<=int(uid)<200000:raise ValueError('unexpected game UID')
    for path in paths:
        if not re.fullmatch(r'/data/local/tmp/royale_replay_[A-Za-z0-9_]+/[A-Za-z0-9_.-]+\.so',path):raise ValueError('not an owned native component path')
        # Root retains ownership of the directory. Only the game UID can read
        # these immutable binaries; the game cannot replace them in the directory.
        subprocess.run(adb+['shell','chown',uid+':'+uid,path],check=True,timeout=10)
        subprocess.run(adb+['shell','chmod','500',path],check=True,timeout=10)
    return int(uid)


def validate_device(adb):
    def text(*args):return subprocess.check_output(adb+list(args),text=True,timeout=15).strip()
    if text('shell','getprop','ro.product.cpu.abi')!='x86_64':raise ValueError('MuMu backend requires primary ABI x86_64')
    if text('shell','getprop','ro.dalvik.vm.native.bridge')!='libnb.so':raise ValueError('unrecognized translation bridge')
    for path,expected in (('/system/lib64/libnb.so',BRIDGE_SHA),('/apex/com.android.art/lib64/libnativebridge.so',API_SHA),
            ('/system/lib64/libhoudini.so',TRANSLATOR_SHA),('/system/lib64/arm64/nb/libdl.so',PROXY_DL_SHA),('/system/lib64/arm64/nb/libc.so',PROXY_C_SHA)):
        if text('shell','sha256sum',path).split()[0]!=expected:raise ValueError('unvalidated MuMu NativeBridge build: '+path)
    header=subprocess.check_output(adb+['exec-out','head -c 64 /system/bin/linker64'],timeout=15)
    if len(header)!=64 or header[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',header,18)[0]!=62:
        raise ValueError('host executable is not x86_64 ELF64')
    return dict(primary_abi='x86_64',host_elf_machine=62,guest_elf_machine=183,
        bridge_library_sha256=BRIDGE_SHA,bridge_api_sha256=API_SHA,translator_sha256=TRANSLATOR_SHA,
        guest_proxy_dl_sha256=PROXY_DL_SHA,guest_proxy_c_sha256=PROXY_C_SHA,bridge_version=6)


def compile_helpers(out):
    from portable_config import compiler_command,host_compiler_command
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    host=out/'librr_mumu_host.so';guest=out/'librr_mumu_guest.so'
    common=['-std=c++17','-O2','-g','-Wall','-Wextra','-Werror','-shared','-fPIC','-fvisibility=hidden','-Wl,-z,defs']
    subprocess.run(host_compiler_command()+common+['-static-libstdc++',str(ROOT/'mumu_bridge_host.cpp'),'-ldl','-o',str(host)],check=True,timeout=45)
    subprocess.run(compiler_command()+common+['-nostdlib',str(ROOT/'mumu_bridge_guest.cpp'),'-o',str(guest)],check=True,timeout=45)
    from elf_contract import Elf
    host_elf=Elf(host.read_bytes(),machine=62);Elf(guest.read_bytes())
    return host,guest,host_elf.exports({'rr_mumu_bind','rr_mumu_bind_api','rr_mumu_call','rr_mumu_error'})


def prepare(out,adb):
    from elf_contract import Elf
    from portable_config import ndk_bin
    out=Path(out)
    evidence=validate_device(adb)
    host,guest,exports=compile_helpers(out)
    for remote,local in (('/system/bin/linker64','host-linker64'),
            ('/apex/com.android.runtime/lib64/bionic/libc.so','host-libc.so'),
            ('/apex/com.android.runtime/lib64/bionic/libdl.so','host-libdl.so')):
        subprocess.run(adb+['pull',remote,str(out/local)],check=True,timeout=30)
        Elf((out/local).read_bytes(),machine=62)
    api_profiles={}
    for key,remote,local,names in (
            ('bridge','/system/lib64/libnb.so','host-libnb.so',{'NativeBridgeItf'}),
            ('state','/apex/com.android.art/lib64/libnativebridge.so','host-libnativebridge.so',{'NativeBridgeInitialized'}),
            ('vm','/apex/com.android.art/lib64/libart.so','host-libart.so',{'JNI_GetCreatedJavaVMs'})):
        subprocess.run(adb+['pull',remote,str(out/local)],check=True,timeout=30)
        elf=Elf((out/local).read_bytes(),machine=62)
        api_profiles[key]=dict(library=remote,local=local,sha256=digest(out/local),exports=elf.exports(names))
    directory='/data/local/tmp/royale_replay_mumu_'+hashlib.sha256(host.read_bytes()+guest.read_bytes()).hexdigest()[:20]
    exists=subprocess.run(adb+['shell','test','-d',directory],timeout=10).returncode
    if exists==1:subprocess.run(adb+['shell','mkdir',directory],check=True,timeout=10)
    elif exists:raise RuntimeError('cannot inspect owned bridge directory')
    for path in (host,guest):
        remote=directory+'/'+path.name
        result=subprocess.run(adb+['shell','sha256sum',remote],capture_output=True,text=True,timeout=10)
        if result.returncode:
            subprocess.run(adb+['push',str(path),remote],check=True,timeout=30)
            subprocess.run(adb+['shell','chmod','700',remote],check=True,timeout=10)
        if subprocess.check_output(adb+['shell','sha256sum',remote],text=True,timeout=10).split()[0]!=digest(path):
            raise ValueError('owned bridge binary changed; not replaced')
    loader=Elf((out/'host-libdl.so').read_bytes(),machine=62)
    game_uid=allow_client_read(adb,[directory+'/'+host.name,directory+'/'+guest.name])
    return dict(evidence,host_device_path=directory+'/'+host.name,guest_device_path=directory+'/'+guest.name,
        host_sha256=digest(host),guest_sha256=digest(guest),host_exports=exports,
        host_loader=dict(library='/apex/com.android.runtime/lib64/bionic/libdl.so',
            library_sha256=hashlib.sha256(loader.raw).hexdigest(),exports=loader.exports({'dlopen','dlclose','dlerror'})),
        ndk_compiler_sha256=digest(ndk_bin()/'clang++.exe'),
        game_uid=game_uid,borrowed_api=api_profiles,gameplay_verified=False)


def borrowed_bindings(session,maps,profile,out):
    from mapped_elf import load_bias
    from elf_contract import Elf
    result={}
    for key,item in profile['borrowed_api'].items():
        local=Path(out)/item['local']
        if digest(local)!=item['sha256']:raise ValueError('borrowed API local image changed')
        observed=subprocess.check_output(session.adb+['shell','sha256sum',item['library']],text=True,timeout=10).split()[0]
        if observed!=item['sha256']:raise ValueError('borrowed API device image changed')
        elf=Elf(local.read_bytes(),machine=62);base=load_bias(maps,item['library'],elf)
        name=next(iter(item['exports']));pin=item['exports'][name];va=int(pin['va'],0);address=base+va
        if key=='bridge':
            if struct.unpack('<I',session.read(address,4))[0]!=6:raise ValueError('NativeBridge interface version changed')
            for offset in (24,72,96,112):
                target=elf.relative_pointer(va+offset)
                if struct.unpack('<Q',session.read(address+offset,8))[0]!=base+target:raise ValueError('NativeBridge callback relocation changed')
                if session.read(base+target,32)!=elf.at(target,32):raise ValueError('NativeBridge callback code changed')
        elif hashlib.sha256(session.read(address,pin['size'])).hexdigest()!=pin['sha256']:
            raise ValueError('borrowed ART API code changed')
        result[key]=address
    return result
