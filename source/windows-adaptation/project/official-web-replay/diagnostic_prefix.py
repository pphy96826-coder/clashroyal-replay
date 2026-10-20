"""Explicit, evidence-bound prefix; never a complete replay or cache entry."""
import copy
from bootstrap_input import validate, render


def preview_inputs(preparation, report, receipt, *, authorized=False):
    if authorized is not True:
        raise ValueError('diagnostic preview requires explicit user authorization')
    validate(preparation)
    if not (receipt.get('detached') and receipt.get('component_unloaded') and receipt.get('source_bootstrap_verified')):
        raise ValueError('original native attempt was not safely released')
    if report.get('error') != 114 or report.get('native_code') != 4:
        raise ValueError('only the diagnosed settlement rejection is supported')
    count = report.get('failed_index'); events = preparation['events']
    if type(count) is not int or not 0 < count < len(events) or report.get('native_accepted') != count:
        raise ValueError('invalid accepted prefix')
    commands = report.get('commands', []); dispatch = report.get('dispatch', [])
    if len(commands) != count + 1 or len(dispatch) != count + 1:
        raise ValueError('expected exactly one rejected command after the accepted prefix')
    for i, entry in enumerate(dispatch[:count]):
        if entry != dict(index=i, kind=commands[i]['ct'], tick=events[i]['source_tick_20hz'], flags=3, code=0):
            raise ValueError('prefix was not genuinely executed at source ticks')
    if dispatch[count] != dict(index=count, kind=153, tick=events[count]['source_tick_20hz'], flags=3, code=4):
        raise ValueError('rejected command differs from diagnosed source event')
    stop = report.get('battle_state', {}).get('first_settlement_tick')
    if type(stop) is not int or not events[count-1]['source_tick_20hz'] < stop < dispatch[count]['tick']:
        raise ValueError('missing verified diagnostic boundary')
    metadata = dict(diagnostic_only=True, original_source_event_count=len(events), preview_event_count=count,
                    stop_tick=stop, complete_replay_verified=False, original_source_events=copy.deepcopy(events))
    subset = copy.deepcopy(preparation)
    subset.update(events=copy.deepcopy(events[:count]), source_action_count=count, preserved_event_count=count,
                  diagnostic_preview=metadata, complete_native_replay=False, executable=False)
    replay = copy.deepcopy(preparation['initialization_only']); replay['cmd'] = copy.deepcopy(commands[:count])
    render(subset, True, replay)
    native = dict(schema='official-web-replay.diagnostic-preview.v1', diagnostic_only=True,
                  source_sha256=preparation['source_sha256'], native_replay=replay,
                  native_accepted_events=count, diagnostic_preview=metadata)
    return subset, native
