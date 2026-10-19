"""Pure source-to-probe input; reject malformed identities before ANY ADB call."""
import json
from tower_profiles import bindings,render_towers


def validate(doc):
    replay = doc['initialization_only']
    battle = replay['battle']
    participants = doc['participants']
    if len(participants) != 2 or sorted(p['native_owner'] for p in participants.values()) != [0, 1]:
        raise ValueError('two distinct native owners required')
    pairs = []
    towers=bindings(doc)
    for participant in participants.values():
        owner = participant['native_owner']
        avatar = battle['avatar'+str(owner)]
        if 'accountID' in avatar:
            raise ValueError('nested accountID is invalid: official parser needs literal dotted keys')
        pair = [avatar.get('accountID.hi'), avatar.get('accountID.lo')]
        if any(type(v) is not int or not 0 <= v <= 0x7fffffff for v in pair) or pair == [0, 0]:
            raise ValueError('nonzero, explicit int32 participant identity required')
        expected = participant['synthetic_native_identity']
        if pair != [expected['hi'], expected['lo']]:
            raise ValueError('avatar identity differs from bound local participant')
        if pair in pairs:
            raise ValueError('native participant identities must be distinct')
        pairs.append(pair)
        deck = battle['deck'+str(owner)]
        tower=towers[owner]
        expected=[] if tower['card_key']=='tower-princess' else [{'d':tower['support_id'],'l':tower['internal_level']}]
        if deck.get('sc',[])!=expected:
            raise ValueError('tower override differs from the native169 source binding')
        if battle['hbd'][owner]['kt']!=16:raise ValueError('unverified king level')
        cards = deck['sp']
        order = [c['d'] for c in cards]
        if len(cards) != 8 or len(set(order)) != 8 or order != participant['deck_order']:
            raise ValueError('physical deck does not match participant binding')
        desired = participant['cycle']['opening'] + participant['cycle']['queue']
        if len(desired) != 8 or sorted(desired) != sorted(order):
            raise ValueError('desired hand/queue does not match physical deck')
    events = doc['events']
    if not events or len(events) != doc['source_action_count'] or len(events) != doc['preserved_event_count']:
        raise ValueError('source event count mismatch')
    previous = -1
    for event in events:
        tick = event['source_tick_20hz']
        if type(tick) is not int or not previous <= tick <= 7200:
            raise ValueError('source ticks must be ordered, integral and bounded')
        previous = tick
        participant = participants[event['source_side']]
        request = event['native_request']
        if event['kind'] == 'play_card':
            index, slot = request['deck_index'], request['expected_cycle_slot']
            if request['command_type'] != 153 or type(index) is not int or not 0 <= index < 8:
                raise ValueError('invalid official deploy binding')
            if type(slot) is not int or not 0 <= slot < 4:
                raise ValueError('invalid source hand slot')
            if participant['deck_order'][index] != event['base_data_id']:
                raise ValueError('source card differs from physical deck index')
            if request['coordinates'] != event['source_position']:
                raise ValueError('source coordinates were changed')
            for coordinate in ('x', 'y'):
                value = event['source_position'][coordinate]
                if type(value) is not int or not 0 <= value <= (18000 if coordinate == 'x' else 32000):
                    raise ValueError('source coordinate outside this arena')
        elif event['kind'] == 'activate_ability':
            if request['command_type'] != 189 or any(k in request for k in ('cgid', 'position', 'coordinates')):
                raise ValueError('ability must resolve a real native actor, not a guessed target')
        else:
            raise ValueError('unsupported source event kind')
    if type(replay['endTick']) is not int or not previous < replay['endTick'] <= 7600:
        raise ValueError('replay end must retain the full source timeline')


def render(doc, run_source=False, native_replay=None):
    validate(doc)
    replay = doc['initialization_only']
    if native_replay is not None:
        if not run_source:
            raise ValueError('loaded replay requires full source verification')
        expected = dict(native_replay)
        commands = expected.pop('cmd')
        initial = dict(replay)
        initial.pop('cmd')
        if expected != initial or len(commands) != len(doc['events']):
            raise ValueError('loaded replay initialization/source count differs')
        for event, command in zip(doc['events'], commands):
            body = command['c']
            participant = doc['participants'][event['source_side']]
            identity = participant['synthetic_native_identity']
            if command['ct'] != event['native_request']['command_type'] or body['t'] != event['source_tick_20hz'] or body['t2'] != body['t']:
                raise ValueError('loaded command timing/type differs')
            if (body['idHi'], body['idLo']) != (identity['hi'], identity['lo']):
                raise ValueError('loaded command identity differs')
            if event['kind'] == 'play_card' and (body['sel']['os'] != event['base_data_id'] or {'x':body['px'],'y':body['py']} != event['source_position']):
                raise ValueError('loaded card/position differs')
        replay = native_replay
    payload = json.dumps(replay, ensure_ascii=True, separators=(',', ':'))
    rows = [doc['initialization_only']['battle']['deck'+str(side)]['sp'] for side in (0, 1)]
    text = 'static const char bootstrap_json[]='+json.dumps(payload)+';\n'
    text += render_towers(doc,'bootstrap')
    text += 'static const unsigned bootstrap_cards[2][8][3]={'
    text += ','.join('{'+','.join('{'+','.join(str(c[k]) for k in ('d','l','el'))+'}' for c in cards)+'}' for cards in rows)+'};\n'
    identities = {p['native_owner']: p['synthetic_native_identity'] for p in doc['participants'].values()}
    text += 'static const unsigned bootstrap_identities[2][2]={'+','.join('{'+str(identities[s]['hi'])+','+str(identities[s]['lo'])+'}' for s in (0,1))+'};\n'
    text += 'static constexpr bool bootstrap_run_source='+str(run_source).lower()+';\n'
    text += 'static constexpr bool bootstrap_run_loaded='+str(native_replay is not None).lower()+';\n'
    desired = {p['native_owner']: p['cycle']['opening']+p['cycle']['queue'] for p in doc['participants'].values()}
    text += 'static const unsigned bootstrap_desired_deal[2][8]={'+','.join('{'+','.join(map(str,desired[s]))+'}' for s in (0,1))+'};\n'
    text += 'struct SourceEvent {int tick,owner,kind,id,x,y,cycle_slot,physical_index;};\nstatic const SourceEvent bootstrap_events[]={\n'
    for event in doc['events']:
        request = event['native_request']
        card = event['kind'] == 'play_card'
        position = event['source_position'] if card else None
        values = [event['source_tick_20hz'], doc['participants'][event['source_side']]['native_owner'], 153 if card else 189,
                  event['base_data_id'] if card else 0, position['x'] if card else 0, position['y'] if card else 0,
                  request['expected_cycle_slot'] if card else -1, request['deck_index'] if card else -1]
        text += '{'+','.join(map(str,values))+'},\n'
    text += '};\nstatic constexpr int bootstrap_source_end='+str(doc['initialization_only']['endTick'])+';\n'
    return text
