"""Coverage, constraints and bounded resume tests. No device/native mutations."""
import copy
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'official-web-replay'))
import ability_search as ability


class CoverageSearchTests(unittest.TestCase):
    def setUp(self):
        self.completed=patch.object(ability,'source_completed',lambda r,n:r.get('done') is True)
        self.failed=patch.object(ability,'source_failure',lambda r:'fixture failure')
        self.completed.start();self.failed.start()
        self.addCleanup(self.completed.stop);self.addCleanup(self.failed.stop)
        self.calls=[];self.leaves=[]

    def prep(self,n=3,seed=1):
        return dict(initialization_only=dict(rndSeed=seed),events=[dict(kind='activate_ability',tick=20*i,raw='unchanged') for i in range(n)])

    def tree(self,n=3,score=lambda bits:100,blocked=lambda bits:False):
        def execute(c,index):
            self.calls.append((index,copy.deepcopy(c)))
            choices=c['ability_target_choices']
            for i in range(n):
                if str(i) not in choices:
                    return dict(error=112,native_code=2,event_index=i),dict(attempt='a'+str(index))
            bits=tuple(choices[str(i)] for i in range(n));self.leaves.append(bits)
            return dict(done=True,score=ability.ELIXIR_MISMATCH_COST if blocked(bits) else score(bits)),dict(attempt='a'+str(index))
        return execute

    def run_search(self,prep,execute,**kwargs):
        return ability.search(prep,execute,lambda c,r:False,strategy='coverage',closest=lambda c,r:r['score'],**kwargs)

    def test_small_tree_exhausts_all_combinations_despite_long_plateau(self):
        _,r,result=self.run_search(self.prep(),self.tree(score=lambda b:1 if b==(1,1,1) else 100),max_attempts=32,patience=1,incumbent=0)
        self.assertEqual(r['score'],1)
        self.assertEqual(set(self.leaves),set(itertools.product(range(2),repeat=3)))
        self.assertEqual(len(self.calls),15);self.assertTrue(result['explored_branches_exhausted'])
        self.assertFalse(result['plateau_stopping']);self.assertFalse(result['unique_solution_proven'])

    def test_large_tree_resumes_without_reexecuting_visited_nodes(self):
        state={};execute=self.tree(n=5);prep=self.prep(5)
        for _ in range(20):
            try:self.run_search(prep,execute,state=state,max_attempts=4)
            except RuntimeError as error:self.assertGreater(error.search_report['remaining'],0)
            if not state['frontier']:break
        self.assertEqual(len(self.calls),63);self.assertEqual(len(self.leaves),32)
        self.assertEqual([i for i,_ in self.calls],list(range(63)))
        self.assertEqual(len({tuple(sorted(c['ability_target_choices'].items())) for _,c in self.calls}),63)

    def test_coverage_visits_different_early_choices_before_polishing_one_subtree(self):
        self.run_search(self.prep(5),self.tree(n=5),max_attempts=14)
        self.assertIn(0,{b[0] for b in self.leaves});self.assertIn(1,{b[0] for b in self.leaves})
        self.assertLess(len(self.leaves),32)

    def test_late_combination_improves_after_entire_slice_without_improvement(self):
        state={};execute=self.tree(n=4,score=lambda b:1 if b==(1,1,1,1) else 100)
        _,first,_=self.run_search(self.prep(4),execute,state=state,max_attempts=8)
        self.assertEqual(first['score'],100)
        _,last,result=self.run_search(self.prep(4),execute,state=state,max_attempts=32)
        self.assertEqual(last['score'],1);self.assertTrue(result['exhaustive'])

    def test_bad_later_candidates_never_replace_best(self):
        state={};execute=self.tree(score=lambda b:1 if b==(0,0,0) else 999)
        _,first,_=self.run_search(self.prep(),execute,state=state,max_attempts=4)
        _,last,_=self.run_search(self.prep(),execute,state=state,max_attempts=32)
        self.assertEqual(first['score'],1);self.assertEqual(last['score'],1)

    def test_actual_elixir_rejection_cannot_be_overridden_by_exact_predicate(self):
        c,r,result=ability.search(self.prep(1),self.tree(n=1,score=lambda b:50,blocked=lambda b:b==(0,)),
            lambda c,r:True,strategy='coverage',closest=lambda c,r:r['score'])
        self.assertEqual(c['ability_target_choices'],{'0':1});self.assertEqual(r['score'],50)
        self.assertTrue(result['attempts'][1]['elixir_rejected'])

    def test_proven_elixir_impossible_branch_prunes_but_hp_score_does_not(self):
        bound=lambda c,r:(ability.ELIXIR_MISMATCH_COST if c['ability_target_choices'].get('0')==0 else 999999,{})
        self.run_search(self.prep(),self.tree(),bound=bound,max_attempts=32)
        self.assertTrue(all(b[0]==1 for b in self.leaves));self.assertEqual(len(self.leaves),4)

    def test_old_ordinal_with_one_eligible_target_is_repaired_not_frozen(self):
        def execute(c,index):
            self.calls.append(copy.deepcopy(c['ability_target_choices']))
            if c['ability_target_choices'].get('0')!=0:return dict(error=112,native_code=1,event_index=0),{}
            return dict(done=True,score=10),{}
        c,_,_=self.run_search(self.prep(1),execute,initial={'0':7},max_attempts=8)
        self.assertEqual(c['ability_target_choices'],{'0':0});self.assertNotIn({'0':7},self.calls[1:])

    def test_different_seed_clears_state_and_never_reuses_report(self):
        state={};execute=self.tree(n=1)
        self.run_search(self.prep(1,1),execute,state=state)
        self.run_search(self.prep(1,2),execute,state=state)
        self.assertEqual([i for i,_ in self.calls],[0,1,2,0,1,2])
        self.assertEqual(state['best'][1]['initialization_only']['rndSeed'],2)

    def test_original_events_and_fields_are_preserved(self):
        prep=self.prep();original=copy.deepcopy(prep)
        self.run_search(prep,self.tree(),max_attempts=32)
        self.assertEqual(prep,original)
        self.assertTrue(all(c['events']==original['events'] for _,c in self.calls))

    def test_budget_without_completed_run_keeps_frontier_and_reports_incomplete(self):
        with self.assertRaises(RuntimeError) as error:self.run_search(self.prep(6),self.tree(n=6),max_attempts=2)
        report=error.exception.search_report
        self.assertEqual(report['slice_attempts'],2);self.assertGreater(report['remaining'],0)
        self.assertFalse(report['exhaustive']);self.assertFalse(report['explored_branches_exhausted'])

    def test_user_stop_and_cancel_are_checked_before_next_execution(self):
        state={};execute=self.tree(n=1)
        _,_,report=self.run_search(self.prep(1),execute,state=state,stop_early=lambda:len(self.calls)>=2)
        self.assertTrue(report['stopped_by_user']);self.assertEqual(len(self.calls),2)
        with self.assertRaisesRegex(RuntimeError,'取消'):
            self.run_search(self.prep(1),execute,state=state,cancelled=lambda:True)
        self.assertEqual(len(self.calls),2)

    def test_retained_native_failure_is_not_swallowed_or_retried(self):
        def execute(c,index):self.calls.append(index);raise RuntimeError('native attempt retained')
        with self.assertRaisesRegex(RuntimeError,'retained'):self.run_search(self.prep(),execute)
        self.assertEqual(self.calls,[0])

    def test_exact_match_stops_without_claiming_full_coverage(self):
        _,_,r=ability.search(self.prep(),self.tree(),lambda c,r:True,
            strategy='coverage',closest=lambda c,r:r['score'])
        self.assertTrue(r['final_hp_matched']);self.assertFalse(r['exhaustive']);self.assertGreater(r['remaining'],0)

    def test_invalid_budget_strategy_and_missing_rank_refuse(self):
        for value in (0,-1,True,4097):
            with self.assertRaises(ValueError):self.run_search(self.prep(),self.tree(),max_attempts=value)
        with self.assertRaises(ValueError):ability.search(self.prep(),self.tree(),lambda c,r:False,strategy='unknown')
        with self.assertRaises(ValueError):ability.search(self.prep(),self.tree(),lambda c,r:False,strategy='coverage')
