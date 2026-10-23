import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'device'),str(ROOT.parent/'windows-adaptation/project/official-web-replay')]
from skill_candidate_pool import Pool,EmptyPool,ordered,actor_plan
SOURCE={'decks':[dict(proposed_native_owner=o,oracle_elixir_leaked=v) for o,v in enumerate((1.5,.95))]}
def preparation(seed=1):return dict(initialization_only={'rndSeed':seed},participants={'team':{'native_owner':0}},events=[dict(kind='activate_ability',source_tick_20hz=20,source_side='team')])
def complete(name='GoldenKnight',leak=15028,cost=1):
 return dict(error=0,finished=1,tick=100,executed=1,native_accepted=1,commands=[{'ct':189,'c':{'t':20,'t2':20}}],dispatch=[dict(index=0,kind=189,tick=20,flags=3,code=0)],diagnostics=[dict(index=0,tick=20,owner=0,card=0,actor={'cost':cost})],ability_observations=[dict(phase='selected',event_index=0,selected_ordinal=0,actors=[{'name':name}])],elixir=[dict(leaked=v,spent=10000) for v in (leak,9579)])
def ambiguous():return dict(error=112,finished=0,native_code=2,event_index=0,native_accepted=0)
class PoolTests(unittest.TestCase):
 def setUp(self):self.pool=Pool(SOURCE,lambda s,c,r:('exact',0));self.calls=[]
 def execute(self,c,i):
  self.calls.append(copy.deepcopy(c));choices=c['ability_target_choices']
  return (ambiguous() if not choices else complete(leak=15028 if choices['0']==0 else 25028)),{'attempt':'candidate-'+str(len(self.calls))}
 def filled(self):return self.pool.enumerate(preparation(),self.execute)
 def test_enumerates_every_branch_even_after_exact_and_keeps_only_elixir_matches(self):
  _,_,report=self.filled();self.assertEqual(len(self.calls),3);self.assertEqual(len(self.pool.entries),1);self.assertTrue(report['pool_enumeration_complete']);self.assertEqual(report['remaining'],0)
 def test_all_complete_combinations_are_retained(self):
  def execute(c,i):return (ambiguous() if not c['ability_target_choices'] else complete('GoldenKnight' if c['ability_target_choices']['0']==0 else 'BossBandit')),{'attempt':str(i)}
  self.pool.enumerate(preparation(),execute);self.assertEqual(len(self.pool.entries),2)
 def test_other_seed_only_runs_frozen_identity_never_expands(self):
  self.filled();calls=[]
  def execute(c,i):calls.append(c);return complete(),{'attempt':'seed-1'}
  self.pool.evaluate(preparation(2),execute);self.assertEqual(len(calls),1);self.assertEqual(calls[0]['ability_target_choices'],{});self.assertEqual(calls[0]['ability_actor_names'],{'0':'GoldenKnight'})
 def test_new_seed_ambiguity_is_rejected_without_adding_children(self):
  self.filled();calls=[]
  def execute(c,i):calls.append(c);return ambiguous(),{'attempt':'seed-1'}
  with self.assertRaises(EmptyPool):self.pool.evaluate(preparation(2),execute)
  self.assertEqual(len(calls),1);self.assertEqual(len(self.pool.entries),1)
 def test_elixir_must_be_checked_again_under_each_seed(self):
  self.filled()
  with self.assertRaises(EmptyPool):self.pool.evaluate(preparation(2),lambda c,i:(complete(leak=25028),{'attempt':'bad'}))
 def test_actual_skill_identity_cannot_switch_when_ordinal_changes(self):
  self.filled()
  with self.assertRaises(EmptyPool):self.pool.evaluate(preparation(2),lambda c,i:(complete('BossBandit'),{'attempt':'bad'}))
 def test_actual_payment_sequence_cannot_change(self):
  self.filled()
  with self.assertRaises(EmptyPool):self.pool.evaluate(preparation(2),lambda c,i:(complete(cost=2),{'attempt':'bad'}))
 def test_complete_but_wrong_order_never_enters_pool(self):
  r=complete();r['diagnostics'][0]['tick']=21
  with self.assertRaises(EmptyPool):self.pool.enumerate(preparation(),lambda c,i:(r,{'attempt':'bad'}))
  self.assertFalse(self.pool.entries)
 def test_origin_empty_can_build_at_first_qualifying_seed(self):
  r=complete(leak=25028)
  with self.assertRaises(EmptyPool):self.pool.enumerate(preparation(),lambda c,i:(r,{'attempt':'origin'}))
  self.pool.enumerate(preparation(2),lambda c,i:(complete(),{'attempt':'first-good'}));self.assertEqual(self.pool.seed,2);self.assertEqual(len(self.pool.entries),1)
 def test_unknown_elixir_never_enters_pool(self):
  r=complete();r.pop('elixir')
  with self.assertRaises(EmptyPool):self.pool.enumerate(preparation(),lambda c,i:(r,{'attempt':'bad'}))
 def test_same_named_duplicate_actor_is_not_frozen_ambiguously(self):
  r=complete();r['ability_observations'][0]['actors'].append({'name':'GoldenKnight'})
  with self.assertRaises(EmptyPool):self.pool.enumerate(preparation(),lambda c,i:(r,{'attempt':'bad'}))
 def test_stop_cancellation_does_not_submit(self):
  with self.assertRaises(RuntimeError):self.pool.enumerate(preparation(),self.execute,cancelled=lambda:True)
  self.assertEqual(self.calls,[])
 def test_real_85_event_order_and_all_16_skills(self):
  base=Path.cwd()
  if not (base/'work/hotfix55-64-port/second-acceptance/qualifying-source-execution.json').exists():self.skipTest('Local acceptance evidence not present')
  prep=json.loads((base/'work/skill-user-target-preparation.json').read_text(encoding='utf-8'));report=json.loads((base/'work/hotfix55-64-port/second-acceptance/qualifying-source-execution.json').read_text(encoding='utf-8'))
  self.assertTrue(ordered(prep,report));names,costs=actor_plan(prep,report);self.assertEqual(len(names),16);self.assertEqual(costs['76'],2)

class Hotfix70PoolTests(unittest.TestCase):
 def test_explicit_exact_stop_preserves_unvisited_branches(self):
  pool=Pool(SOURCE,lambda *a:('exact',0));calls=[]
  def execute(c,i):
   calls.append(c);return (ambiguous() if not c['ability_target_choices'] else complete()),{'attempt':str(i)}
  _,_,result=pool.enumerate(preparation(),execute,stop_on_exact=True);self.assertEqual(len(calls),2);self.assertGreater(result['remaining'],0);self.assertFalse(result['pool_enumeration_complete'])
 def test_exact_predicate_cannot_bypass_actual_elixir(self):
  pool=Pool(SOURCE,lambda *a:('exact',0));calls=[]
  def execute(c,i):
   calls.append(c);choices=c['ability_target_choices'];return (ambiguous() if not choices else complete(leak=25028 if choices['0']==0 else 15028)),{'attempt':str(i)}
  _,_,result=pool.enumerate(preparation(),execute,stop_on_exact=True);self.assertEqual(len(calls),3);self.assertEqual(len(pool.entries),1)
 def test_single_available_actor_is_repaired(self):
  pool=Pool(SOURCE,lambda *a:('same_towers',100));calls=[]
  def execute(c,i):
   calls.append(c);r=ambiguous();r['native_code']=1;return (r if not c['ability_target_choices'] else complete()),{'attempt':str(i)}
  pool.enumerate(preparation(),execute);self.assertEqual(len(calls),2);self.assertEqual(calls[-1]['ability_target_choices'],{'0':0})
 def test_exact_fixed_candidate_stops_other_candidates_and_refinement(self):
  pool=Pool(SOURCE,lambda *a:('exact',0));pool.enumerate(preparation(),lambda c,i:(complete(),{'attempt':'origin'}));pool.entries.append(dict(actors={'0':'BossBandit'},costs={'0':1}));calls=[]
  def execute(c,i):calls.append(c);return complete(),{'attempt':str(i)}
  _,_,r=pool.evaluate(preparation(2),execute,alns_budget=4);self.assertEqual(len(calls),1);self.assertEqual(r['alns_allocation']['granted'],0);self.assertTrue(r['final_hp_matched'])
