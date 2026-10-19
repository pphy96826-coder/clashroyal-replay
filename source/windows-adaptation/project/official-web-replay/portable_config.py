"""Windows fork configuration. No automatic device or network selection."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parent
CONFIG=Path(os.environ.get('ROYALE_REPLAY_CONFIG',str(WORKSPACE/'deploy-config.json')))

def config():return json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.is_file() else {}
def windows():return platform.system()=='Windows'
def local_data():
    if windows():
        value=os.environ.get('LOCALAPPDATA')
        if not value:raise RuntimeError('LOCALAPPDATA missing; no shared directory fallback')
        return Path(value)
    return Path.home()/'.local/share'

def ndk_bin():
    value=config().get('ndk_bin') or os.environ.get('ROYALE_NDK_BIN')
    if value:return Path(value).expanduser().resolve()
    base=Path(os.environ.get('ANDROID_SDK_ROOT',str(local_data()/'Android/Sdk')))
    tag={'Windows':'windows-x86_64','Darwin':'darwin-x86_64','Linux':'linux-x86_64'}.get(platform.system())
    if not tag:raise RuntimeError('unsupported build host')
    return base/'ndk/30.0.16248370/toolchains/llvm/prebuilt'/tag/'bin'

def compiler_command(system=None):
    host=system or platform.system()
    return [str(ndk_bin()/('clang++.exe' if host=='Windows' else 'clang++')),'--target=aarch64-linux-android24']
def native_transport():return config().get('native_transport','arm64-native')
def translated():return native_transport()=='mumu-nativebridge-v1'
def host_compiler_command():
    return [str(ndk_bin()/('clang++.exe' if windows() else 'clang++')),'--target=x86_64-linux-android24'] if translated() else compiler_command()
def prepare_lldb_environment(cfg=None):
    cfg=config() if cfg is None else cfg
    lldb=Path(cfg['lldb_path']) if cfg.get('lldb_path') else None
    # lldb.exe in the Windows NDK depends on the sibling bundled Python DLL.
    if lldb and windows():
        python=lldb.parent.parent/'python3'
        if python.is_dir():
            os.environ['PATH']=str(python)+os.pathsep+str(lldb.parent)+os.pathsep+os.environ.get('PATH','')
def readelf_command():return [str(ndk_bin()/('llvm-readelf.exe' if windows() else 'llvm-readelf'))]
def lldb_command():
    value=config().get('lldb_path')
    if not value:raise RuntimeError('configure a Python-enabled LLDB path before playback')
    prepare_lldb_environment()
    return [str(Path(value).resolve())]

def binding_file():
    value=config().get('device_binding_file')
    if not value:raise ValueError('explicit local device binding file required')
    return Path(value).expanduser().resolve()
def instance_dir():return binding_file().parent
def instance_name():return config().get('instance_name','')
def runtime_dir():return WORKSPACE/'runtime/native'
def runtime_profile():return json.loads((runtime_dir()/'runtime-profile.json').read_text(encoding='utf-8'))
def deployment_id():
    value=config().get('deployment_id','')
    if not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('deployment ID missing')
    return value
def bridge_queue():return local_data()/'RoyaleReplayBridge'/(deployment_id() if config().get('deployment_id') else 'unconfigured')/'jobs'
def operation_lock():
    identity=os.path.normcase(str(binding_file()))
    return local_data()/'RoyaleReplayLocks'/(hashlib.sha256(identity.encode()).hexdigest()[:24]+'.lock')
def debug_server():return runtime_profile()['debug_server']
def debug_port():return int(config()['debug_port'])

_adb=config().get('adb_path')
if _adb and Path(_adb).is_file():
    os.environ['PATH']=str(Path(_adb).parent)+os.pathsep+os.environ.get('PATH','')
os.environ['PYTHONUTF8']='1'
os.environ['PYTHONIOENCODING']='utf-8'
