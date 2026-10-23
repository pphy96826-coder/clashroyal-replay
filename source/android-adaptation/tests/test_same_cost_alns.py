import copy,unittest
from test_skill_candidate_pool import preparation,complete,SOURCE,Pool,actor_plan
from alns_skills import Explorer,domains

def observed(name='GoldenKnight',cost=1,value=100):
 r=complete(name,cost=cost);r['value']=value;r['ability_observations'].insert(0,dict(phase='available',event_index=0,actors=[dict(name='GoldenKnight',definition_id=1,cost=1),dict(name='BossBandit',definition_id=2,cost=1),dict(name='goblinstein_doctor',definition_id=3,cost=2)]));return r
class AlnsTests(unittest.TestCase):
 def setUp(self):
  self.prep=preparation(123);self.candidate=copy.deepcopy(self.prep);self.candidate.update(ability_actor_names={'0':'GoldenKnight'},ability_target_choices={});self.base=observed();self.pool=Pool(SOURCE,self.compare);self.explorer=Explorer();self.calls=[]
 def compare(self,source,candidate,report):return 'same_towers',report.get('value',100)
 def execute(self,candidate,index):
  self.calls.append(copy.deepcopy(candidate));return observed(candidate['ability_actor_names']['0'],value=50),{'attempt':str(index)}
 def run_search(self,execute=None,**options):return self.explorer.run(self.prep,[(self.candidate,self.base,{'attempt':'base'},{'0':1})],execute or self.execute,self.pool.qualified,actor_plan,self.compare,SOURCE,**options)
 def test_only_same_cost_other_identity_is_mutated(self):
  rows=self.run_search();self.assertEqual(len(rows),1);self.assertEqual(self.calls[0]['ability_actor_names'],{'0':'BossBandit'});self.assertTrue(rows[0][-1]['improved'])
 def test_full_stream_seed_and_ownership_unchanged(self):
  self.run_search();trial=self.calls[0];self.assertEqual(trial['events'],self.prep['events']);self.assertEqual(trial['participants'],self.prep['participants']);self.assertEqual(trial['initialization_only'],self.prep['initialization_only']);self.assertEqual(trial['ability_target_choices'],{})
 def test_different_cost_is_never_used(self):self.assertEqual(domains(self.base,{'0':1}),{'0':['BossBandit','GoldenKnight']})
 def test_unknown_cost_not_guessed(self):
  for actor in self.base['ability_observations'][0]['actors']:actor.pop('cost')
  self.assertEqual(self.run_search(),[]);self.assertEqual(self.calls,[])
 def test_real_payment_mismatch_rejected(self):
  rows=self.run_search(lambda c,i:(observed(c['ability_actor_names']['0'],cost=2),{'attempt':'wrong-payment'}));self.assertFalse(rows[0][-1]['qualified'])
 def test_same_cost_does_not_bypass_elixir_gate(self):
  def execute(c,i):
   r=observed(c['ability_actor_names']['0']);r['elixir'][0]['leaked']=25028;return r,{'attempt':'bad-leak'}
  self.assertFalse(self.run_search(execute)[0][-1]['qualified'])
 def test_same_cost_does_not_bypass_order_gate(self):
  def execute(c,i):
   r=observed(c['ability_actor_names']['0']);r['diagnostics'][0]['tick']=99;return r,{'attempt':'bad-order'}
  self.assertFalse(self.run_search(execute)[0][-1]['qualified'])
 def test_no_duplicate_native_candidates(self):self.run_search(budget=20);self.assertEqual(len(self.calls),1)
 def test_operator_weights_follow_feedback(self):
  self.explorer.small_space_limit=1;self.explorer.coverage_trials=0;rows=self.run_search();op=rows[0][-1]['operator'];self.assertGreater(self.explorer.weights[op],1);self.assertFalse(rows[0][-1]['exhaustive'])
 def test_cancel_before_native_submission(self):
  with self.assertRaises(RuntimeError):self.run_search(cancelled=lambda:True)
  self.assertEqual(self.calls,[])
 def test_stop_keeps_verified_incumbent_without_submission(self):self.assertEqual(self.run_search(stop_early=lambda:True),[]);self.assertEqual(self.calls,[])
 def test_no_improvement_does_not_stop_discrete_search(self):
  candidate=copy.deepcopy(self.candidate);candidate['ability_actor_names']={str(i):'GoldenKnight' for i in range(3)};costs={str(i):1 for i in range(3)}
  report={'value':100,'ability_observations':[dict(phase='available',event_index=i,actors=[dict(name=n,cost=1) for n in ('GoldenKnight','BossBandit')]) for i in range(3)]};calls=[]
  def execute(c,i):calls.append(c);return copy.deepcopy(report),{'attempt':str(i)}
  rows=self.explorer.run(self.prep,[(candidate,report,{},costs)],execute,lambda c,r:True,lambda c,r:(c['ability_actor_names'],costs),self.compare,SOURCE,budget=4)
  self.assertEqual(len(rows),4);self.assertEqual(len(calls),4);self.assertTrue(all(not r[-1]['improved'] for r in rows))
 def test_legacy_unfiltered_evidence_can_join_costs_by_definition(self):
  r=self.base
  for actor in r['ability_observations'][0]['actors']:actor.pop('cost')
  r['diagnostics'][0]['eligible']=[{'id':1,'cost':1},{'id':2,'cost':1},{'id':3,'cost':2}]
  self.assertEqual(domains(r,{'0':1}),{'0':['BossBandit','GoldenKnight']})

class AllocationTests(unittest.TestCase):
 setUp=AlnsTests.setUp
 compare=AlnsTests.compare
 execute=AlnsTests.execute
 def fill(self):
  self.pool.enumerate(self.prep,lambda c,i:(observed(),{'attempt':'pool'}));self.calls=[]
 def test_screening_does_not_run_alns(self):
  self.fill();_,_,r=self.pool.evaluate(preparation(2),self.execute);self.assertEqual(len(self.calls),1);self.assertEqual(self.pool.explorer.history,[]);self.assertEqual(r['alns_allocation']['granted'],0)
 def test_only_explicit_refinement_runs_alns(self):
  self.fill();_,_,r=self.pool.evaluate(preparation(2),self.execute,alns_budget=4);self.assertEqual(len(self.calls),2);self.assertEqual(r['alns_allocation']['used'],1);self.assertEqual(r['alns_allocation']['granted'],4)
 def test_history_best_is_retained_after_worse_seed(self):
  self.fill();self.pool.elite={'actors':{'0':'GoldenKnight'},'costs':{'0':1},'key':(1,1)}
  def bad(c,i):self.calls.append(c);return observed(c['ability_actor_names']['0'],value=500),{'attempt':'bad'}
  self.pool.evaluate(preparation(2),bad,alns_budget=1);self.assertEqual(self.pool.elite['key'],(1,1));self.assertEqual(len(self.calls),2)
 def test_global_budget_is_not_reset_per_seed(self):
  self.fill();self.pool.alns_total_budget=2
  for seed in (2,3,4):self.pool.evaluate(preparation(seed),self.execute,alns_budget=4)
  self.assertEqual(len(self.pool.explorer.history),2);self.assertEqual(self.pool.snapshot()['alns_remaining_budget'],0);self.assertEqual(self.pool.allocations[-1]['granted'],0)
 def test_repeated_seed_does_not_repeat_mutations(self):
  self.fill()
  for _ in range(2):self.pool.evaluate(preparation(2),self.execute,alns_budget=4,scope={'generation':1},verify_reuse=lambda records:True)
  self.assertEqual(len(self.pool.explorer.history),1)
 def test_invalid_budget_rejected_before_native_call(self):
  self.fill()
  for value in (-1,5,True,None):
   with self.assertRaises(ValueError):self.pool.evaluate(preparation(2),self.execute,alns_budget=value)
  self.assertEqual(self.calls,[])
 def test_invalid_base_cannot_spend_refinement_budget(self):
  from skill_candidate_pool import EmptyPool
  self.fill()
  def bad(c,i):self.calls.append(c);return observed(c['ability_actor_names']['0'],cost=2),{'attempt':'bad'}
  with self.assertRaises(EmptyPool):self.pool.evaluate(preparation(2),bad,alns_budget=4)
  self.assertEqual(len(self.calls),1);self.assertEqual(self.pool.allocations[-1]['granted'],0)

class DiscreteCoverageTests(unittest.TestCase):
 def setup_search(self,n=3):
  explorer=Explorer();prep=preparation(901);candidate=copy.deepcopy(prep);candidate['ability_actor_names']={str(i):'GoldenKnight' for i in range(n)};costs={str(i):1 for i in range(n)}
  report={'value':100,'ability_observations':[dict(phase='available',event_index=i,actors=[dict(name=name,cost=1) for name in ('GoldenKnight','BossBandit')]) for i in range(n)]};calls=[]
  def execute(c,i):
   calls.append(copy.deepcopy(c));r=copy.deepcopy(report);r['value']=1 if list(c['ability_actor_names'].values())==['GoldenKnight']*(n-1)+['BossBandit'] else 200;return r,{'attempt':str(i)}
  def run(budget=1):return explorer.run(prep,[(candidate,report,{},costs)],execute,lambda c,r:True,lambda c,r:(c['ability_actor_names'],costs),lambda s,c,r:('same_towers',r['value']),SOURCE,budget=budget)
  return explorer,calls,run
 def test_small_space_exhausted_despite_six_worse_results(self):
  e,calls,run=self.setup_search();rows=run(20);self.assertEqual(len(rows),7);self.assertTrue(rows[-1][-1]['improved']);self.assertTrue(e.snapshot()['seed_spaces'][0]['observed_domains_complete']);self.assertEqual(e.snapshot()['seed_spaces'][0]['remaining'],0)
 def test_rounds_resume_without_repeating_or_losing_best(self):
  e,calls,run=self.setup_search()
  for _ in range(9):run()
  self.assertEqual(len(calls),7);self.assertEqual(len({tuple(sorted(c['ability_actor_names'].items())) for c in calls}),7);self.assertEqual(e.snapshot()['seed_spaces'][0]['best_cost'],1)
 def test_large_space_coverage_precedes_local_search(self):
  e,calls,run=self.setup_search(5);rows=run(10);self.assertEqual(len(rows),10);self.assertTrue(all(r[-1]['phase']=='diverse-coverage' for r in rows[:4]));self.assertTrue(all(r[-1]['phase']=='adaptive-local' for r in rows[4:]));self.assertEqual(len({tuple(sorted(c['ability_actor_names'].items())) for c in calls}),10)
 def test_first_diverse_plan_covers_distant_choices(self):
  e,calls,run=self.setup_search(5);run();self.assertEqual(sum(n=='BossBandit' for n in calls[0]['ability_actor_names'].values()),5)
 def test_small_exhaustion_does_not_claim_unobserved_engine_branches(self):
  e,calls,run=self.setup_search();run(20);self.assertFalse(e.snapshot()['exhaustive']);self.assertFalse(e.snapshot()['stop_on_stagnation'])
