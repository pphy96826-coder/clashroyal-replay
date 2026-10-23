import ast,copy,sys,textwrap,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'device'),str(ROOT.parent/'windows-adaptation/project/official-web-replay')]
from ability_search import CandidateMemo
class DispatchTests(unittest.TestCase):
 def test_only_first_qualifying_seed_enumerates_later_seeds_evaluate_pool(self):
  source=(ROOT/'device/device_playback.py').read_text(encoding='utf-8');node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='run_seed');calls=[];native=[]
  class Pool:
   seed=1
   alns_total_budget=12
   screen_limit=2
   refinement_used=0
   explorer=SimpleNamespace(history=[])
   def __init__(self):self.entries=[]
   def enumerate(self,trial,execute,**kwargs):calls.append('enumerate');self.entries=[1];self.seed=trial['seed'];return trial,*execute(trial,0)
   def evaluate(self,trial,execute,**kwargs):calls.append(('evaluate',kwargs['alns_budget']));return trial,*execute(trial,0)
  pool=Pool()
  def execute(candidate,index):native.append(candidate['seed']);return {'error':0},{'attempt':'native-'+str(len(native))}
  def forbidden(*args,**kwargs):raise AssertionError('seed tried dynamic branch search')
  ns=dict(context={'skill_pool_mode':True},skill_pool=pool,candidate_memo=CandidateMemo(),identity={},candidate_scope=lambda i:{'pid':1},snapshots={},execute_candidate=execute,search=forbidden,seed_stop=lambda:False,destination=Path('.'),save_skill_pool=lambda:None,seed_report={},progress_observer=SimpleNamespace(observe=lambda *a:None,message=lambda:''),status=lambda *a,**k:None)
  factory="def factory():\n    attempt_prefix=''\n"+textwrap.indent(ast.unparse(node),'    ')+"\n    return run_seed\n";exec(factory,ns);run=ns['factory']()
  for i in range(3):run(i,i,{'seed':i},'seed-'+str(i)+'-')
  self.assertEqual(calls,['enumerate',('evaluate',0),('evaluate',0)]);self.assertEqual(native,[0,1,2]);self.assertFalse(ns['seed_report']['skill_pool']['per_seed_branch_expansion'])

class RefineAllocationTests(unittest.TestCase):
 def run_loop(self,*,costs=(100,10,30,20,200),incumbent=10,used=0,total=6,stop=False,exhausted=(),partial_first=False):
  source=(ROOT/'device/device_playback.py').read_text(encoding='utf-8');tree=ast.parse(source);node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="closest_abilities and best[2] != 'exact' and (not seed_stop())");calls=[]
  pool=SimpleNamespace(explorer=SimpleNamespace(history=[{}]*used),alns_total_budget=total,refinement_used=used)
  def run_seed(number,seed,trial,prefix,**options):
   calls.append((seed,options,prefix));spent=0 if seed in exhausted else 1
   if spent:pool.explorer.history.append({});pool.refinement_used+=1
   if partial_first and len(calls)==1:
    error=RuntimeError('no complete result in this slice');error.search_report={'alns_allocation':{'used':1,'can_continue':True}};raise error
   return ({},{},{'alns_allocation':{'used':spent}})
  ns=dict(planned_seeds=list(range(len(costs))),context={'skill_pool_mode':True},screened=[((False,1,cost),i,i,{}, {}) for i,cost in enumerate(costs)],REFINE_SEEDS=3,REFINE_RUNS=24,destination=Path('.'),seed_stop=lambda:stop,seed_report={'attempts':[]},status=lambda *a,**k:None,closest_text=lambda:'',SEED_ATTEMPTS=60,best=(None,None,'same_towers',incumbent),skill_pool=pool,incumbent=lambda:incumbent,run_seed=run_seed,hp_key=None,consider=lambda *a:None,Cancelled=type('Cancelled',(Exception,),{}))
  exec(compile(ast.Module(body=node.body,type_ignores=[]),'actual-refine-loop','exec'),ns);return calls,ns['seed_report']['attempts']
 def test_only_top_three_receive_interleaved_refinement(self):
  calls,_=self.run_loop();self.assertEqual([r[0] for r in calls],[1,3,2,1,3,2]);self.assertTrue(all(r[1]['pool_alns_budget']==1 for r in calls))
 def test_no_improvement_does_not_remove_seed(self):self.assertEqual([r[0] for r in self.run_loop(costs=(10,200,300))[0]],[0,1,2,0,1,2])
 def test_exhausted_global_budget_stops_dispatch(self):self.assertEqual(self.run_loop(used=6)[0],[])
 def test_user_stop_prevents_refinement(self):self.assertEqual(self.run_loop(stop=True)[0],[])
 def test_ranking_uses_comprehensive_cost(self):self.assertEqual([r[0] for r in self.run_loop(costs=(90,30,10,20))[0]][:3],[2,3,1])
 def test_exhausted_seed_removed_and_budget_flows_to_others(self):
  calls,_=self.run_loop(exhausted=(1,));self.assertEqual([r[0] for r in calls],[1,3,2,3,2,3,2])
 def test_failed_slice_with_deferred_work_gets_another_round(self):
  calls,rows=self.run_loop(partial_first=True);self.assertEqual([r[0] for r in calls],[1,3,2,1,3,2]);self.assertTrue(rows[0]['alns_allocation']['can_continue'])
 def test_each_round_has_distinct_native_attempt_prefix(self):
  calls,_=self.run_loop();self.assertEqual(len({r[2] for r in calls}),len(calls))

class BestRetentionTests(unittest.TestCase):
 def consider(self,*,old_cost=50,new_cost=20,old_tier='same_towers',new_tier='same_winner',pool=True):
  source=(ROOT/'device/device_playback.py').read_text(encoding='utf-8');node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='consider')
  ns=dict(cost_text=lambda *a:'',status=lambda *a,**k:None,context={'skill_pool_mode':pool},selected_candidate={},restore=lambda s:None,read=lambda p:{},source=None,page_comparison=lambda s,c,r:(new_tier,new_cost),page_breakdown=lambda *a:{'hp_difference':new_cost},ELIXIR_MISMATCH_COST=10**9,elixir_gate=lambda *a:'bad elixir',PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different','unknown'),rank=lambda t,c:(False,('exact','same_towers','same_winner','different','unknown').index(t),c))
  ns['initial']=((False,1,old_cost),1,old_tier,old_cost,({}, {},{},{}))
  factory="def factory():\n    best=initial\n"+textwrap.indent(ast.unparse(node),'    ')+"\n    return consider,lambda:best\n";exec(factory,ns);consider,get=ns['factory']();consider(0,2,({}, {},{}),{});return get()
 def test_lower_cost_replaces_best_even_if_tier_is_lower(self):self.assertEqual(self.consider()[3],20)
 def test_worse_later_result_cannot_replace_history_best(self):self.assertEqual(self.consider(new_cost=70,new_tier='exact')[3],50)
 def test_elixir_failure_cannot_replace_best(self):
  with self.assertRaises(RuntimeError):self.consider(new_cost=10**9)
 def test_non_pool_path_keeps_existing_tier_policy(self):self.assertEqual(self.consider(pool=False)[3],50)
