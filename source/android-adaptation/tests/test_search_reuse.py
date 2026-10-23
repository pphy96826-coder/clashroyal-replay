"""Equivalence and refusal tests; no device or game calls."""
import copy
import ast
import hashlib
import itertools
from pathlib import Path
import sys
import struct
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'windows-adaptation/project/official-web-replay'))
from ability_search import CandidateMemo,search
import align_native_deal as deal
from prepare_native_replay import cycle_slots,NOT_IN_OPENING


class CandidateReuseTests(unittest.TestCase):
    def setUp(self):
        self.memo=CandidateMemo();self.calls=[];self.checks=[];self.scope={'pid':1,'start':7,'resource_generation':12}
        self.candidate={'initialization_only':{'rndSeed':2},'events':[{'kind':'activate_ability'}],
                        'ability_target_choices':{}}

    def execute(self,candidate,number):
        self.calls.append(copy.deepcopy(candidate))
        return {'error':112,'event_index':0,'native_code':2}, {'attempt':'native-'+str(len(self.calls))}

    def run_candidate(self,candidate=None,scope=None,cacheable=True,verify=None):
        return self.memo.run(candidate or self.candidate,0,self.execute,scope=self.scope if scope is None else scope,
            verify=verify or (lambda:self.checks.append('verified')),cacheable=lambda *args:cacheable)

    def test_identical_inputs_reuse_evidence_not_a_new_submission(self):
        first=self.run_candidate();second=self.run_candidate()
        self.assertEqual(first,tuple(second));self.assertEqual(len(self.calls),1);self.assertEqual(self.checks,['verified'])
        self.assertEqual(self.memo.stats()['reused_candidates'],1)

    def test_results_and_inputs_cannot_mutate_the_retained_copy(self):
        result,evidence=self.run_candidate();result['error']=999;evidence['attempt']='wrong'
        again=self.run_candidate();again[0]['error']=999
        self.assertEqual(self.run_candidate()[0]['error'],112)
        self.assertEqual(self.run_candidate()[1]['attempt'],'native-1')

    def test_every_input_field_including_seed_choices_and_full_stream_is_bound(self):
        self.run_candidate()
        for key,value in [('initialization_only',{'rndSeed':3}),('ability_target_choices',{'0':1}),
                          ('events',[{'kind':'activate_ability','tick':99}]),('native_initial_tower_hp',[100])]:
            candidate=copy.deepcopy(self.candidate);candidate[key]=value
            self.run_candidate(candidate)
        self.assertEqual(len(self.calls),5)

    def test_changed_process_or_resource_scope_invalidates_all_entries(self):
        self.run_candidate()
        for key in self.scope:
            scope=dict(self.scope);scope[key]+=1
            self.run_candidate(scope=scope)
        self.assertEqual(len(self.calls),4);self.assertEqual(self.memo.stats()['retained_candidates'],1)

    def test_cached_verification_refusal_does_not_rerun_or_fall_back(self):
        self.run_candidate()
        def refuse():raise RuntimeError('generation changed')
        with self.assertRaisesRegex(RuntimeError,'generation changed'):self.run_candidate(verify=refuse)
        self.assertEqual(len(self.calls),1)

    def test_unclean_and_other_failed_reports_are_never_reused(self):
        self.run_candidate(cacheable=False);self.run_candidate(cacheable=False)
        self.assertEqual(len(self.calls),2)
        for error in (114,70,None):
            memo=CandidateMemo();calls=[]
            def failed(candidate,index):calls.append(1);return {'error':error}, {'attempt':'failed'}
            for _ in range(2):memo.run(self.candidate,0,failed,scope={},verify=lambda:None,cacheable=lambda *args:True)
            self.assertEqual(len(calls),2)

    def test_exceptions_are_not_cached(self):
        calls=[]
        def failed(candidate,index):calls.append(1);raise RuntimeError('native attempt retained')
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'retained'):
                self.memo.run({},0,failed,scope={},verify=lambda:None,cacheable=lambda *args:True)
        self.assertEqual(len(calls),2);self.assertEqual(self.memo.stats()['retained_candidates'],0)

    def test_memory_and_entry_limits(self):
        memo=CandidateMemo(max_entries=1,max_bytes=1000)
        for i in range(3):memo.run({'seed':i},0,self.execute,scope={},verify=lambda:None,cacheable=lambda *args:True)
        self.assertEqual(memo.stats()['retained_candidates'],1)
        memo=CandidateMemo(max_bytes=1)
        memo.run({},0,self.execute,scope={},verify=lambda:None,cacheable=lambda *args:True)
        self.assertEqual(memo.stats()['retained_candidates'],0)

    def test_screen_and_refine_keep_identical_branch_and_save_two_native_runs(self):
        def run(use_cache):
            calls=[];memo=CandidateMemo()
            def execute(candidate,index):
                choices=candidate['ability_target_choices'];calls.append(dict(choices))
                if not choices:return dict(error=112,native_code=2,event_index=0),dict(attempt=len(calls))
                return dict(error=0,complete=True,value=choices['0']),dict(attempt=len(calls))
            def wrapped(candidate,index):
                return memo.run(candidate,index,execute,scope={'pid':1},verify=lambda:None,cacheable=lambda *args:True) if use_cache else execute(candidate,index)
            with patch('ability_search.source_completed',lambda report,count:report.get('complete',False)):
                first=search(self.candidate,wrapped,lambda c,r:r.get('value')==1,max_attempts=2,closest=lambda c,r:10)
                second=search(self.candidate,wrapped,lambda c,r:r.get('value')==1,max_attempts=4,initial=first[0]['ability_target_choices'],closest=lambda c,r:10)
            return second,calls,memo
        cold,cold_calls,_=run(False);warm,warm_calls,memo=run(True)
        self.assertEqual(cold[0],warm[0]);self.assertEqual(cold[1],warm[1])
        self.assertEqual(len(cold_calls),5);self.assertEqual(len(warm_calls),3)
        self.assertEqual(memo.stats()['reused_candidates'],2)
        self.assertTrue(warm[2]['final_hp_matched'])

    def test_device_uses_released_receipts_and_fresh_identity_only(self):
        text=(ROOT/'android-adaptation/device/device_playback.py').read_text()
        block=text[text.index('                def run_seed('):text.index('                def consider(')]
        for guard in ("receipt.get('detached') is True","receipt.get('source_bootstrap_verified') is True",
                      "receipt.get('component_unloaded') is True",'candidate_scope(identity)==before','verify=verify_reuse'):
            self.assertIn(guard,block)


class CandidateScopeTests(unittest.TestCase):
    def scope(self, *, missing=False, changing=False, restart=False):
        source=(ROOT/'android-adaptation/device/device_playback.py').read_text()
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='candidate_scope')
        class ProcPath:
            def __init__(self,*args):pass
            def __truediv__(self,part):return self
            def read_text(self):return 'thread-start'
        class Session:
            base=0x10000
            def __init__(self,identity):self.round=0
            def raw_pointer(self,address):
                if address==self.base+0x1d34ae0:
                    self.round+=1
                    return 0 if missing else 10
                return {10+0x20:20,self.base+0x1d88820:40,20+0x38:31 if changing and self.round==2 else 30}[address]
            def read(self,address,size):return struct.pack('<i',9)
            def verify(self):
                if restart:raise ValueError('process changed')
        ns=dict(ReadOnlySession=Session,Path=ProcPath,struct=struct,start_time=lambda raw:raw,copy=copy,hashlib=hashlib)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'scope-test','exec'),ns)
        return ns['candidate_scope']({'pid':123,'process_start_time':'first'})

    def test_generation_label_is_repeatable_without_exposing_handles(self):
        self.assertEqual(self.scope(),self.scope())
        self.assertEqual(len(self.scope()['resource_generation']),64)
        self.assertNotIn('worker',self.scope())

    def test_absent_resource_owner_is_refused(self):
        with self.assertRaisesRegex(ValueError,'owner absent'):self.scope(missing=True)

    def test_changed_resource_generation_is_refused(self):
        with self.assertRaisesRegex(ValueError,'generation changed'):self.scope(changing=True)

    def test_changed_process_is_refused(self):
        with self.assertRaisesRegex(ValueError,'process changed'):self.scope(restart=True)


def exhaustive(entries,actual,plays,desired,seen,owner):
    """The previous implementation, as an independent equivalence oracle."""
    physical=[c['d'] for c in entries];draws=deal.engine_draws(physical,actual)
    by_id={c['d']:c for c in entries}
    held_slots={k for k,c in enumerate(actual) if c in NOT_IN_OPENING}
    tried={tuple(previous[owner]) for previous in seen}|{tuple(physical)};candidates=[]
    for order in itertools.permutations(actual):
        if {k for k,c in enumerate(order) if c in NOT_IN_OPENING}!=held_slots:continue
        slots=cycle_slots(list(order[:4]),list(order[4:]),plays)
        if slots is None:continue
        deck=deal.deck_order_for(list(order),draws)
        if deck is None or tuple(deck) in tried:continue
        score=(sum(a!=b for a,b in zip(order,desired)),sum(a!=b for a,b in zip(order,actual)))
        candidates.append((score,list(order),deck,slots))
    if not candidates:raise ValueError(deal.DEAL_SEED_INFEASIBLE)
    _,chosen,deck,slots=min(candidates,key=lambda c:c[0])
    return [by_id[c] for c in deck],chosen,slots


class LegalDealReuseTests(unittest.TestCase):
    def setUp(self):deal._legal_held_deals.cache_clear()

    def test_same_selection_as_exhaustive_for_all_four_set_aside_positions(self):
        collector=27000007
        for held_draw in range(4):
            physical=[1,2,3,4,5,6,collector,7];entries=[dict(d=c,l=11) for c in physical]
            draws=[2,0,1,0,held_draw,0,0,0];actual=deal.engine_deal(physical,draws)
            for plays in ([1,2,3,4,5,6,7,collector],[2,1,4,3,collector,5,6,7],[1,collector,2,3,4]):
                args=(entries,actual,plays,physical,[],0)
                try:expected=exhaustive(*args)
                except ValueError:
                    with self.assertRaisesRegex(ValueError,deal.DEAL_SEED_INFEASIBLE):
                        deal.calibrate_held(entries,actual,None,plays,physical,[],0)
                else:self.assertEqual(deal.calibrate_held(entries,actual,None,plays,physical,[],0),expected)

    def test_seen_decks_and_card_metadata_are_never_cached(self):
        cards=[1,2,3,4,5,6,27000007,7];entries=[dict(d=c,l=11) for c in cards]
        draws=[2,0,1,0,3,0,0,0];actual=deal.engine_deal(cards,draws);plays=[1,2,3,4,27000007]
        first=deal.calibrate_held(entries,actual,None,plays,cards,[],0)
        seen=[(tuple(c['d'] for c in first[0]),())]
        changed=[dict(c,l=9) for c in entries]
        self.assertEqual(deal.calibrate_held(changed,actual,None,plays,cards,seen,0),exhaustive(changed,actual,plays,cards,seen,0))
        self.assertEqual(deal._legal_held_deals.cache_info().hits,1)

    def test_collector_and_mirror_together_preserve_exhaustive_choice(self):
        cards=[1,2,3,4,5,6,27000007,28000006];entries=[dict(d=c,l=11) for c in cards]
        for draws in ([0,1,1,1,3,2,0,0],[2,0,1,0,1,0,1,0],[4,0,0,0,3,0,1,0]):
            actual=deal.engine_deal(cards,draws)
            for plays in ([1,2,3,4,5,6,27000007,28000006],[1,27000007,2,28000006,3,4]):
                try:expected=exhaustive(entries,actual,plays,cards,[],0)
                except ValueError:
                    with self.assertRaisesRegex(ValueError,deal.DEAL_SEED_INFEASIBLE):
                        deal.calibrate_held(entries,actual,None,plays,cards,[],0)
                else:self.assertEqual(deal.calibrate_held(entries,actual,None,plays,cards,[],0),expected)

    def test_deal_cache_binds_full_stream_and_has_a_hard_limit(self):
        cards=tuple(sorted([1,2,3,4,5,6,27000007,7]))
        result=deal._legal_held_deals(cards,(1,2,3,4,27000007),(4,))
        self.assertIsInstance(result,tuple)
        self.assertTrue(all(isinstance(order,tuple) and isinstance(slots,tuple) for order,slots in result))
        for count in range(10):deal._legal_held_deals(cards,tuple([1]*count),(4,))
        self.assertLessEqual(deal._legal_held_deals.cache_info().currsize,8)


if __name__=='__main__':unittest.main()
