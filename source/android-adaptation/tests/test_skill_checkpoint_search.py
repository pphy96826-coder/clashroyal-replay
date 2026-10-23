from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'device'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'windows-adaptation/project/official-web-replay'))
from skill_checkpoint_search import search,requested_seed
class CheckpointTests(unittest.TestCase):
 def setUp(self):self.prep=dict(source_sha256='test',events=[dict(kind='activate_ability',source_tick_20hz=100)],initialization_only={'rndSeed':123})
 def checkpoint(self,hp):return dict(error=126,tick=2800,executed=1,native_accepted=1,finished=0,commands=[dict(ct=189,c=dict(t=100,t2=100))],dispatch=[dict(index=0,kind=189,tick=100,flags=3,code=0)],hp_floor_violation=None,skill_checkpoints=[dict(native_tick=2800,all_tower_hp=[[4000,3000,3000],[4000,hp,2800]])])
 def test_free_choices_enumerated_and_strict_greater(self):
  seen=[]
  def execute(c,n):
   seen.append(c);v=dict(error=112,event_index=0,native_code=2) if not c['ability_target_choices'] else self.checkpoint(2417 if c['ability_target_choices']['0']==0 else 2420)
   return v,{'attempt':n}
  r=search(self.prep,execute);self.assertEqual(len(r['attempts']),3);self.assertEqual(len(r['solutions']),1)
  self.assertEqual(r['solutions'][0]['checkpoint_hp'],2420);self.assertFalse(r['full_source_completed']);self.assertTrue(r['reachable_prefix_tree_exhausted'])
  self.assertTrue(all(c['ability_actor_names']=={} for c in seen));self.assertTrue(all(c['events']==self.prep['events'] for c in seen))
 def test_rejected_prefix_not_accepted_as_checkpoint(self):
  bad=self.checkpoint(2900);bad['dispatch'][0]['code']=4
  with self.assertRaises(ValueError):search(self.prep,lambda *_:(bad,{}))
 def test_floor_rejection_never_resumed_for_this_goal(self):
  r=search(self.prep,lambda *_:(dict(error=123,event_index=0,hp_floor_violation={'actual_hp':2400}),{}))
  self.assertFalse(r['solutions']);self.assertEqual(len(r['attempts']),1)
 def test_budget_is_not_exhaustive(self):
  r=search(self.prep,lambda *_:(dict(error=112,event_index=0,native_code=2),{}),max_attempts=1)
  self.assertTrue(r['budget_exhausted']);self.assertFalse(r['reachable_prefix_tree_exhausted'])
 def test_locked_actor_is_rejected(self):
  with self.assertRaises(ValueError):search(dict(self.prep,ability_actor_names={'0':'GoldenKnight'}),lambda *_:None)
 def test_seed_must_be_from_deterministic_plan(self):
  self.assertEqual(requested_seed({},123,[456]),123)
  self.assertEqual(requested_seed({'random_seed':456},123,[456]),456)
  for value in (789,True,'456'):
   with self.assertRaises(ValueError):requested_seed({'random_seed':value},123,[456])
if __name__=='__main__':unittest.main()
