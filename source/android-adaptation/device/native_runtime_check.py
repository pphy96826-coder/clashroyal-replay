"""One native-runtime acceptance against our synthetic x86 child, never game."""
import json,os,sys,time,traceback
from pathlib import Path
from device_playback import Debugger
from device_tools import check_own_child
from mumu_platform import host_binary,native_debugger_runtime


def run(prefix,destination):
    destination.mkdir(mode=0o700,exist_ok=False);started=time.monotonic();debugger=None
    try:
        if native_debugger_runtime() is None:raise ValueError('native x86 runtime required')
        temporary=destination/'tmp';temporary.mkdir(mode=0o700)
        os.environ['TMPDIR']=str(temporary);os.environ['HOME']=str(destination)
        debugger=Debugger(prefix)
        if debugger.debugger.GetNumTargets()!=0:raise ValueError('unexpected debugger target')
        passed=check_own_child(debugger.lldb,debugger.debugger,host_binary('debug-child'),destination)
        result=dict(schema='royale-replay.native-runtime-check.v1',processing_location='android',
            python_version=sys.version.split()[0],debugger_version=debugger.lldb.SBDebugger.GetVersionString(),
            native_runtime_arch='x86_64',debugger_loaded=True,targets=0,own_child_native_call_verified=passed,
            own_child_result=44,own_child_arch='x86_64',own_child_built_on_phone=False,
            game_attached=False,native_game_calls=False,game_memory_written=False,
            desktop_backend_used=False,seconds=time.monotonic()-started)
        with (destination/'result.json').open('x') as stream:json.dump(result,stream,indent=2)
        return result
    except BaseException:
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        raise
    finally:
        if debugger:debugger.close()
        owner=destination.parent.stat()
        for path in sorted(destination.rglob('*'),reverse=True):
            if path.is_symlink():raise ValueError('unexpected tool-check link')
            os.chown(path,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)
