"""Generate source-specific native preparation entirely on the phone.

Reuses the desktop's unmodified public card/tower observers and preparation
rules. It does not attach, publish, step or replace a native battle.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import traceback

from device_session import bind, ReadOnlySession
from device_runtime import prepare as prepare_runtime


def run(source, output, apk):
    output.mkdir(exist_ok=False, mode=0o700)
    try:
        document = json.loads(source.read_text())
        if document['dropped_actions'] or document['unresolved_base_card_ids']:
            raise ValueError('source is incomplete or contains unresolved cards')
        identity = bind(apk)
        runtime = prepare_runtime(identity, output/'runtime')
        with (output/'observation.json').open('x') as stream:
            json.dump(dict(identity=identity, native_calls=False), stream)
        modules = (
            ('observe_card_levels', ['--observation', str(output/'observation.json'),
                                    '--source', str(source), '--output', str(output/'levels.json')]),
            ('observe_tower_catalog', ['--observation', str(output/'observation.json'),
                                      '--output', str(output/'towers.json')]),
            ('prepare_native_replay', [str(source), '--level-evidence', str(output/'levels.json'),
                                       '--tower-evidence', str(output/'towers.json'),
                                       '--output', str(output/'preparation.json')]),
        )
        old = sys.argv
        try:
            for module, arguments in modules:
                sys.argv = [module, *arguments]
                with contextlib.redirect_stdout(io.StringIO()):
                    runpy.run_module(module, run_name='__main__')
        finally:
            sys.argv = old
        ReadOnlySession(identity).verify()
        prepared = json.loads((output/'preparation.json').read_text())
        if len(prepared['events']) != document['retained_action_count']:
            raise ValueError('preparation lost source events')
        levels = json.loads((output/'levels.json').read_text())
        towers = json.loads((output/'towers.json').read_text())
        report = dict(schema='royale-replay.android-native-preparation.v1', state='prepared_not_executed',
                      processing_location='android', desktop_backend_used=False,
                      source_sha256=document['source_sha256'],
                      source_manifest_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      retained_events=len(prepared['events']), native_card_count=len(levels['cards']),
                      native_tower_types=len(towers['towers']), native_calls=False,
                      game_memory_written=False, debugger_attached=False,
                      global_execution_delay_ticks=20, standalone_playback_ready=False,
                      native_execution_pending=True)
        report['installed_map_assets_verified']=runtime['assets']['generated_from_local_apk']
        report['native_worker_bound']=True
        report['local_loader_exports_verified']=True
        with (output/'result.json').open('x') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        return report
    except Exception:
        with (output/'error.txt').open('x') as stream:
            stream.write(traceback.format_exc())
        raise
    finally:
        # Only files just created inside this fresh app-owned attempt. Never
        # change game files, permissions, security settings or another app.
        owner = output.parent.stat()
        for path in sorted(output.rglob('*'), reverse=True):
            if path.is_symlink():
                raise ValueError('unexpected link in private preparation')
            os.chown(path, owner.st_uid, owner.st_gid)
        os.chown(output, owner.st_uid, owner.st_gid)
