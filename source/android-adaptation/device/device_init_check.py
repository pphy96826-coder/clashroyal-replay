"""One initialization-only check; no source simulation or scene publication."""
import fcntl,json,os,traceback
from pathlib import Path
from device_playback import Debugger,publish_inputs,checked_receipt,write_new
from device_session import ReadOnlySession
from device_runtime import scene_state
from scene_start_contract import require_idle_lobby


def run(build,destination,prefix):
    destination.mkdir(mode=0o700,exist_ok=False)
    owner=destination.parent.stat();files=next(p for p in destination.parents if p.name=='files')
    debugger=None
    try:
        with (files/'phone-operation.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            binding=json.loads((build/'binding.json').read_text())
            if binding.get('source_execution') is not False or binding.get('scene') is not False:
                raise ValueError('initialization-only component required')
            identity=binding['identity'];ReadOnlySession(identity).verify()
            require_idle_lobby(scene_state(identity))
            preparation=Path(binding['preparation_path'])
            publish_inputs(destination,build,preparation.parent/'runtime','bootstrap-init')
            debugger=Debugger(prefix)
            result=debugger.run(destination,'bootstrap-init')
            checked_receipt(result)
            write_new(destination/'result.json',dict(state='initialization_verified',processing_location='android',
                desktop_backend_used=False,source_sha256=binding['source_html_sha256'],
                source_events_executed=False,scene_published=False,component_unloaded=result.get("component_unloaded",False),
                component_retained_idle=result.get("component_retained_idle",False),debugger_detached=True))
            return result
    except BaseException:
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        raise
    finally:
        if debugger:debugger.close()
        for path in sorted(destination.rglob('*'),reverse=True):
            if path.is_symlink():raise ValueError('unexpected link in initialization check')
            os.chown(path,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)
