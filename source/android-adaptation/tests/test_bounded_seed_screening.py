"""Native-call counts, deferred coverage, and scoped receipt reuse."""
import copy,itertools,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'device'),str(ROOT.parent/'windows-adaptation/project/official-web-replay')]
from skill_candidate_pool import Pool,EmptyPool,PoolScopeChanged
from test_skill_candidate_pool import SOURCE

def preparation(seed=55,n=4):
    return dict(initialization_only={'rndSeed':seed},participants={'team':{'native_owner':0}},
        events=[dict(kind='activate_ability',source_side='team',source_tick_20hz=20*(i+1)) for i in range(n)])
def report(candidate,value=100,valid=True):
    events=candidate['events'];count=len(events)
    if not valid:return dict(error=114,finished=0,native_accepted=1,tick=25)
    return dict(error=0,finished=1,tick=200,executed=count,native_accepted=count,value=value,
        commands=[dict(ct=189,c={'t':e['source_tick_20hz'],'t2':e['source_tick_20hz']}) for e in events],
        dispatch=[dict(index=i,kind=189,tick=e['source_tick_20hz'],flags=3,code=0) for i,e in enumerate(events)],
        diagnostics=[dict(index=i,tick=e['source_tick_20hz'],owner=0,card=0,actor={'cost':1}) for i,e in enumerate(events)],
        ability_observations=[dict(phase='selected',event_index=i,selected_ordinal=0,actors=[dict(name=candidate['ability_actor_names'][str(i)])]) for i in range(count)]
            +[dict(phase='available',event_index=i,actors=[dict(name=n,cost=1) for n in ('GoldenKnight','BossBandit')]) for i in range(count)],
        elixir=[dict(leaked=v,spent=count*10000) for v in (15028,9579)])

class BoundedScreenTests(unittest.TestCase):
    def setUp(self):
        self.pool=Pool(SOURCE,lambda s,c,r:('same_towers',r['value']));self.prep=preparation();self.calls=[];self.scope={'generation':1}
        for bits in itertools.product(('GoldenKnight','BossBandit'),repeat=4):
            plan=dict(zip(map(str,range(4)),bits));self.pool.entries.append(dict(actors=plan,costs={str(i):1 for i in range(4)},origin_cost=100,origin_tier='same_towers'))
        self.pool.entries[5]['origin_cost']=1;self.best=self.pool.entries[5]['actors']
    def execute(self,c,i):
        self.calls.append(copy.deepcopy(c));return report(c),{'attempt':'native-'+str(len(self.calls))}
    def evaluate(self,execute=None,**options):
        return self.pool.evaluate(self.prep,execute or self.execute,scope=self.scope,verify_reuse=lambda rows:True,**options)
    def test_sixteen_plan_pool_screens_only_two(self):
        _,_,r=self.evaluate();self.assertEqual(len(self.calls),2);self.assertEqual(r['deferred_pool_candidates'],14);self.assertEqual(len(self.pool.entries),16)
    def test_best_origin_plan_is_first(self):
        self.evaluate();self.assertEqual(self.calls[0]['ability_actor_names'],self.best)
    def test_second_representative_covers_maximum_different_skills(self):
        self.evaluate();self.assertEqual(sum(self.calls[0]['ability_actor_names'][i]!=self.calls[1]['ability_actor_names'][i] for i in self.best),4)
    def test_repeated_screen_uses_only_verified_saved_receipts(self):
        self.evaluate();_,_,r=self.evaluate();self.assertEqual(len(self.calls),2);self.assertEqual(r['alns_allocation']['reused_candidates'],2)
    def test_each_refinement_adds_only_one_new_plan(self):
        self.evaluate()
        for expected in (3,4,5):
            _,_,r=self.evaluate(alns_budget=1);self.assertEqual(len(self.calls),expected);self.assertEqual(r['alns_allocation']['used'],1)
        self.assertEqual(len({tuple(sorted(c['ability_actor_names'].items())) for c in self.calls}),5)
    def test_global_budget_covers_deferred_pool_candidates(self):
        self.pool.alns_total_budget=2;self.evaluate()
        for _ in range(4):self.evaluate(alns_budget=1)
        self.assertEqual(len(self.calls),4);self.assertEqual(self.pool.refinement_used,2);self.assertEqual(self.pool.snapshot()['alns_remaining_budget'],0)
    def test_global_budget_shared_between_different_seeds(self):
        self.pool.alns_total_budget=2
        for seed in (55,56,57):
            self.prep=preparation(seed);self.evaluate();self.evaluate(alns_budget=1)
        self.assertEqual(len(self.calls),8);self.assertEqual(self.pool.refinement_used,2)
    def test_worse_refinement_never_overwrites_verified_best(self):
        self.evaluate();_,r,_=self.evaluate(lambda c,i:(report(c,999),{'attempt':'worse'}),alns_budget=1);self.assertEqual(r['value'],100);self.assertEqual(self.pool.elite['key'][0],100)
    def test_two_failed_representatives_do_not_mean_seed_exhausted(self):
        def bad(c,i):self.calls.append(c);return report(c,valid=False),{'attempt':str(i)}
        with self.assertRaises(EmptyPool) as raised:self.evaluate(bad)
        detail=raised.exception.search_report;self.assertEqual(len(self.calls),2);self.assertEqual(detail['deferred_pool_candidates'],14);self.assertTrue(detail['alns_allocation']['can_continue']);self.assertFalse(detail['explored_branches_exhausted'])
        self.evaluate(alns_budget=1);self.assertEqual(len(self.calls),3)
    def test_changed_process_scope_refuses_without_new_simulation(self):
        self.evaluate();self.scope={'generation':2}
        with self.assertRaises(PoolScopeChanged):self.evaluate(alns_budget=1)
        self.assertEqual(len(self.calls),2)
    def test_failed_clean_release_verification_refuses_cached_result(self):
        self.evaluate()
        with self.assertRaises(PoolScopeChanged):self.pool.evaluate(self.prep,self.execute,scope=self.scope,verify_reuse=lambda rows:False,alns_budget=1)
        self.assertEqual(len(self.calls),2)
    def test_missing_reuse_guard_never_reissues_same_input(self):
        self.evaluate()
        with self.assertRaises(PoolScopeChanged):self.pool.evaluate(self.prep,self.execute,alns_budget=1)
        self.assertEqual(len(self.calls),2)
    def test_interrupted_native_attempt_is_preserved_not_retried(self):
        def failed(c,i):self.calls.append(c);raise RuntimeError('native attempt retained')
        with self.assertRaisesRegex(RuntimeError,'retained'):self.evaluate(failed)
        with self.assertRaisesRegex(RuntimeError,'retained'):self.evaluate()
        self.assertEqual(len(self.calls),1)
    def test_stop_with_existing_best_submits_no_next_plan(self):
        self.evaluate();self.evaluate(alns_budget=1,stop_early=lambda:True);self.assertEqual(len(self.calls),2)
    def test_cancel_before_reuse_or_execution(self):
        with self.assertRaisesRegex(RuntimeError,'取消'):self.evaluate(cancelled=lambda:True)
        self.assertEqual(self.calls,[])
    def test_partial_plan_cannot_become_playable_best(self):
        self.evaluate()
        def bad(c,i):self.calls.append(c);return report(c,valid=False),{'attempt':'partial'}
        _,r,_=self.evaluate(bad,alns_budget=1);self.assertEqual(r['finished'],1);self.assertEqual(self.pool.elite['key'][0],100)
    def test_large_pool_reaches_mutations_before_all_deferred_candidates(self):
        self.evaluate()
        for _ in range(5):self.evaluate(alns_budget=1)
        kinds=[row['kind'] for row in self.pool.refinement_history]
        self.assertIn('same-cost-mutation',kinds);self.assertGreater(self.pool.snapshot()['seed_progress'][0]['deferred_pool_candidates'],0);self.assertEqual(self.pool.refinement_used,5);self.assertEqual(len(self.calls),7)
    def test_exact_first_representative_stops_second_and_refinement(self):
        self.pool.compare=lambda s,c,r:('exact',0);self.evaluate(alns_budget=1);self.assertEqual(len(self.calls),1);self.assertEqual(self.pool.refinement_used,0)
    def test_prepare_change_starts_fresh_results_instead_of_reusing_other_deal(self):
        self.evaluate();self.prep['deck_version']='different';self.evaluate();self.assertEqual(len(self.calls),4)
    def test_remaining_candidates_are_reported_without_false_exhaustion(self):
        self.evaluate();snap=self.pool.snapshot();self.assertEqual(snap['seed_progress'][0]['tested'],2);self.assertEqual(snap['seed_progress'][0]['deferred_pool_candidates'],14);self.assertFalse(snap['same_cost_alns']['exhaustive'])

class RealSixteenPlanFixtureTests(unittest.TestCase):
    def test_current_replay_first_pass_is_two_and_continuations_are_one(self):
        folder=Path.cwd()/'work/seed-screen-limit/real-fixture'
        if not (folder/'reports.json').exists():self.skipTest('Local completed-replay fixture unavailable')
        import replay_matching
        pool=Pool(json.loads((folder/'source.json').read_text(encoding='utf-8')),replay_matching.page_comparison)
        pool.entries=json.loads((folder/'pool.json').read_text(encoding='utf-8'))['entries'];prep=json.loads((folder/'preparation.json').read_text(encoding='utf-8'))
        records=json.loads((folder/'reports.json').read_text(encoding='utf-8'));lookup={tuple(sorted(r['actors'].items())):r for r in records};calls=[];best=None
        def execute(c,i):
            signature=tuple(sorted(c['ability_actor_names'].items()));calls.append(signature);r=lookup[signature];return copy.deepcopy(r['report']),copy.deepcopy(r['evidence'])
        for step in range(3):
            try:
                _,r,result=pool.evaluate(prep,execute,scope={'fixture':'captured-dev52'},verify_reuse=lambda rows:True,alns_budget=0 if step==0 else 1)
                cost=replay_matching.page_comparison(pool.source,prep,r)[1]
                if best is not None:self.assertLessEqual(cost,best)
                best=cost
            except EmptyPool:pass
            self.assertEqual(len(calls),2+step)
        self.assertEqual(len(set(calls)),4);self.assertEqual(pool.refinement_used,2)

class RoundReceiptNamesTests(unittest.TestCase):
    def test_all_actual_bounded_seed_and_round_names_are_recognized(self):
        from mumu_ownership import ATTEMPT
        for seed in range(61):
            for turn in range(24):self.assertIsNotNone(ATTEMPT.fullmatch('seed-'+str(seed)+'-r'+str(turn)+'-candidate-2'))
        self.assertIsNotNone(ATTEMPT.fullmatch('seed-60-deal-11'));self.assertIsNotNone(ATTEMPT.fullmatch('seed-3-r-candidate-5'))
    def test_out_of_bound_foreign_or_path_names_remain_rejected(self):
        from mumu_ownership import ATTEMPT
        for value in ('seed-61-r0-candidate-2','seed-0-r24-candidate-2','seed-0-r-1-candidate-2','seed-0-r0-candidate-1000','../seed-0-r0-candidate-2','seed-0-r0-candidate-2.extra','seed-0-deal-12'):
            self.assertIsNone(ATTEMPT.fullmatch(value),value)
