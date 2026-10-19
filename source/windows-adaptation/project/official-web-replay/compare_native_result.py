"""Compare native replay evidence with the source; never repair the oracle.

Missing active towers stay unknown, not silently zero. A clean command trace
and a rendered scene are not an exact-result certificate.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bootstrap_input import render
from tower_profiles import bindings


def compare(source, preparation, replay, execution, snapshot):
    render(preparation, True, replay['native_replay'])
    if source['source_sha256'] != preparation['source_sha256'] or source['source_sha256'] != replay['source_sha256']:
        raise ValueError('different source replay')
    expected = preparation['events']
    dispatch = execution['source_dispatch']
    if execution.get('errors') or not execution.get('battle_terminal') or execution['local_driver']['error']:
        raise ValueError('clean terminal execution required')
    if len(dispatch) != len(expected):
        raise ValueError('missing executed commands')
    for index, (event, actual) in enumerate(zip(expected, dispatch)):
        if actual != dict(index=index, kind=event['native_request']['command_type'],
                          tick=event['source_tick_20hz'], flags=3, code=0):
            raise ValueError('source dispatch mismatch')
    for key in ('controller', 'domain', 'battle', 'tick'):
        if execution['scene_state'][key] != snapshot['scene_state'][key]:
            raise ValueError('tower snapshot is from a different replay state')
    if not snapshot.get('battle_terminal'):
        raise ValueError('tower snapshot must be terminal')
    rows, missing = [], []
    for deck in source['decks']:
        side, owner = deck['source_side'], deck['proposed_native_owner']
        oracle = deck.get('oracle_final_hp')
        if not oracle or any(type(oracle.get(k)) is not int for k in ('king', 'princess0', 'princess1')):
            raise ValueError('source final tower HP missing')
        spawn=bindings(preparation)[owner]['spawn_entries']
        for kind,entry in zip(('king','princess0','princess1'),spawn):
            data_id,x=entry['data_id']&0xffffffff,entry['grid_x']*500
            candidates = [t for t in snapshot['active_towers']
                          if (t['owner'], t['data_id'], t['x']) == (owner, data_id, x)]
            if len(candidates) > 1:
                raise ValueError('ambiguous native tower')
            row = dict(side=side, native_owner=owner, tower=kind, native_x=x,
                       source_hp=oracle[kind], native_hp=None, delta=None, match=None)
            if candidates:
                row.update(native_hp=candidates[0]['hp'], delta=candidates[0]['hp'] - oracle[kind],
                           match=candidates[0]['hp'] == oracle[kind])
            else:
                missing.append(dict(side=side, tower=kind,
                                    reason='absent from active graph; destruction needs separate evidence'))
            rows.append(row)
    mismatches = [r for r in rows if r['match'] is False]
    return dict(replay_tag=source['replay_tag'], source_sha256=source['source_sha256'],
                native_terminal_tick=execution['scene_state']['tick'],
                native_simulation_seconds=execution['scene_state']['tick'] / 20,
                source_page_duration_seconds=source['source_duration_seconds'],
                duration_semantics_verified=False, original_random_seed_known=False,
                reconstruction_random_seed=replay['native_replay']['rndSeed'],
                source_commands=len(expected), accepted_at_original_ticks=len(dispatch),
                native_terminal=True, tower_rows=rows, mismatches=mismatches,
                missing_towers=missing, exact_result_verified=not mismatches and not missing,
                snapshot_maintenance_errors=snapshot.get('errors', []),
                version_difference_confirmed=False, fresh_sample_comparison_completed=False)


def main():
    parser = argparse.ArgumentParser()
    for name in ('source', 'preparation', 'replay', 'execution', 'snapshot', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ('source', 'preparation', 'replay', 'execution', 'snapshot')}
    result = compare(**{name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()})
    result['evidence_sha256'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
