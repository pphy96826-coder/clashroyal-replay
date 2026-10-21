"""Asymmetric six-tower regression; neither totals nor screen-left are slots."""
import ast,copy,importlib.util,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SHARED=ROOT.parent/'windows-adaptation/project/official-web-replay'
spec=importlib.util.spec_from_file_location('real_tower_profiles',SHARED/'tower_profiles.py');towers=importlib.util.module_from_spec(spec);spec.loader.exec_module(towers)
def function(path,name):
 tree=ast.parse(path.read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name];scope={}
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope);return scope[name]
compare=function(ROOT/'device/device_playback.py','page_comparison')
matches=function(SHARED/'ability_search.py','terminal_hp_matches')
class OracleOrientationTests(unittest.TestCase):
 def setUp(self):
  self.prep={};self.source={'decks':[{'proposed_native_owner':0,'oracle_final_hp':{'king':4824,'princess0':729,'princess1':0}}, {'proposed_native_owner':1,'oracle_final_hp':{'king':4824,'princess0':2446,'princess1':993}}]}
  self.report={'battle_state':{'towers':[{'owner':o,'data_id':d,'x':x,'hp':hp} for o,d,x,hp in [(0,35000000,9000,4824),(0,35000001,14500,729),(1,35000000,9000,4824),(1,35000001,3500,2446),(1,35000001,14500,993)]],
    'destroyed_towers':[{'owner':0,'data_id':35000001,'x':3500,'hp':0,'native_destructor_observed':True,'health_at_destruction':0}]}}
 def result(self):
  with patch.dict(sys.modules,{'tower_profiles':towers}):return compare(self.source,self.prep,self.report),matches(self.source,self.prep,self.report)
 def test_actual_six_tower_sample_is_exact_not_1458(self):self.assertEqual(self.result(),(('exact',0),True))
 def test_both_source_orientations_follow_native_owner_not_deck_order(self):
  for orientation in (0,1):
   self.source['source_orientation']=orientation
   for deck in self.source['decks']:deck['source_side']='team' if deck['proposed_native_owner']==1-orientation else 'opponent'
   self.source['decks'].reverse();self.assertEqual(self.result(),(('exact',0),True))
 def test_single_survivor_does_not_certify_destroyed_side(self):
  self.source['decks'][0]['oracle_final_hp'].update(princess0=0,princess1=729)
  self.assertEqual(self.result(),(('exact',0),True))
 def test_both_alive_order_is_preserved_and_not_sorted_to_match(self):
  self.source['decks'][1]['oracle_final_hp'].update(princess0=993,princess1=2446)
  self.assertEqual(self.result(),(('same_towers',2906),False))
 def test_both_alive_upper_player_uses_own_left_right(self):
  self.report['battle_state']['destroyed_towers']=[]
  self.report['battle_state']['towers'].append({'owner':0,'data_id':35000001,'x':3500,'hp':200})
  self.source['decks'][0]['oracle_final_hp']['princess1']=200
  self.assertEqual(self.result(),(('exact',0),True))
  self.source['decks'][0]['oracle_final_hp'].update(princess0=200,princess1=729)
  self.assertEqual(self.result(),(('same_towers',1058),False))
 def test_equal_side_totals_do_not_hide_per_tower_difference(self):
  self.source['decks'][1]['oracle_final_hp'].update(princess0=2436,princess1=1003)
  self.assertEqual(self.result(),(('same_towers',20),False))
 def test_opposite_side_differences_never_cancel(self):
  self.source['decks'][0]['oracle_final_hp']['princess0']+=10
  self.source['decks'][1]['oracle_final_hp']['princess0']-=10
  self.assertEqual(self.result(),(('same_towers',20),False))
 def test_missing_tower_is_unknown_without_destruction_evidence(self):
  self.report['battle_state']['destroyed_towers']=[]
  self.assertEqual(self.result(),(('different',None),False))
 def test_comparison_does_not_modify_native_spawn_bindings(self):
  prep={'tower_bindings':[towers.default_binding(),towers.default_binding()]};before=copy.deepcopy(prep)
  towers.oracle_tower_pairs(self.source['decks'][0],prep,self.report['battle_state']);self.assertEqual(prep,before)
 def test_other_verified_sample_also_matches_without_fixed_mirroring(self):
  for deck in self.source['decks']:
   deck['oracle_final_hp'].update(king=7025,princess0=4155,princess1=0 if deck['proposed_native_owner']==0 else 1127)
  self.report['battle_state']={'towers':[{'owner':o,'data_id':d,'x':x,'hp':hp} for o,d,x,hp in [(0,35000000,9000,7025),(0,35000001,3500,4155),(1,35000000,9000,7025),(1,35000001,3500,4155),(1,35000001,14500,1127)]],
    'destroyed_towers':[{'owner':0,'data_id':35000001,'x':14500,'hp':0,'native_destructor_observed':True}]}
  self.assertEqual(self.result(),(('exact',0),True))
if __name__=='__main__':unittest.main()
