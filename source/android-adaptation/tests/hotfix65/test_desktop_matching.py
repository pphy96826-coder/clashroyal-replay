"""Exercise the Windows adapter itself, with immutable native callbacks replaced."""
from pathlib import Path
import copy,json,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT.parent/'windows-adaptation/project/official-web-replay'))
import replay_matching as matching

class DesktopMatchingTests(unittest.TestCase):
    def run_case(self,hunter=False,bad=False):
        source=dict(replay_tag='fixture',source_duration_seconds=40,actions=[],decks=[])
        for o,side in enumerate(('team','opponent')):
            source['decks'].append(dict(source_side=side,proposed_native_owner=o,
                oracle_final_hp=dict(king=4824,princess0=3000,princess1=2900),oracle_elixir_leaked=(1.5,.95)[o],
                cards=[dict(base_card_key='hunter' if hunter else 'archers',base_data_id=26000044 if hunter else 26000001,form='basic')]))
        source['actions']=[dict(kind='play_card',source_tick_20hz=20,source_side='team',base_data_id=26000044 if hunter else 26000001)]
        prep=dict(initialization_only=dict(rndSeed=42),events=[dict(kind='activate_ability')])
        calls=[]
        def execute(path,name):
            candidate=json.loads(path.read_text());seed=candidate['initialization_only']['rndSeed'];choices=candidate.get('ability_target_choices',{})
            calls.append((seed,copy.deepcopy(choices),name))
            if hunter and not choices:return dict(error=112,native_code=2,event_index=0,elixir=[dict(leaked=0,spent=0)]*2),path
            wrong=bad or (hunter and (seed==42 or choices.get('0')==0))
            totals=[dict(current=10000,spent=10000,gained=10000,leaked=25000 if wrong and o==0 else (15028,9579)[o]) for o in (0,1)]
            towers=[dict(owner=o,data_id=35000000 if k==0 else 35000001,x=(9000,3500,14500)[k],hp=hp)
                    for o in (0,1) for k,hp in enumerate((4824,3000,2900))]
            return dict(error=0,finished=1,tick=800,executed=1,native_accepted=1,
                commands=[dict(ct=189,c=dict(t=20,t2=20))],dispatch=[dict(index=0,kind=189,tick=20,flags=3,code=0)],
                elixir=totals,elixir_at_page_end=dict(tick=800,sides=totals),battle_state=dict(towers=towers)),path
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);path=folder/'source.json';path.write_text(json.dumps(source))
            with patch.object(matching,'calibrate',lambda doc,receipt,seen:dict(doc,native_deal_ready=True)),patch.object(matching,'deck_fingerprint',lambda doc:()):
                try:result=matching.match(path,prep,copy.deepcopy(prep),folder,execute,lambda path,name:{})
                except RuntimeError as error:
                    return str(error),calls,json.loads((folder/'page-comparison.json').read_text()) if (folder/'page-comparison.json').exists() else None
            return result,calls,json.loads((folder/'page-comparison.json').read_text())

    def test_exact_native_run_produces_full_comparison(self):
        result,calls,comparison=self.run_case()
        self.assertEqual(len(calls),1);self.assertEqual(comparison['tier'],'exact')
        self.assertEqual(comparison['hp_difference'],0);self.assertTrue(comparison['elixir_matched'])
        self.assertEqual(comparison['time_difference_seconds'],0)

    def test_mismatch_is_refused_and_native_evidence_is_retained(self):
        result,calls,comparison=self.run_case(bad=True)
        self.assertIn('溢出圣水与网页不一致',result);self.assertEqual(len(calls),1)
        self.assertIn('网页 1.50，模拟 2.50',result)

    def test_each_seed_branches_after_an_original_elixir_rejection(self):
        result,calls,comparison=self.run_case(hunter=True)
        self.assertIsInstance(result,tuple)
        first_new=next(seed for seed,_,_ in calls if seed!=42)
        choices=[choice for seed,choice,_ in calls if seed==first_new]
        self.assertIn({'0':0},choices);self.assertIn({'0':1},choices)
        self.assertEqual(comparison['tier'],'exact');self.assertTrue(comparison['elixir_matched'])

if __name__=='__main__':unittest.main()
