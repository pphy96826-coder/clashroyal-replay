"""Feedback allocation must preserve search frontiers and completion gates."""
import copy
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'device'),str(Path(__file__).resolve().parent)]
from test_extreme_ability_search import report,ambiguity,ABILITIES
import adaptive_skill_search as adaptive


class AdaptiveTests(unittest.TestCase):
 def setUp(self):
  self.prep=dict(events=[dict(kind='activate_ability' if i in ABILITIES else 'play_card') for i in range(85)],
                 initialization_only={'rndSeed':1},ability_actor_names={'18':'stale-name'})
  self.prepared=[];self.snapshots=[]
 def prepare(self,seed,number):
  self.prepared.append(seed);p=copy.deepcopy(self.prep);p['initialization_only']['rndSeed']=seed;return p
 def run_search(self,execute,**kw):
  return adaptive.search(self.prep,[2,3],self.prepare,execute,lambda c,r:r.get('gap')==0,
                         lambda c,r:r['gap'],on_snapshot=self.snapshots.append,**kw)
 def test_each_seed_discovers_its_own_skill_and_revisits_saved_frontier(self):
  seen=[]
  def execute(c,n):
   seed=c['initialization_only']['rndSeed'];choices=c['ability_target_choices'];seen.append((seed,dict(choices)))
   self.assertEqual(c['ability_actor_names'],{})
   return (ambiguity(18,4) if not choices else dict(report(),gap=abs(choices['18']-(seed%4))*100+seed)),{'attempt':n}
  c,r,d=self.run_search(execute,max_attempts=30)
  self.assertEqual(len(seen),15);self.assertEqual(len(set((s,tuple(v.items())) for s,v in seen)),15)
  self.assertEqual(set(self.prepared),{2,3});self.assertEqual(d['selected_hp_difference'],1)
  self.assertTrue(any(x['action']=='revisit' for x in d['decisions']))
  self.assertTrue(d['explored_branches_exhausted']);self.assertFalse(d['exhaustive'])
  self.assertEqual(self.prep['ability_actor_names'],{'18':'stale-name'})
 def test_budget_retains_every_unvisited_branch_without_fallback(self):
  def execute(c,n):return (ambiguity(18,4) if not c['ability_target_choices'] else dict(report(),gap=100)),{'attempt':n}
  c,r,d=self.run_search(execute,max_attempts=5)
  self.assertTrue(d['budget_exhausted']);self.assertGreater(d['remaining'],0)
  self.assertFalse(d['explored_branches_exhausted']);self.assertFalse(d['floor_fallback_used'])
  self.assertEqual(sum(s['visits'] for s in d['seeds']),5)
 def test_better_other_seed_returns_its_own_preparation_and_evidence(self):
  def execute(c,n):
   seed=c['initialization_only']['rndSeed'];choices=c['ability_target_choices']
   v=ambiguity(18,2) if not choices else dict(report(),gap=1 if seed==2 and choices['18']==1 else 100)
   return v,{'attempt':n,'seed':seed,'choices':dict(choices)}
  c,r,d=self.run_search(execute)
  self.assertEqual(c['initialization_only']['rndSeed'],2)
  self.assertEqual(c['ability_target_choices'],{'18':1})
  self.assertEqual(d['selected_evidence']['seed'],2)
  self.assertEqual(d['selected_evidence']['choices'],{'18':1})
 def test_incomplete_zero_gap_cannot_win(self):
  scored=Mock(return_value=0)
  with self.assertRaises(RuntimeError) as error:
   adaptive.search(self.prep,[],self.prepare,lambda *_:(dict(report(),finished=0,gap=0),{}),
                   lambda *_:True,scored)
  scored.assert_not_called();self.assertIsNone(error.exception.search_report['selected_evidence'])
 def test_rejected_dispatch_never_competes(self):
  bad=report();bad['dispatch'][24]['code']=1
  with self.assertRaises(RuntimeError):self.run_search(lambda *_:(dict(bad,gap=0),{}),max_seeds=1)
 def test_stop_returns_best_only_at_safe_boundary(self):
  ready=[]
  c,r,d=self.run_search(lambda c,n:(dict(report(),gap=50),{'attempt':n}),
      on_best=lambda *_:ready.append(True),stop_requested=lambda:bool(ready))
  self.assertEqual(len(d['attempts']),1);self.assertTrue(d['stopped_by_user'])
  self.assertFalse(d['explored_branches_exhausted'])
 def test_cancel_submits_no_candidate(self):
  execute=Mock()
  with self.assertRaisesRegex(RuntimeError,'取消'):self.run_search(execute,cancelled=lambda:True)
  execute.assert_not_called()
 def test_budget_exception_preserves_unsubmitted_choices_and_existing_best(self):
  class Budget(Exception):pass
  def execute(c,n):
   if n:raise Budget()
   return dict(report(),gap=100),{'attempt':n}
  c,r,d=self.run_search(execute,boundary_errors=(Budget,))
  self.assertTrue(d['budget_exhausted']);self.assertEqual(len(d['attempts']),1)
  self.assertEqual(d['remaining'],2);self.assertEqual(d['selected_evidence'],{'attempt':0})
 def test_no_best_budget_raises_with_frontier(self):
  class Budget(Exception):pass
  with self.assertRaises(RuntimeError) as error:self.run_search(Mock(side_effect=Budget()),boundary_errors=(Budget,))
  self.assertEqual(error.exception.search_report['remaining'],3)
 def test_floor_fallback_waits_for_all_admitted_strict_seeds(self):
  seen=[]
  def execute(c,n):
   seed=c['initialization_only']['rndSeed'];strict=c['prune_below_oracle'];seen.append((seed,strict))
   v=dict(error=123,native_accepted=25,gap=seed,hp_floor_violation={'native_tick':1200}) if strict else dict(report(),gap=seed*10)
   return v,{'attempt':n}
  c,r,d=self.run_search(execute)
  self.assertEqual([x[1] for x in seen],[True]*3+[False]*3)
  self.assertTrue(d['floor_fallback_used']);self.assertTrue(d['continued_by_fresh_simulation'])
 def test_strict_budget_never_claims_all_seeds_fail_or_starts_fallback(self):
  with self.assertRaises(RuntimeError) as error:
   self.run_search(lambda *_:(dict(error=123,native_accepted=25,gap=1,hp_floor_violation={}),{}),max_attempts=1)
  d=error.exception.search_report
  self.assertEqual(d['phase'],'strict');self.assertTrue(d['budget_exhausted']);self.assertEqual(d['remaining'],2)
 def test_first_fallback_uses_smallest_checkpoint_gap_across_seeds(self):
  seen=[]
  def execute(c,n):
   seed=c['initialization_only']['rndSeed'];strict=c['prune_below_oracle'];seen.append((seed,strict))
   v=dict(error=123,native_accepted=25,gap=40-seed*10,hp_floor_violation={}) if strict else dict(report(),gap=100)
   return v,{'attempt':n}
  self.run_search(execute)
  self.assertEqual(seen[3],(3,False))
 def test_exact_stops_without_claiming_exhaustive_or_unique(self):
  c,r,d=self.run_search(lambda c,n:(dict(report(),gap=0),{'attempt':n}))
  self.assertEqual(len(d['attempts']),1);self.assertEqual(d['stop_reason'],'exact_terminal_hp')
  self.assertFalse(d['exhaustive']);self.assertFalse(d['unique_solution_proven'])
 def test_time_budget_returns_best_and_retains_unexplored(self):
  now=[0.]
  def execute(c,n):now[0]+=10;return dict(report(),gap=1),{'attempt':n}
  c,r,d=self.run_search(execute,max_seconds=5,clock=lambda:now[0])
  self.assertEqual(len(d['attempts']),1);self.assertTrue(d['budget_exhausted'])
 def test_guard_and_checkpoint_are_not_branch_quality_feedback(self):
  for code in (125,126):
   with self.subTest(code=code),self.assertRaises(ValueError):self.run_search(lambda *_:(dict(error=code),{}))
 def test_bad_calibration_seed_aborts_without_candidate(self):
  def wrong(seed,n):return self.prep
  def execute(c,n):return dict(error=114),{}
  with self.assertRaisesRegex(ValueError,'seed identity'):
   adaptive.search(self.prep,[2],wrong,execute,lambda *_:False,lambda *_:0)
 def test_invalid_ambiguity_aborts(self):
  with self.assertRaisesRegex(ValueError,'source skill'):self.run_search(lambda *_:(ambiguity(0,2),{}))
 def test_cost_feedback_prefers_cheaper_seed_with_equal_quality(self):
  now=[0.]
  def execute(c,n):
   now[0]+=100 if c['initialization_only']['rndSeed']==1 else 1
   choices=c['ability_target_choices']
   return (ambiguity(18,20) if not choices else dict(report(),gap=100)),{'attempt':n}
  c,r,d=self.run_search(execute,max_attempts=15,max_seconds=10000,clock=lambda:now[0])
  counts={s['seed']:s['visits'] for s in d['seeds']}
  self.assertLess(counts[1],counts[2]+counts[3]);self.assertGreater(counts[1],0)
  self.assertTrue(any(x['observed_seconds']==100 for x in d['decisions']))
 def test_device_calibration_uses_existing_owned_attempt_names(self):
  from mumu_ownership import ATTEMPT
  source=(ROOT/'device/device_playback.py').read_text(encoding='utf-8')
  node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='adaptive_prepare')
  labels=[]
  def probe(label):
   self.assertIsNotNone(ATTEMPT.fullmatch(label));labels.append(label);return {}
  with tempfile.TemporaryDirectory() as d:
   scope=dict(copy=copy,delayed=self.prep,preparation=Path(d),
    deck_fingerprint=lambda p:p['initialization_only']['rndSeed'],probe=probe,
    write_new=lambda p,v:p.write_text(json.dumps(v)),
    calibrate=lambda p,r,seen:dict(p,native_deal_ready=len(seen)==2))
   exec(ast.unparse(node).replace('nonlocal prep','global prep'),scope)
   value=scope['adaptive_prepare'](-2,1)
  self.assertEqual(labels,['seed-1-deal-0','seed-1-deal-1'])
  self.assertEqual(value['ability_actor_names'],{});self.assertEqual(value['ability_target_choices'],{})
  self.assertEqual(value['initialization_only']['rndSeed'],-2)
 def test_adaptive_errors_do_not_read_targeted_test_constraints(self):
  tree=ast.parse((ROOT/'device/device_playback.py').read_text(encoding='utf-8'))
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.body[0],ast.Expr)
   and "'skill-target-result.json'" in ast.unparse(n.body[0]) and "error=str(error)" in ast.unparse(n.body[0]))
  self.assertIn('not adaptive_test',ast.unparse(node.test))

if __name__=='__main__':unittest.main()
