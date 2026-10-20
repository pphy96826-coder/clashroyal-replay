"""Prepare lossless native execution requests and an initialization-only JSON.

The initialization JSON deliberately is NOT submitted as a complete replay.
Selections and ability object IDs must be produced by the initialized official
runtime, then serialized by its own command serializers. In particular a source
web player tag is never guessed to be a native account ID, and an ability icon
is never guessed to be a game-object ID.
"""
import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
from tower_profiles import tower_request,default_binding

# Rarity-dependent internal level convention, verified in the native level
# contract. This small adapter rejects other cards, rather than guessing them.
RARITY_OFFSET = {26000021:3,26000038:3,26000014:3,27000000:1,
                 28000000:3,28000011:9,26000010:1,26000030:1}
FORM_INPUT = {'basic':0,'evolution':1,'hero':2}


def cycle_slots(opening, queue, plays):
    hand=list(opening);queue=list(queue);slots=[]
    for card in plays:
        if card not in hand:return None
        slot=hand.index(card);slots.append(slot)
        hand[slot]=queue.pop(0);queue.append(card)
    return slots


def infer_compatible_cycle(cards, plays):
    """User-requested first four DISTINCT appearances, plus full-stream check.

    This is one compatible reconstruction, not proof of the hidden original
    opening. Keep every compatible queue and explicitly report ambiguity.
    """
    if len(cards)!=8 or len(set(cards))!=8 or not plays or not set(plays)<=set(cards):
        raise ValueError('invalid deck/action stream')
    opening=list(dict.fromkeys(plays))[:4]
    if len(opening)!=4:raise ValueError('fewer than four distinct observed cards')
    remaining=[c for c in dict.fromkeys(plays+cards) if c not in opening]
    queues=[]
    for queue in itertools.permutations(remaining):
        slots=cycle_slots(opening,queue,plays)
        if slots is not None:queues.append({'queue':list(queue),'slots':slots})
    if not queues:raise ValueError('first-seen opening cannot reproduce complete stream')
    return {'opening':opening,'queue':queues[0]['queue'],'slots':queues[0]['slots'],
            'compatible_queue_count':len(queues),'all_actions_legal_in_cycle_model':True,
            'hidden_original_hand_proven':False,'native_deal_verified':False,
            'inference':'first-four-distinct-appearances/full-stream-checked'}


def prepare(source,level_offsets=None,tower_evidence=None):
    if source.get('dropped_actions')!=0 or source['source_action_count']!=len(source['actions']):
        raise ValueError('source actions missing')
    if source['unresolved_base_card_ids']:raise ValueError('unsupported cards')
    if source['coordinate_transform_applied']:raise ValueError('unexpected source transform')
    if sorted(d['proposed_native_owner'] for d in source['decks'])!=[0,1]:
        raise ValueError('invalid participant mapping')
    offsets=dict(RARITY_OFFSET)
    if level_offsets is not None:
        for data_id,value in level_offsets.items():
            if type(data_id) is not int or type(value) is not int or not 1<=value<=16:
                raise ValueError('invalid native level offset')
            if data_id in offsets and offsets[data_id]!=value:raise ValueError('native level evidence disagrees with existing binding')
            offsets[data_id]=value
    battle=dict(gmt=1,plt=1,t1s=0,t2s=0,gamemode=72000006,hm=False,lvlcap=0,
                cardlvlmin=0,stp=0,trail=170000000,te=-1,tps=1,
                location=15000061,arena=54000016,hbd=[None,None])
    sides={};events=copy.deepcopy(source['actions']);towers=[None,None]
    for deck in source['decks']:
        owner=deck['proposed_native_owner'];side=deck['source_side']
        source_player=deck.get('source_player',{})
        if not source_player.get('tag') or not source_player.get('name'):
            raise ValueError('source player identity missing')
        by_id={c['base_data_id']:c for c in deck['cards']}
        plays=[e['base_data_id'] for e in events if e['source_side']==side and e['kind']=='play_card']
        cycle=infer_compatible_cycle(list(by_id),plays)
        ordered=cycle['opening']+cycle['queue']
        entries=[]
        for cid in ordered:
            if cid not in offsets:raise ValueError('native level evidence required for card '+str(cid))
            c=by_id[cid];offset=offsets[cid];level=c['source_level']-offset
            if not 0<=level<=15:raise ValueError('unsupported internal card level')
            entries.append({'d':cid,'l':level,'el':FORM_INPUT[c['form']]})
        tower=deck['tower']
        if not tower or type(tower.get('level')) is not int or not 1<=tower['level']<=16:
            raise ValueError('需要明确且受当前客户端支持的塔楼等级（1至16级）')
        king_level=deck.get('king_level',tower['level'])
        if type(king_level) is not int or not 1<=king_level<=16:
            raise ValueError('国王塔等级必须在当前客户端支持的1至16级范围内')
        if tower_evidence is None:
            if tower['card_key']!='tower-princess':raise ValueError('需要当前客户端的塔楼目录校验')
            towers[owner]=default_binding(tower['level'])
        else:towers[owner]=tower_request(tower,tower_evidence)
        towers[owner].update(king_level=king_level,
            king_level_policy='explicit-source' if 'king_level' in deck else 'user-default-match-tower-level',
            explicit_support=tower['card_key']!='tower-princess' or king_level!=tower['level'])
        # Distinct local-only identities, not the logged-in user's identity and
        # not claimed to be the source player's real server-side identifier.
        identity={'hi':0x11223344,'lo':0x55660001+owner}
        # These are LITERAL dotted keys in the official parser, not a nested
        # accountID object. Nesting silently defaults BOTH participants to0.
        battle['avatar'+str(owner)]={'accountID.hi':identity['hi'],'accountID.lo':identity['lo'],'expLevel':1,
            'name':source_player['name'],'arena':54000016,'welo':-1,'scr':0,'lti':0,'npc':False}
        # Princess uses the verified native default SupportCard169000000.
        # Other types use their explicit official sc169 record and rarity
        # level. Never copy the web/API159 wrapper into the official parser.
        battle['deck'+str(owner)]={'hdr':'BD01','sp':entries}
        if towers[owner]['explicit_support']:
            bound=towers[owner]
            battle['deck'+str(owner)]['sc']=[{'d':bound['support_id'],'l':bound['internal_level']}]
        battle['hbd'][owner]={'em':{'oe':[],'de':[],'fav':[]},
            'sk':{'os':[],'ss':[],'rnd':False},'bn':{'bg':0,'fg':0},'kt':king_level}
        sides[side]={'native_owner':owner,'source_player':source_player,
                     'synthetic_native_identity':identity,'deck_order':ordered,'cycle':cycle}
        play_index=0
        for event in events:
            if event['source_side']!=side:continue
            if event['kind']=='play_card':
                event['native_request']={'command_type':153,'deck_index':ordered.index(event['base_data_id']),
                    'expected_cycle_slot':cycle['slots'][play_index],
                    'selection':'produce-from-actual-native-hand-card','coordinates':event['source_position']}
                play_index+=1
            elif event['kind']=='activate_ability':
                event['native_request']={'command_type':189,
                    'object_id':'resolve-native-owned-hero-at-source-tick',
                    'ability_source_marker':event['source_fields']['data_ability']}
            else:raise ValueError('unsupported event')
    duration=source['source_duration_seconds']
    if type(duration) not in (int,float) or not 0<duration<=360:raise ValueError('invalid source duration')
    limit=max(int(duration*20),max(e['source_tick_20hz'] for e in events))+400
    return {'schema':'official-web-replay.preparation.v1','replay_tag':source['replay_tag'],
        'source_sha256':source['source_sha256'],'source_orientation':source['source_orientation'],
        'tower_bindings':towers,
        'source_to_native_orientation_verified':False,'participants':sides,'events':events,
        'initialization_only':{'battle':battle,'rndSeed':1784463263,'time':-1,'endTick':limit,
                               'cmd':[],'evt':[],'srq':[],'srs':[]},
        'preserved_event_count':len(events),'source_action_count':source['source_action_count'],
        'default_tower_binding':{'source':'tower-princess','scope':'native fallback catalog precondition, not both source towers','native_default_support_id':169000000,
            'native_tower_definition_ids':[35000000,35000001],'requires_runtime_binding':True},
        'pending_native_checks':['JSON initialization/default tower binding','native deal/order','el form availability',
            'ability target','timing/orientation','native scene playback','safe exit'],
        'complete_native_replay':False,'executable':False,
        'initialization_json_is_complete_replay':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--level-evidence',type=Path)
    p.add_argument('--tower-evidence',type=Path)
    a=p.parse_args();source=json.loads(a.source.read_text());offsets=None
    if a.level_evidence:
        evidence=json.loads(a.level_evidence.read_text())
        if evidence['source_sha256']!=source['source_sha256'] or evidence['identity']['library_sha256']!='c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55':
            raise ValueError('level evidence from different source/build')
        offsets={c['data_id']:c['display_offset'] for c in evidence['cards']}
    towers=None
    if a.tower_evidence:
        evidence=json.loads(a.tower_evidence.read_text())
        if evidence['identity']['library_sha256']!='c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55':
            raise ValueError('tower evidence from different native build')
        if a.level_evidence and evidence['identity']!=json.loads(a.level_evidence.read_text())['identity']:
            raise ValueError('tower and card evidence from different client generations')
        towers=evidence['towers']
    doc=prepare(source,offsets,towers)
    if a.tower_evidence:doc['native_tower_evidence_sha256']=hashlib.sha256(a.tower_evidence.read_bytes()).hexdigest()
    if a.level_evidence:doc['native_level_evidence_sha256']=hashlib.sha256(a.level_evidence.read_bytes()).hexdigest()
    doc['source_manifest_sha256']=hashlib.sha256(a.source.read_bytes()).hexdigest()
    with a.output.open('x') as f:json.dump(doc,f,ensure_ascii=False,indent=2)
    print(json.dumps({'events':len(doc['events']),'source_actions':doc['source_action_count'],
          'queues':{k:v['cycle']['compatible_queue_count'] for k,v in doc['participants'].items()},
          'complete_native_replay':False},ensure_ascii=False))

if __name__=='__main__':main()
