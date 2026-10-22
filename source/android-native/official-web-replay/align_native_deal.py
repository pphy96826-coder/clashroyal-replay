"""Invert an observed native deal; never claim the hidden original hand."""
import argparse
import copy
import hashlib
import json
import itertools
from pathlib import Path
from prepare_native_replay import NOT_IN_OPENING, cycle_slots
from tower_profiles import bind_initial_towers


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


# Native deal (0x120ff14): cards whose definition flags "not in starting hand"
# (+0x250: Elixir Collector, Mirror) are set aside; the four hand cards are drawn
# at random from the rest (deck order); the set-aside cards are then appended at
# the END of what remains, and the last four are drawn at random from that. The
# draws come from a generator seeded per battle (0x153885c / 0x15388cc), so a
# flagged card's dealt position depends only on the seed, never on deck order.
DEAL_SEED_INFEASIBLE = 'native deal seed cannot place Collector/Mirror as the page requires'


def engine_draws(physical, dealt, held=NOT_IN_OPENING):
    """The random draw indices that turn deck order `physical` into `dealt`
    (hand then queue); None when the observation does not fit the model."""
    rest = [c for c in physical if c not in held]; later = [c for c in physical if c in held]; draws = []
    for k, card in enumerate(dealt):
        if k == 4: rest, later = rest + later, []
        if card not in rest: return None
        draws.append(rest.index(card)); rest.remove(card)
    return draws


def engine_deal(physical, draws, held=NOT_IN_OPENING):
    rest = [c for c in physical if c not in held]; later = [c for c in physical if c in held]; dealt = []
    for k, index in enumerate(draws):
        if k == 4: rest, later = rest + later, []
        dealt.append(rest.pop(index))
    return dealt


def deck_order_for(desired, draws, held=NOT_IN_OPENING):
    """Deck order whose native deal under `draws` is `desired`; None if the seed
    puts the set-aside cards elsewhere (their positions depend on the seed only)."""
    count = sum(c in held for c in desired)
    tokens = [('n', i) for i in range(len(desired) - count)] + [('h', i) for i in range(count)]
    dealt = engine_deal(tokens, draws, held={t for t in tokens if t[0] == 'h'})
    if any((t[0] == 'h') != (card in held) for t, card in zip(dealt, desired)): return None
    slot = {t: card for t, card in zip(dealt, desired)}
    return [slot[t] for t in tokens]


def calibrate_held(entries, actual, perm, plays, desired, seen, owner):
    """Exact calibration for a deck holding Collector/Mirror: one observation gives
    the seed's draws; pick the closest stream-legal deal the seed can produce."""
    physical = [c['d'] for c in entries]
    draws = engine_draws(physical, actual)
    if draws is None: raise ValueError('native deal does not match the set-aside model')
    by_id = {c['d']: c for c in entries}
    held_slots = {k for k, card in enumerate(engine_deal(list(range(8)), draws, held={i for i, c in enumerate(physical) if c in NOT_IN_OPENING}))
                  if physical[card] in NOT_IN_OPENING}
    tried = {tuple(previous[owner]) for previous in seen} | {tuple(physical)}
    candidates = []
    for order in itertools.permutations(actual):
        if {k for k, c in enumerate(order) if c in NOT_IN_OPENING} != held_slots: continue
        slots = cycle_slots(list(order[:4]), list(order[4:]), plays)
        if slots is None: continue
        deck = deck_order_for(list(order), draws)
        if deck is None or tuple(deck) in tried: continue
        score = (sum(a != b for a, b in zip(order, desired)), sum(a != b for a, b in zip(order, actual)))
        candidates.append((score, list(order), deck, slots))
    if not candidates: raise ValueError(DEAL_SEED_INFEASIBLE)
    _, chosen, deck, slots = min(candidates, key=lambda c: c[0])
    return [by_id[c] for c in deck], chosen, slots


def deck_fingerprint(doc):
    return tuple(tuple(c['d'] for c in doc['initialization_only']['battle']['deck'+str(s)]['sp']) for s in (0,1))


def calibrate(preparation,observation,seen=()):
    """Check the actual native deal before executing even one source command.

    Dealing can depend on card identities (not just a fixed permutation). Search
    full-stream-legal openings instead of assuming first-seen cards were held
    initially. Only fresh, clean initialization probes are used by callers.
    """
    # Retain the existing full physical-deck/permutation identity checks.
    align(preparation,observation)
    result=bind_initial_towers(preparation,observation)
    ready=True
    for side,part in result['participants'].items():
        owner=part['native_owner'];entries=result['initialization_only']['battle']['deck'+str(owner)]['sp']
        packed=observation['fields'][94+owner];perm=[(packed>>(8*i))&255 for i in range(8)]
        actual=[entries[i]['d'] for i in perm]
        plays=[e['base_data_id'] for e in result['events'] if e['source_side']==side and e['kind']=='play_card']
        slots=cycle_slots(actual[:4],actual[4:],plays)
        # A dealt opening holding Collector/Mirror is rejected natively: recalibrate.
        if set(actual[:4])&set(NOT_IN_OPENING):slots=None
        if set(actual)&set(NOT_IN_OPENING) and slots is None:
            ready=False
            physical,desired,slots=calibrate_held(entries,actual,perm,plays,part['cycle']['opening']+part['cycle']['queue'],seen,owner)
            result['initialization_only']['battle']['deck'+str(owner)]['sp']=physical
            part['deck_order']=[c['d'] for c in physical]
        elif slots is None:
            ready=False;ordered=list(dict.fromkeys(plays+actual));candidates=[]
            for opening in itertools.combinations(ordered,4):
                if set(opening)&set(NOT_IN_OPENING):continue
                rest=[c for c in ordered if c not in opening]
                for queue in itertools.permutations(rest):
                    candidate_slots=cycle_slots(opening,queue,plays)
                    if candidate_slots is None:continue
                    desired=list(opening)+list(queue);physical=[None]*8
                    by_id={c['d']:c for c in entries}
                    for i,index in enumerate(perm):physical[index]=by_id[desired[i]]
                    signature=tuple(c['d'] for c in physical)
                    forbidden={tuple(previous[owner]) for previous in seen}
                    if signature in forbidden:continue
                    held=[queue.index(c) for c in NOT_IN_OPENING if c in queue]
                    score=(len(set(opening)-set(actual[:4])),sum(a!=b for a,b in zip(desired,actual)),held,desired)
                    candidates.append((score,physical,desired,candidate_slots))
            if not candidates:raise ValueError('no untested full-stream-legal native deal candidate remains')
            _,physical,desired,slots=min(candidates,key=lambda c:c[0])
            result['initialization_only']['battle']['deck'+str(owner)]['sp']=physical
            part['deck_order']=[c['d'] for c in physical]
        else:desired=actual
        part['cycle'].update(opening=desired[:4],queue=desired[4:],slots=slots,
                             native_deal_verified=actual==desired,inference='native-observed/full-stream-checked')
        index=0
        for event in result['events']:
            if event['source_side']==side and event['kind']=='play_card':
                event['native_request']['deck_index']=part['deck_order'].index(event['base_data_id'])
                event['native_request']['expected_cycle_slot']=slots[index];index+=1
    result['native_deal_ready']=ready
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('preparation', type=Path)
    p.add_argument('observation', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--calibrate',action='store_true')
    p.add_argument('--seen',type=Path)
    args = p.parse_args()
    prep=json.loads(args.preparation.read_text());observed=json.loads(args.observation.read_text())
    doc = calibrate(prep,observed,json.loads(args.seen.read_text()) if args.seen else ()) if args.calibrate else align(prep,observed)
    doc['native_deal_observation_sha256'] = hashlib.sha256(args.observation.read_bytes()).hexdigest()
    with args.output.open('x') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(json.dumps({'aligned_physical_decks': 2, 'native_deal_verified': False, 'events': len(doc['events'])}))


if __name__ == '__main__':
    main()
