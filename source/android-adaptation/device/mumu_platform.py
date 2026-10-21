"""Exact Windows MuMu/Android 12 profile, checked locally on Android."""
import hashlib,os,struct,subprocess,sys
from pathlib import Path
PINS={
'/system/lib64/libnb.so':'24d0054a8ea291ece0206f17e8fcdff06f7427a316f6c7133ab89f963c55f8d6',
'/apex/com.android.art/lib64/libnativebridge.so':'1ce757b34548a939d3f8bed53565703e77ae821dae1919ebf1b1a0d344a61ff3',
'/system/lib64/libhoudini.so':'00d3e51de8666b8cc8f79b529f40dcbe596c7c1b2b0cf508ede96ce2513a2d4a',
'/system/lib64/arm64/nb/libdl.so':'38720b762efe9c7f58951a46fb2a47e58f6eb73b295e06e8165d064d1fe9e432',
'/system/lib64/arm64/nb/libc.so':'339e9d365ae791793b5e69a4b90855bde4cbfc7c293c37ef4ef2234208a385c2'}
_validated=False

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def system_env():
    environment=dict(os.environ)
    for key in ('LD_LIBRARY_PATH','LD_PRELOAD'):environment.pop(key,None)
    return environment

def prop(name):return subprocess.check_output(['/system/bin/getprop',name],text=True,timeout=5,env=system_env()).strip()
def enabled():
    global _validated
    if _validated:return True
    if prop('ro.product.cpu.abi')!='x86_64':return False
    if prop('ro.dalvik.vm.native.bridge')!='libnb.so':raise ValueError('unrecognized x86 Android translation bridge')
    for path,expected in PINS.items():
        if sha(path)!=expected:raise ValueError('unvalidated MuMu system image: '+path)
    raw=Path('/system/bin/linker64').read_bytes()[:64]
    if raw[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',raw,18)[0]!=62:raise ValueError('MuMu host is not ELF64 x86_64')
    _validated=True;return True

def support():return Path(__file__).resolve().parent/'mumu-support'

def host_binary(name):
    import json
    if name not in ('debug-child','lldb-server'):raise ValueError('unknown owned host binary')
    directory=support()/'host';manifest=json.loads((directory/'manifest.json').read_text())
    raw=(directory/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest[name] or raw[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',raw,18)[0]!=62:
        raise ValueError('MuMu host binary differs: '+name)
    if not os.access(directory/name,os.X_OK):raise ValueError('owned host binary is not executable')
    return directory/name
def arm_stubs():
    import json
    directory=support()/'arm-stubs';manifest=json.loads((directory/'manifest.json').read_text())
    if set(manifest)!={'libc.so','libm.so','libdl.so','liblog.so','libandroid.so'}:raise ValueError('incomplete ARM64 linker contract')
    for name,digest in manifest.items():
        raw=(directory/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest or raw[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',raw,18)[0]!=183:raise ValueError('ARM64 link stub differs: '+name)
    return directory


_compiler_ready=None
_native_runtime_ready=None


def native_debugger_runtime():
    """Only native x86 Python may import the native x86 LLDB extension."""
    global _native_runtime_ready
    # /proc/self/exe can name Houdini's host loader for a translated ARM
    # executable. Use CPython's compiled ABI, never the guest kernel uname.
    abi=getattr(sys.implementation,'_multiarch','')
    if abi.startswith('aarch64-'):return None
    if not abi.startswith('x86_64-') or not enabled():raise ValueError('unsupported runtime ABI: '+abi)
    if _native_runtime_ready is not None:return _native_runtime_ready
    import json
    directory=support()/'runtime';manifest=json.loads((directory/'manifest.json').read_text())
    files=manifest.get('files',{})
    if manifest.get('machine')!=62 or not 8<=len(files)<=256 or not {'bin/phone_runtime','lib/libpython3.14.so','lib/liblldb.so'}<=set(files):raise ValueError('incomplete native runtime manifest')
    total=0
    for name,digest in files.items():
        if Path(name).is_absolute() or '..' in Path(name).parts or not name.startswith(('bin/','lib/')):raise ValueError('unsafe native runtime path')
        path=directory/name;total+=path.stat().st_size
        if total>96*1024*1024:raise ValueError('native runtime exceeds bounds')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('native runtime differs: '+name)
        if raw[:4]==b'\x7fELF' and (len(raw)<64 or struct.unpack_from('<H',raw,18)[0]!=62):raise ValueError('native runtime ELF machine differs')
    compiler=json.loads((support()/'compiler/manifest.json').read_text())['files']
    for name,digest in manifest.get('shared_compiler_files',{}).items():
        if Path(name).is_absolute() or '..' in Path(name).parts or not name.startswith('lib/'):raise ValueError('unsafe shared native dependency')
        if compiler.get(name)!=digest or hashlib.sha256((support()/'compiler'/name).read_bytes()).hexdigest()!=digest:raise ValueError('shared native runtime dependency differs')
    _native_runtime_ready=directory
    return directory
def native_compiler():
    global _compiler_ready
    if _compiler_ready is not None:return _compiler_ready
    import json
    if not enabled():raise ValueError('verified MuMu image required')
    directory=support()/'compiler';manifest=json.loads((directory/'manifest.json').read_text())
    expected=manifest.get('files',{})
    if not 2<=len(expected)<=32 or not {'bin/clang++','bin/ld.lld'}<=set(expected):
        raise ValueError('incomplete native compiler manifest')
    total=0
    for name,digest in expected.items():
        path=directory/name
        if Path(name).is_absolute() or '..' in Path(name).parts or not name.startswith(('bin/','lib/')):
            raise ValueError('unsafe native compiler member')
        total+=path.stat().st_size
        if total>256*1024*1024:raise ValueError('native compiler exceeds byte bound')
        checksum=hashlib.sha256()
        with path.open('rb') as stream:
            header=stream.read(64);checksum.update(header)
            while block:=stream.read(1024*1024):checksum.update(block)
        if checksum.hexdigest()!=digest or header[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',header,18)[0]!=62:
            raise ValueError('native compiler or dependency differs: '+name)
    for name in ('bin/clang++','bin/ld.lld'):
        if not os.access(directory/name,os.X_OK):raise ValueError('verified compiler is not executable')
    environment=system_env();environment['LD_LIBRARY_PATH']=str(directory/'lib')
    _compiler_ready=(directory/'bin/clang++',directory/'bin/ld.lld',environment)
    return _compiler_ready
