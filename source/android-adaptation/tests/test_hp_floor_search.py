"""Floor pruning must not publish partials or mistake a bound for exhaustion."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extreme_ability_search import ability,report,ambiguity,ABILITIES

class FloorSearchTests(unittest.TestCase):
 def setUp(self):self.prep={'events':[dict(kind='activate_ability' if i in ABILITIES else 'play_card') for i in range(85)],'prune_below_oracle':True}
 def pruned(self,gap):return dict(error=123,event_index=35,native_accepted=35,executed=35,finished=0,commands=[],dispatch=[],gap=gap,hp_floor_violation={'native_tick':2801,'owner':1,'tower_slot':1,'expected_min':2417,'actual_hp':2400})
 def test_other_branch_is_tried_before_fallback_and_partial_never_wins(self):
  seen=[]
  def execute(c,n):
   seen.append((n,c['prune_below_oracle'],dict(c['ability_target_choices'])))
   v=ambiguity(18,2) if not c['ability_target_choices'] else self.pruned(1) if c['ability_target_choices']['18']==0 else dict(report(),gap=90)
   return v,{'attempt':n}
  c,r,d=ability.search_with_hp_floor(self.prep,execute,lambda *_:False,score=lambda c,r:r['gap'])
  self.assertEqual(c['ability_target_choices'],{'18':1});self.assertEqual(r['native_accepted'],85)
  self.assertFalse(d['floor_fallback_used']);self.assertEqual(len(seen),3);self.assertTrue(all(v[1] for v in seen))
 def test_all_first_pass_rejections_then_closest_prefix_fresh_rerun(self):
  seen=[]
  def execute(c,n):
   choices=c['ability_target_choices'];seen.append((n,c['prune_below_oracle'],dict(choices)))
   v=ambiguity(18,2) if not choices else self.pruned(20 if choices['18']==0 else 5) if c['prune_below_oracle'] else dict(report(),gap=300)
   return v,{'attempt':n}
  c,r,d=ability.search_with_hp_floor(self.prep,execute,lambda *_:False,score=lambda c,r:r['gap'])
  self.assertEqual(seen,[(0,True,{}),(1,True,{'18':0}),(2,True,{'18':1}),(3,False,{'18':1})])
  self.assertTrue(d['continued_by_fresh_simulation']);self.assertTrue(d['floor_fallback_used']);self.assertEqual(d['floor_selected_prefix']['difference'],5)
  self.assertEqual(c['ability_target_choices'],{'18':1});self.assertEqual(len(d['attempts']),4)
 def test_limit_with_pruned_branch_never_starts_fallback(self):
  calls=[]
  def execute(c,n):
   calls.append(c['prune_below_oracle']);return (ambiguity(18,2) if not c['ability_target_choices'] else self.pruned(0)),{}
  with self.assertRaises(RuntimeError) as error:ability.search_with_hp_floor(self.prep,execute,lambda *_:False,max_attempts=2,score=lambda c,r:r['gap'])
  self.assertEqual(calls,[True,True]);self.assertFalse(error.exception.search_report['explored_branches_exhausted'])
 def test_no_complete_prefix_may_compete_as_playable(self):
  with self.assertRaises(RuntimeError):ability.search_with_hp_floor(self.prep,lambda c,n:(self.pruned(0),{}),lambda *_:True,score=lambda c,r:r['gap'],fallback_attempts=1)
 def test_failed_closest_prefix_falls_through_to_next_and_numbers_unique(self):
  seen=[]
  def execute(c,n):
   seen.append(n);choices=c['ability_target_choices']
   if not choices:v=ambiguity(18,2)
   elif c['prune_below_oracle']:v=self.pruned(5 if choices['18']==1 else 20)
   elif choices['18']==1:v=ambiguity(24,0)
   else:v=dict(report(),gap=400)
   return v,{'attempt':n}
  c,r,d=ability.search_with_hp_floor(self.prep,execute,lambda *_:False,score=lambda c,r:r['gap'])
  self.assertEqual(c['ability_target_choices'],{'18':0});self.assertEqual(seen,list(range(5)))
  self.assertEqual([x['completed'] for x in d['floor_fallback_prefixes']],[False,True])
 def test_user_stop_never_claims_exhaustion(self):
  ready=[]
  def execute(c,n):return (ambiguity(18,2) if not c['ability_target_choices'] else dict(report(),gap=50)),{}
  c,r,d=ability.search_with_hp_floor(self.prep,execute,lambda *_:False,score=lambda c,r:r['gap'],on_best=lambda *_:ready.append(True),stop_requested=lambda:bool(ready))
  self.assertTrue(d['stopped_by_user']);self.assertFalse(d['explored_branches_exhausted']);self.assertFalse(d['floor_fallback_used'])
if __name__=='__main__':unittest.main()
