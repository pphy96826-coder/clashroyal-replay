"""85-event/16-ability regression: legal actors and RNG are separate searches."""
from pathlib import Path
import importlib.util,sys,unittest
from unittest.mock import Mock
SHARED=Path(__file__).resolve().parents[2]/'windows-adaptation/project/official-web-replay'
sys.path.insert(0,str(SHARED))
spec=importlib.util.spec_from_file_location('extreme_ability_search',SHARED/'ability_search.py');ability=importlib.util.module_from_spec(spec);spec.loader.exec_module(ability)
ABILITIES=(7,15,18,22,24,28,35,37,44,45,56,59,62,68,72,76)

def report(n=85):
 commands=[{'ct':189 if i in ABILITIES else 153,'c':{'t':i*20,'t2':i*20}} for i in range(n)]
 return dict(error=0,finished=1,executed=n,native_accepted=n,commands=commands,
   dispatch=[dict(index=i,kind=c['ct'],tick=c['c']['t'],flags=3,code=0) for i,c in enumerate(commands)])
def ambiguity(index,count):return dict(error=112,event_index=index,tick=index*20,native_code=count,executed=index,native_accepted=index,commands=[],dispatch=[])
class ExtremeAbilityTests(unittest.TestCase):
 def setUp(self):self.prep={'events':[dict(kind='activate_ability' if i in ABILITIES else 'play_card') for i in range(85)]}
 def test_captured_nested_ambiguities_reach_full_run_before_seed_search(self):
  seen=[]
  def execute(candidate,number):
   choices=candidate['ability_target_choices'];seen.append(dict(choices))
   if '18' not in choices:value=ambiguity(18,2)
   elif '24' not in choices:value=ambiguity(24,2)
   elif choices['24']==0:value=ambiguity(28,0)
   elif '35' not in choices:value=ambiguity(35,2)
   elif '44' not in choices:value=ambiguity(44,2)
   else:value=report()
   return value,{'attempt':number}
  matched=Mock(return_value=False)
  selected,value,detail=ability.search(self.prep,execute,matched,allow_nonmatching_complete=True)
  self.assertEqual(len(seen),6);self.assertEqual(value['native_accepted'],85)
  self.assertEqual(sum(c['ct']==189 for c in value['commands']),16)
  self.assertEqual(selected['ability_target_choices'],{'18':0,'24':1,'35':0,'44':0})
  self.assertFalse(detail['final_hp_matched']);self.assertTrue(detail['inferred']);self.assertTrue(detail['complete_branch_before_seed_search'])
  self.assertFalse(detail['unique_solution_proven']);self.assertNotIn('ability_target_choices',self.prep)
 def test_strict_default_still_explores_alternative_actor_for_exact_hp(self):
  def execute(candidate,number):return (ambiguity(18,2) if not candidate['ability_target_choices'] else report()),{}
  selected,_,detail=ability.search(self.prep,execute,lambda c,r:c['ability_target_choices'].get('18')==1)
  self.assertEqual(selected['ability_target_choices'],{'18':1});self.assertTrue(detail['final_hp_matched'])
 def test_rng_policy_does_not_accept_dropped_skill_or_partial_stream(self):
  for invalid in (report(84),dict(report(),native_accepted=84),dict(report(),finished=0),dict(report(),error=114)):
   with self.subTest(invalid=invalid.get('error')),self.assertRaises(RuntimeError):
    ability.search(self.prep,lambda *_:(invalid,{}),lambda *_:True,allow_nonmatching_complete=True)
 def test_rng_policy_still_rejects_retimed_or_rejected_dispatch(self):
  value=report();value['dispatch'][24]['code']=1
  with self.assertRaises(RuntimeError):ability.search(self.prep,lambda *_:(value,{}),lambda *_:True,allow_nonmatching_complete=True)
 def test_cancelled_search_does_not_execute_more_native_candidates(self):
  execute=Mock()
  with self.assertRaisesRegex(RuntimeError,'取消'):ability.search(self.prep,execute,lambda *_:True,cancelled=lambda:True,allow_nonmatching_complete=True)
  execute.assert_not_called()
 def test_bound_does_not_convert_incomplete_branches_to_playable(self):
  with self.assertRaises(RuntimeError) as error:
   ability.search(self.prep,lambda *_:(ambiguity(18,2),{}),lambda *_:True,max_attempts=1,allow_nonmatching_complete=True)
  self.assertEqual(error.exception.search_report['remaining'],2)
 def test_skill_first_selects_lower_six_tower_difference_after_first_full(self):
  calls=[]
  def execute(candidate,number):
   choices=candidate['ability_target_choices'];calls.append(dict(choices))
   return (report() if choices else ambiguity(18,3)),{'attempt':number}
  selected,_,detail=ability.search(self.prep,execute,lambda *_:False,
   score=lambda c,r:{0:1492,1:90,2:700}[c['ability_target_choices']['18']])
  self.assertEqual(selected['ability_target_choices'],{'18':1})
  self.assertEqual(detail['selected_hp_difference'],90);self.assertEqual(detail['selected_evidence'],{'attempt':2})
  self.assertEqual(len(calls),4);self.assertTrue(detail['explored_branches_exhausted'])
 def test_skill_bound_retains_only_completed_best(self):
  def execute(c,n):return (report() if c['ability_target_choices'] else ambiguity(18,3)),{'attempt':n}
  selected,_,detail=ability.search(self.prep,execute,lambda *_:False,score=lambda *_:100,max_attempts=2)
  self.assertEqual(selected['ability_target_choices'],{'18':0});self.assertTrue(detail['budget_exhausted'])
 def test_zero_difference_stops_skill_search(self):
  execute=Mock(side_effect=[(ambiguity(18,3),{}),(report(),{})])
  _,_,detail=ability.search(self.prep,execute,lambda *_:True,score=lambda *_:0)
  self.assertEqual(execute.call_count,2);self.assertTrue(detail['final_hp_matched'])
 def test_partial_complete_never_competes_on_hp(self):
  invalid=dict(report(),finished=0);score=Mock(return_value=0)
  with self.assertRaises(RuntimeError):ability.search(self.prep,lambda *_:(invalid,{}),lambda *_:True,score=score)
  score.assert_not_called()
 def test_user_stop_preserves_first_full_at_boundary(self):
  ready=[]
  def execute(c,n):return (report() if c['ability_target_choices'] else ambiguity(18,3)),{}
  _,_,detail=ability.search(self.prep,execute,lambda *_:False,score=lambda *_:1492,
   on_best=lambda *args:ready.append(True),stop_requested=lambda:bool(ready))
  self.assertTrue(detail['stopped_by_user']);self.assertEqual(len(detail['attempts']),2)
 def test_seed_trial_keeps_selected_skill_ordinals_and_rejects_new_ambiguity(self):
  choices={'18':1,'24':0};seen=[]
  def execute(c,n):seen.append(c['ability_target_choices']);return report(),{}
  candidate,_,detail=ability.fixed_choice_trial(self.prep,choices,execute,lambda *_:False)
  self.assertEqual(seen,[choices]);self.assertTrue(detail['fixed_skill_choices'])
  candidate['ability_target_choices']['18']=0;self.assertEqual(choices['18'],1)
  with self.assertRaises(RuntimeError):ability.fixed_choice_trial(self.prep,choices,lambda *_:(ambiguity(35,2),{}),lambda *_:True)
if __name__=='__main__':unittest.main()
