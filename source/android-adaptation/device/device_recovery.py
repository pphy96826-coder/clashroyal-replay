"""Observe and release ONE previously completed initialization, never republish."""
import json
import os
from pathlib import Path
import traceback
from device_playback import Debugger, checked_receipt


def run(binding_path,destination,prefix):
    destination.mkdir(mode=0o700,exist_ok=False)
    owner=destination.parent.stat();debugger=None
    try:
        if binding_path.name!='bootstrap-v2-binding.json' or binding_path.parent.name!='phone-playback':raise ValueError('not the original initialization')
        binding=json.loads(binding_path.read_text())
        if binding.get('source_execution') or binding.get('scene'):raise ValueError('recovery only supports init-only observer')
        temporary=destination/'tmp';temporary.mkdir(mode=0o700)
        os.environ['TMPDIR']=str(temporary);os.environ['HOME']=str(destination)
        debugger=Debugger(prefix)
        result=debugger.run(binding_path.parent,'bootstrap-v2',observe_original=True,receipt='bootstrap-v2-observe-v1')
        checked_receipt(result)
        with (destination/'result.json').open('x') as stream:json.dump(dict(original_observed_not_republished=True,component_unloaded=True,detached=True),stream)
    except BaseException:
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        raise
    finally:
        if debugger:debugger.close()
        for file in sorted(destination.rglob('*'),reverse=True):os.chown(file,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)
