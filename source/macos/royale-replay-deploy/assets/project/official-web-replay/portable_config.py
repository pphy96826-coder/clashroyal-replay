"""Receiving-machine configuration; no author paths or captured identities."""
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parent
CONFIG=Path(os.environ.get('ROYALE_REPLAY_CONFIG',str(WORKSPACE/'deploy-config.json')))


def config():
    return json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}


def ndk_bin():
    value=config().get('ndk_bin') or os.environ.get('ROYALE_NDK_BIN')
    if value:return Path(value).expanduser().resolve()
    sdk=Path(os.environ.get('ANDROID_SDK_ROOT',str(Path.home()/'Library/Android/sdk')))
    return sdk/'ndk/30.0.16248370/toolchains/llvm/prebuilt/darwin-x86_64/bin'


def instance_dir():
    return Path(config().get('vm_dir',str(Path.home()/'Library/Application Support/com.netease.mumu.nemux/vms/1'))).expanduser().resolve()


def instance_name():return config().get('instance_name','我的安卓-1')
def runtime_dir():return WORKSPACE/'runtime/native'
def runtime_profile():return json.loads((runtime_dir()/'runtime-profile.json').read_text())
def deployment_id():
    import re
    value=config().get('deployment_id','')
    if not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('deployment ID missing; install into a new target first')
    return value
def bridge_queue():
    value=config().get('deployment_id')
    return Path.home()/'Library/Application Support/FirstLightReplayBridge'/(deployment_id() if value else 'unconfigured')/'jobs'
def operation_lock():
    import hashlib
    identifier=hashlib.sha256(str(instance_dir()).encode()).hexdigest()[:24]
    return Path.home()/'Library/Application Support/RoyaleReplayLocks'/(identifier+'.lock')
def debug_server():return runtime_profile()['debug_server']
def debug_port():return int(config().get('debug_port',56115))

# Finder does not inherit shell startup files. Preserve the configured adb's
# actual directory for every worker/subprocess, without editing shell settings.
_adb=config().get('adb_path')
if _adb and Path(_adb).is_file():
    os.environ['PATH']=str(Path(_adb).parent)+os.pathsep+os.environ.get('PATH','')
