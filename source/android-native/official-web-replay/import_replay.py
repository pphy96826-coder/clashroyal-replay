"""Lossless RoyaleAPI HTML import for the official-client replay adapter.

This is source preparation, not a declaration that client playback succeeded.
Never replace Evo/Hero cards by base cards or synthesize ability targets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from html.parser import HTMLParser
from urllib.parse import unquote

BASE_IDS={'hog-rider':26000021,'ice-golem':26000038,'musketeer':26000014,
          'cannon':27000000,'fireball':28000000,'the-log':28000011,
          'skeletons':26000010,'ice-spirit':26000030,
          # IDs independently present in the user-saved official page's
          # open-deck links; native catalog/level binding remains mandatory.
          'princess':26000026,'mighty-miner':26000065,'tesla':27000006,
          'goblin-barrel':28000004,'rocket':28000003}

def elixir_leaked_from_html(html):
    """Each player's elixir leaked from the battle header (the battle log's
    elixirLeaked), in the same order as the hp-popup tower health the parser maps
    to team, opponent. None unless both players have exactly one value."""
    values=[];start=0
    for popup in re.finditer(r'class="hp-popup"',html):
        found=re.findall(r'Elixir Leaked\s*</span>\s*(\d+(?:\.\d+)?)\s*<',html[start:popup.start()])
        values.append(float(found[0]) if len(found)==1 else None);start=popup.end()
    return dict(team=values[0],opponent=values[1]) if len(values)==2 and None not in values else None


def attach_elixir_leaked(document, html):
    """Record the page's elixir leaked per source deck (None when absent)."""
    leaked=elixir_leaked_from_html(html) or {}
    for deck in document['decks']:deck['oracle_elixir_leaked']=leaked.get(deck['source_side'])
    return document


def card_ids_from_html(html, resolver=None):
    """Resolve names against each source deck's copyDeck ID SET, never order.

    These IDs come from the saved page, not Null or a guessed slug dictionary.
    Portraits are sorted by equipped form; copyDeck is NOT in that order.
    Require both eight-card profiles, duplicate-link agreement, known/catalog
    name anchors, and at most one unambiguous remaining name/ID pair per deck.
    Runtime catalog verification is still
    mandatory before any native use of newly discovered IDs.
    """
    starts = list(re.finditer(r'<div\b(?=[^>]*\bid="deck_[^"]+")(?=[^>]*\bclass="[^"]*\bpadded\b[^"]*\bgrid\b)[^>]*>', html))
    if not starts: return {}
    if len(starts) != 2: raise ValueError('expected exactly two source deck grids')
    class Deck(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True); self.keys = []; self.links = []; self.names = {}
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == 'img' and values.get('data-card-key'):
                key = re.sub(r'-(?:ev\d+|hero)$', '', values['data-card-key'].strip().lower())
                if key not in self.keys: self.keys.append(key)
                self.names[key] = values.get('alt')
            for value in (values.get('href'), values.get('data-qrcode')):
                if not value or 'copyDeck?' not in value: continue
                match = re.search(r'(?:\?|&)deck=([0-9;]+)(?:&|$)', unquote(value))
                if match: self.links.append([int(v) for v in match.group(1).split(';')])
    result = {}
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        deck = Deck(); deck.feed(html[start.end():end]); deck.close()
        if len(deck.keys) != 8 or not deck.links:
            raise ValueError('deck portraits/copyDeck identity evidence incomplete')
        ids = deck.links[0]
        if len(ids) != 8 or len(set(ids)) != 8 or any(link != ids for link in deck.links):
            raise ValueError('ambiguous copyDeck ID sequence')
        if any(cid // 1000000 not in (26, 27, 28) for cid in ids): raise ValueError('invalid source card category')
        resolved = {}; unknown = []
        for key in deck.keys:
            data_id = BASE_IDS.get(key) or result.get(key)
            if data_id is None and resolver is not None: data_id = resolver(key, deck.names.get(key))
            if data_id is None: unknown.append(key); continue
            if data_id not in ids: raise ValueError('copyDeck disagrees with named card '+key)
            if data_id in resolved.values(): raise ValueError('two source names alias one card')
            resolved[key] = data_id
        remaining = set(ids) - set(resolved.values())
        if len(unknown) == len(remaining) == 1:
            resolved[unknown[0]] = remaining.pop()
        for key, data_id in resolved.items():
            if key in result and result[key] != data_id: raise ValueError('source decks disagree on card '+key)
            result[key] = data_id
    return result


def convert(payload, *, source_path, source_bytes, parser_digest, card_ids=None):
    ids = dict(BASE_IDS)
    for key, value in (card_ids or {}).items():
        if key in ids and ids[key] != value: raise ValueError('source card ID conflicts with known anchor')
        ids[key] = value
    orientation=payload['source']['source_data_i']
    if type(orientation) is not int or orientation not in (0,1):raise ValueError('mixed/unknown source orientation')
    # Explicit hypothesis for native absolute-coordinate playback. Retain the
    # source identity independently; a live native check still has to certify it.
    owner_map={'team':1-orientation,'opponent':orientation}
    decks=[];requirements=set();unknown_ids=set()
    for side in ('team','opponent'):
        player=payload['battle'][side]['players'][0];deck=player['deck']
        if len(deck)!=8:raise ValueError('source does not contain an eight-card deck')
        cards=[];bases=[]
        for c in deck:
            key=c['card_key'];base=re.sub(r'-(?:ev\d+|hero)$','',key)
            level=c.get('level')
            if type(level) is not int or not 1<=level<=16:raise ValueError('source card level missing or unsupported: '+key)
            form='hero' if key.endswith('-hero') else 'evolution' if re.search(r'-ev\d+$',key) else 'basic'
            if form!='basic':requirements.add(form)
            if base not in ids:unknown_ids.add(base)
            cards.append(dict(source_card_key=key,base_card_key=base,base_data_id=ids.get(base),source_level=level,form=form))
            bases.append(base)
        if len(set(bases))!=8:raise ValueError('duplicate base card in source deck')
        decks.append(dict(source_side=side,source_player={'name':player.get('name'),'tag':player.get('tag')},
                          proposed_native_owner=owner_map[side],cards=cards,
                          tower=player.get('tower_card'),oracle_final_hp=payload['battle'][side].get('tower_health')))
    events=payload['events'];actions=[];last=-1
    for e in events:
        tick=e['replay_tick_20hz'];fields=e['source_fields'];side=e['side']
        if type(tick) is not int or tick<0 or tick<last:raise ValueError('invalid or reordered source clock')
        if tick!=fields['data_t'] or fields['data_i']!=orientation:raise ValueError('source clock/orientation changed')
        if side not in owner_map:raise ValueError('unknown source owner')
        action=dict(kind=e['kind'],source_tick_20hz=tick,source_side=side,
                    proposed_native_owner=owner_map[side],source_fields=fields)
        if e['kind']=='play_card':
            p=e['position'];x,y=p['x'],p['y']
            if type(x) is not int or type(y) is not int or not 0<=x<18000 or not 0<=y<32000:raise ValueError('invalid source position')
            if (x,y)!=(fields['data_x'],fields['data_y']):raise ValueError('source coordinate changed')
            key=e['card_key']
            if key not in [c['base_card_key'] for d in decks if d['source_side']==side for c in d['cards']]:raise ValueError('action card outside source deck')
            action.update(base_card_key=key,base_data_id=ids.get(key),source_position={'x':x,'y':y})
        elif e['kind']=='activate_ability':
            if 'position' in e:raise ValueError('ability target needs separate verified semantics')
            requirements.add('ability')
        else:raise ValueError('unknown action kind')
        actions.append(action);last=tick
    if not actions or payload['source'].get('dropped_pre_policy_event_count')!=0:raise ValueError('incomplete source timeline')
    return dict(schema='official-web-replay.source.v1',source_html=str(source_path),
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),parser_sha256=parser_digest,
        replay_tag=payload['source']['replay_tag'],source_orientation=orientation,
        game_mode=payload['battle'].get('game_mode'),decks=decks,actions=actions,
        requirements=sorted(requirements),unresolved_base_card_ids=sorted(unknown_ids),
        source_duration_seconds=payload['replay']['duration']['timeline_seconds'],
        source_result=payload['replay']['outcome'],source_action_count=len(events),
        retained_action_count=len(actions),dropped_actions=0,coordinate_transform_applied=False,
        source_to_native_orientation_verified=False,initial_hand_known=False,
        executable=False,client_native_scene_playback_verified=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('html',type=Path);parser.add_argument('--project-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();sys.path.insert(0,str(args.project_root.resolve()))
    from native_runner.tools.royaleapi_hog_il import parse_royaleapi_replay_html
    from native_runner.royaleapi_replay import resolve_native_card, RoyaleAPIReplayError
    def resolve(key, name):
        try: return resolve_native_card(key, name).card_id
        except RoyaleAPIReplayError: return None
    raw=args.html.read_bytes();payload=parse_royaleapi_replay_html(raw.decode('utf-8'),preserve_all_events=True)
    source=args.project_root/'native_runner/tools/royaleapi_hog_il.py'
    doc=convert(payload,source_path=args.html.resolve(),source_bytes=raw,parser_digest=hashlib.sha256(source.read_bytes()).hexdigest(),
                card_ids=card_ids_from_html(raw.decode('utf-8'), resolve))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(doc,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:doc[k] for k in ('replay_tag','retained_action_count','dropped_actions','requirements','unresolved_base_card_ids','executable','client_native_scene_playback_verified')},ensure_ascii=False))

if __name__=='__main__':main()
