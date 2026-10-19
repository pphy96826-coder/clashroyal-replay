"""Synthetic replay checks, not a fabricated real-game result."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];CORE=ROOT/'project/official-web-replay'
sys.path[:0]=[str(CORE),str(ROOT/'project/vendor')]


def fixture():
    from import_replay import convert
    from prepare_native_replay import prepare
    from timing_policy import apply_offset
    keys=('hog-rider','ice-golem','musketeer','cannon','fireball','the-log','skeletons','ice-spirit')
    deck=[dict(card_key=key,level=16) for key in keys]
    battle={side:dict(players=[dict(name='Synthetic '+side,tag='TEST0001' if side=='team' else 'TEST0002',
        deck=copy.deepcopy(deck),tower_card=dict(card_key='tower-princess',level=16))]) for side in ('team','opponent')}
    events=[]
    for i in range(4):
        for side in ('team','opponent'):
            tick=100+30*len(events);x,y=(3500,14500) if side=='team' else (14500,17500)
            events.append(dict(kind='play_card',side=side,replay_tick_20hz=tick,card_key=keys[i],position=dict(x=x,y=y),
                source_fields=dict(data_t=tick,data_i=1,data_x=x,data_y=y,data_s='blue' if side=='team' else 'red')))
    payload=dict(source=dict(source_data_i=1,replay_tag='SYNTHETIC',dropped_pre_policy_event_count=0),battle=battle,
        events=events,replay=dict(duration=dict(timeline_seconds=300),outcome='unknown'))
    source=convert(payload,source_path=Path('synthetic.html'),source_bytes=b'synthetic',parser_digest='synthetic')
    prep=prepare(source)
    return source,prep,apply_offset(prep,20)


class SourceTests(unittest.TestCase):
    def test_all_actions_preserved_and_delayed_once(self):
        from timing_policy import apply_offset
        source,prep,shifted=fixture()
        self.assertEqual(source['retained_action_count'],8);self.assertEqual(source['dropped_actions'],0)
        for old,new in zip(prep['events'],shifted['events']):
            self.assertEqual(new['source_tick_20hz'],old['source_tick_20hz']+20)
            self.assertEqual(new['source_fields'],old['source_fields'])
            self.assertEqual(new['source_position'],old['source_position'])
        with self.assertRaises(ValueError):apply_offset(shifted,20)

    def test_bootstrap_and_full_scene_headers_generated(self):
        from bootstrap_input import render
        from scene_input import render_scene
        _,_,shifted=fixture();self.assertIn('static const char bootstrap_json[]=',render(shifted,True))
        native=copy.deepcopy(shifted['initialization_only']);native['cmd']=[]
        for event in shifted['events']:
            identity=shifted['participants'][event['source_side']]['synthetic_native_identity'];tick=event['source_tick_20hz']
            native['cmd'].append(dict(ct=153,c=dict(t=tick,t2=tick,idHi=identity['hi'],idLo=identity['lo'],
                sel=dict(os=event['base_data_id']),px=event['source_position']['x'],py=event['source_position']['y'])))
        self.assertTrue(render_scene(shifted,native))

    def test_native_engine_adaptation_sources_unchanged(self):
        expected=json.loads((ROOT/'upstream-manifest.json').read_text(encoding='utf-8'))
        for relative,digest in expected.items():
            if relative.endswith(('.cpp','.h')):
                self.assertEqual(hashlib.sha256((ROOT/'project'/relative).read_bytes()).hexdigest(),digest,relative)

    def test_invalid_html_rejected(self):
        from native_runner.tools.royaleapi_hog_il import parse_royaleapi_replay_html
        with self.assertRaises(ValueError):parse_royaleapi_replay_html('<html>Not a replay</html>',preserve_all_events=True)


if __name__=='__main__':unittest.main()
