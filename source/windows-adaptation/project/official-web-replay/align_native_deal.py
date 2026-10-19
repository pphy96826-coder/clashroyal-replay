"""Invert an observed native deal; never claim the hidden original hand."""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def align(preparation, observation):
    if not observation.get('source_bootstrap_verified') or observation.get('errors'):
        raise ValueError('native deal observation did not complete cleanly')
    fields = observation['fields']
    if len(fields) != 96:
        raise ValueError('wrong native observation format')
    result = copy.deepcopy(preparation)
    for participant in result['participants'].values():
        side = participant['native_owner']
        permutation = [(fields[94 + side] >> (8 * i)) & 255 for i in range(8)]
        if sorted(permutation) != list(range(8)):
            raise ValueError('native hand/queue is not a permutation')
        key = 'deck' + str(side)
        entries = result['initialization_only']['battle'][key]['sp']
        observed_cards = [fields[16 + (side * 8 + i) * 4] for i in range(8)]
        if observed_cards != [c['d'] for c in entries]:
            raise ValueError('observation belongs to another physical deck')
        desired = participant['cycle']['opening'] + participant['cycle']['queue']
        by_id = {c['d']: c for c in entries}
        physical = [None] * 8
        for dealt, physical_index in enumerate(permutation):
            physical[physical_index] = by_id[desired[dealt]]
        result['initialization_only']['battle'][key]['sp'] = physical
        participant['deck_order'] = [c['d'] for c in physical]
        participant['native_deal_alignment'] = {
            'observed_permutation': permutation,
            'desired_deal': desired,
            'requires_second_native_verification': True,
        }
        for event in result['events']:
            if event['source_side'] in result['participants'] and result['participants'][event['source_side']]['native_owner'] == side and event['kind'] == 'play_card':
                event['native_request']['deck_index'] = participant['deck_order'].index(event['base_data_id'])
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('preparation', type=Path)
    p.add_argument('observation', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    doc = align(json.loads(args.preparation.read_text(encoding="utf-8")), json.loads(args.observation.read_text(encoding="utf-8")))
    doc['native_deal_observation_sha256'] = hashlib.sha256(args.observation.read_bytes()).hexdigest()
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(json.dumps({'aligned_physical_decks': 2, 'native_deal_verified': False, 'events': len(doc['events'])}))


if __name__ == '__main__':
    main()
