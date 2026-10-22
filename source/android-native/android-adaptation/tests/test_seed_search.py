from pathlib import Path
import ast
import hashlib
import copy
import tempfile
import textwrap
import unittest

ROOT=Path(__file__).resolve().parents[1]
import sys as _sys
_sys.path.insert(0,str(ROOT.parent/'official-web-replay'))  # shared final_tower_rows
SOURCE=(ROOT/'device/device_playback.py').read_text()


def load(name):
    tree=ast.parse(SOURCE)
    names={name,'page_tower_comparison'} if name=='page_comparison' else {name}
    nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names)
           or (isinstance(n,ast.Assign) and any(getattr(t,'id','')=='SEED_ATTEMPTS' for t in n.targets))]
    nodes+=[n for n in tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','')=='PAGE_MATCH_TIERS' for t in n.targets)]
    scope=dict(hashlib=hashlib)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'seed','exec'),scope)
    return scope[name]


class SeedSearchTests(unittest.TestCase):
    def test_plan_is_bounded_reproducible_int32_and_skips_original(self):
        plan=load('seed_plan')
        first=plan('a'*64,1784463263);second=plan('a'*64,1784463263)
        self.assertEqual(first,second)
        self.assertEqual(len(first),60);self.assertEqual(len(set(first)),60)
        self.assertNotIn(1784463263,first)
        self.assertTrue(all(-2**31<=s<2**31 for s in first))
        self.assertNotEqual(first,plan('b'*64,1784463263))
        self.assertNotIn(first[0],plan('a'*64,first[0]))

    def test_page_is_always_compared_and_closest_run_is_kept(self):
        block=SOURCE[SOURCE.index('# Always compare the simulated end with the page'):SOURCE.index("receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']")]
        self.assertIn('tier,difference=page_comparison(read(source),aligned,execution)',block)
        self.assertIn("if seed_policy['search_needed']:",block)
        # Each seed gets its own deal calibration before any source command runs.
        self.assertLess(block.index("trial['initialization_only']['rndSeed']=seed"),block.index('trial=calibrate(trial,probe(name),trial_seen)'))
        self.assertLess(block.index('trial=calibrate(trial,probe(name),trial_seen)'),block.index('return search(trial,execute_candidate'))
        # Screening predicts the deal from ONE probe; a deal mismatch recalibrates normally.
        self.assertIn("if trial['native_deal_ready'] or optimistic:return trial",block)
        self.assertIn("if 'native deal mismatch' not in str(error):raise",block)
        self.assertIn("trial=calibrated(number,seed,False)",block)
        # Only fully executed runs compete; the original seed stays a candidate; an exact match stops the search.
        self.assertIn("best=(rank(tier,difference),original_seed",block)
        self.assertIn("if entry[0]<best[0]:best=entry",block)
        self.assertIn("if best[2]=='exact':break",block)
        self.assertIn("selected_candidate.clear();selected_candidate.update(chosen)",block)
        self.assertIn("raise Cancelled('cancelled during seed search')",block)
        tail=SOURCE[SOURCE.index("receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']"):]
        self.assertIn("context.update(final_hp_matched=hp_matched,page_match=tier,page_hp_difference=breakdown['hp_difference'],page_match_cost=difference",tail)
        self.assertIn("name=(attempt_prefix+'candidate-'+str(number)) if attempt_prefix else",SOURCE)

    def test_page_comparison_tiers(self):
        import sys,types
        def run(page,alive,destroyed=()):
            tower_profiles=types.ModuleType('tower_profiles')
            entries=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
            tower_profiles.bindings=lambda p:{0:dict(spawn_entries=entries),1:dict(spawn_entries=entries)}
            sys.modules['tower_profiles']=tower_profiles
            cmp=load('page_comparison')
            source=dict(decks=[dict(proposed_native_owner=o,oracle_final_hp=dict(zip(('king','princess0','princess1'),page[o]))) for o in (0,1)])
            xs=(9000,3500,14500);ids=(35000000,35000001,35000001)
            tw=[dict(owner=o,data_id=ids[i],x=xs[i],hp=hp) for o in (0,1) for i,hp in enumerate(alive[o]) if hp is not None]
            gone=[dict(owner=o,data_id=ids[i],x=xs[i],hp=0,native_destructor_observed=True) for o,i in destroyed]
            return cmp(source,{},dict(battle_state=dict(towers=tw,destroyed_towers=gone)))
        page={0:(2151,1630,0),1:(4824,2037,2146)}
        self.assertEqual(run(page,{0:(2151,1630,None),1:(4824,2037,2146)},[(0,2)]),('exact',0))
        self.assertEqual(run(page,{0:(2000,1600,None),1:(4824,2037,2146)},[(0,2)]),('same_towers',181))
        self.assertEqual(run(page,{0:(4824,None,2359),1:(4824,2144,2146)},[(0,1)])[0],'same_winner')
        self.assertEqual(run(page,{0:(4824,1467,2278),1:(4824,None,1717)},[(1,1)])[0],'different')
        # A destroyed princess never counts the king as destroyed.
        self.assertEqual(run(page,{0:(4824,1630,None),1:(4824,2037,2146)},[(0,2)]),('same_towers',2673))
        # A fallen king takes its princess towers with it.
        self.assertEqual(run({0:(0,0,0),1:(4824,2037,2146)},{0:(0,None,None),1:(4824,2037,2146)}),('exact',0))
        # Absent without destruction evidence is unknown, never a guessed match.
        self.assertEqual(run(page,{0:(2151,1630,None),1:(4824,2037,2146)}),('unknown',None))

    def test_end_time_outweighs_tower_hp(self):
        import sys,types
        tower_profiles=types.ModuleType('tower_profiles')
        entries=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
        tower_profiles.bindings=lambda p:{0:dict(spawn_entries=entries),1:dict(spawn_entries=entries)}
        sys.modules['tower_profiles']=tower_profiles
        cmp=load('page_comparison')
        page={0:(2151,1630,2000),1:(4824,2037,2146)}
        source=dict(source_duration_seconds=267,decks=[dict(proposed_native_owner=o,oracle_final_hp=dict(zip(('king','princess0','princess1'),page[o]))) for o in (0,1)])
        def run(offset,tick):
            xs=(9000,3500,14500);ids=(35000000,35000001,35000001)
            tw=[dict(owner=o,data_id=ids[i],x=xs[i],hp=hp-(offset if (o,i)==(0,0) else 0)) for o in (0,1) for i,hp in enumerate(page[o])]
            return cmp(source,{},dict(finished=1,tick=tick,battle_state=dict(towers=tw)))
        # Within the 1 s tolerance only tower HP counts; exact stays exact.
        self.assertEqual(run(0,267*20+8),('exact',0))
        self.assertEqual(run(0,267*20-20),('exact',0))
        # Same towers but the battle ends 2 s late: never exact, each extra tick costs 100 HP.
        self.assertEqual(run(0,267*20+40),('same_towers',2000))
        # 946 HP off but on time beats 1016 HP off and 2.3 s late.
        self.assertLess(run(946,267*20+4)[1],run(1016,267*20+46)[1])
        self.assertLess(run(1500,267*20)[1],run(0,267*20+40)[1])
        # Unknown page duration or unfinished battle: HP only, as before.
        self.assertEqual(cmp(dict(source,source_duration_seconds=None),{},dict(finished=1,tick=9999,battle_state=dict(towers=[]))),('unknown',None))
        from ability_search import terminal_time,terminal_hp_matches
        self.assertEqual(terminal_time(source,dict(finished=0,tick=5000))['excess_ticks'],None)
        self.assertEqual(terminal_time(source,dict(finished=1,tick=267*20+46))['excess_ticks'],26)
        # The ability search's exact stop also requires the end time.
        xs=(9000,3500,14500);ids=(35000000,35000001,35000001)
        towers=[dict(owner=o,data_id=ids[i],x=xs[i],hp=hp) for o in (0,1) for i,hp in enumerate(page[o])]
        self.assertTrue(terminal_hp_matches(source,{},dict(finished=1,tick=267*20+10,battle_state=dict(towers=towers))))
        self.assertFalse(terminal_hp_matches(source,{},dict(finished=1,tick=267*20+46,battle_state=dict(towers=towers))))

    def test_ready_message_never_claims_a_match_that_was_not_found(self):
        ready=SOURCE[SOURCE.index("if diagnostic is not None:ready_message="):SOURCE.index("status('ready_to_open',ready_message)")]
        self.assertIn("elif context.get('page_match')=='same_towers':ready_message=",ready)
        self.assertIn("elif not context.get('final_hp_matched'):ready_message='全部指令已执行，但终局与网页不符",ready)
        actions=(ROOT/'app/src/local/royale/replay/android/ConsoleActions.java').read_text()
        self.assertIn('return state.optString("page_match",state.optBoolean("final_hp_matched",true)?"exact":"different");',actions)
        status=(ROOT/'app/src/local/royale/replay/android/PlaybackStatus.java').read_text()
        self.assertIn('"⚠ 终局与网页不符 · 准备前台加载"',status)


class SeedPolicyTests(unittest.TestCase):
    def source(self, *decks):
        return dict(decks=[dict(cards=[dict(base_card_key=key) for key in deck]) for deck in decks])

    def test_only_allowlisted_cards_in_either_deck_enable_search(self):
        policy=load('seed_search_policy')
        for key in ('skeleton-king','hunter','hunter-ev1'):
            for source in (self.source([key],[]),self.source([],[key])):
                result=policy(source,'different')
                self.assertTrue(result['allowed']);self.assertTrue(result['search_needed'])
                self.assertIsNone(result['skip_reason'])
        self.assertEqual(policy(self.source(['hunter'],['skeleton-king']),'same_towers')['eligible_cards'],['hunter','skeleton-king'])

    def test_no_other_king_hero_tower_or_graveyard_is_eligible(self):
        source=self.source(['king','king-tower','royal-chef','little-prince','golden-knight','goblinstein'],
                           ['archer-queen','graveyard','skeleton-army','skeleton-barrel','knight-hero','hunter-fake'])
        for tier in ('different','same_winner','same_towers'):
            policy=load('seed_search_policy')(source,tier)
            self.assertFalse(policy['allowed']);self.assertFalse(policy['search_needed'])
            self.assertEqual(policy['skip_reason'],'no_seed_sensitive_card')

    def test_normalized_source_key_fallback_and_exact_match_skip(self):
        source=dict(decks=[dict(cards=[dict(source_card_key='hunter-ev1')])])
        policy=load('seed_search_policy')(source,'exact')
        self.assertTrue(policy['allowed']);self.assertFalse(policy['search_needed'])
        self.assertEqual(policy['skip_reason'],'exact_match')
        self.assertEqual(policy['eligible_cards'],['hunter'])
        self.assertFalse(load('seed_search_policy')({},'different')['search_needed'])

    def run_gate(self, cards, tier='different', fail_abilities=False, seeds=(100,), differences=None):
        """Execute the real runner selection block with native calls replaced by counters."""
        start=SOURCE.index('            ability_error=None')
        end=SOURCE.index('            full=finalize(aligned,execution,receipt)',start)
        block=textwrap.dedent(SOURCE[start:end])
        source=self.source(cards,[])
        aligned=dict(initialization_only=dict(rndSeed=42),events=[dict(tick=20)])
        selected={};calls=dict(seeds=[],search=[],probe=[]);records={};self.search_options=[]
        def search(candidate,execute,match,*,cancelled,**options):
            calls['search'].append(candidate['initialization_only']['rndSeed'])
            self.search_options.append(options)
            if fail_abilities:
                error=RuntimeError('strict ability search exhausted')
                error.search_report=dict(explored_branches_exhausted=True)
                raise error
            selected.update(receipt='receipt',preparation='prep')
            chosen=dict(candidate,ability_target_choices={'3':1})
            return chosen,dict(seed=candidate['initialization_only']['rndSeed']),dict(inferred=False)
        def plan(key,original,remembered=None):calls['seeds'].append(original);self.remembered=getattr(self,'remembered',[])+[remembered];return ([remembered] if remembered else [])+list(seeds)
        def compare(source,candidate,report):
            if differences is not None:return ('same_towers',differences[report['seed']])
            return ('exact',0) if report['seed']==100 else (tier,0 if tier=='exact' else 123)
        def calibrate(candidate,deal,seen):candidate['native_deal_ready']=True;return candidate
        with tempfile.TemporaryDirectory() as directory:
            scope=dict(aligned=aligned,delayed=copy.deepcopy(aligned),source='source',read=lambda path:source,
                       seed_search_policy=load('seed_search_policy'),seed_search_note=load('seed_search_note'),
                       PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different','unknown'),SEED_ATTEMPTS=60,SCREEN_RUNS=1,SCREEN_RUNS_UNFIXED=12,REFINE_SEEDS=3,REFINE_RUNS=24,
                       rank=lambda t,d:(type(d) is int and d>=1000000,('exact','same_towers','same_winner','different','unknown').index(t),d if d is not None else 1<<30),
                       search=search,execute_candidate=None,terminal_hp_matches=lambda *args:True,page_comparison=compare,page_towers=lambda *args:[],
                       page_breakdown=lambda source,candidate,report:dict(hp_difference=compare(source,candidate,report)[1],time_difference_seconds=None,page_seconds=None,simulated_seconds=None,elixir_matched=None),
                       cost_text=lambda cost:'',elixir_gate=getattr(self,'elixir_gate_fn',lambda *args:getattr(self,'elixir_refusal',None)),elixir_consistent=dict(getattr(self,'elixir_consistent',{})),ELIXIR_MISMATCH_COST=1000000,
                       restore=lambda result:None,selected_candidate=selected,context={},
                       closest_abilities=load('seed_search_policy')(source,'different')['allowed'],hp_key='hp_key',hp_bound='hp_bound',
                       destination=Path(directory),preparation=Path(directory),request=dict(source_sha256='a'*64),
                       write_new=lambda path,value:records.update({path.name:copy.deepcopy(value)}),
                       seed_plan=plan,copy=copy,seed_stop=lambda:False,status=lambda *args,**kwargs:None,
                       replay_key=lambda source:'match-key',files=Path(directory),owner=Path(directory).stat(),os=__import__('os'),time=__import__('time'),json=__import__('json'),
                       calibrate=calibrate,deck_fingerprint=lambda candidate:(),
                       probe=lambda name:calls['probe'].append(name),Cancelled=type('Cancelled',(Exception,),{}))
            # The block runs inside run() in production; give it a function scope so
            # its nested helpers can use nonlocal exactly as they do on the phone.
            names=[k for k in scope if k.isidentifier()]
            code='def _outer(_g):\n'+''.join('    %s=_g[%r]\n'%(k,k) for k in names)+"    prep=None\n    attempt_prefix=''\n"+\
                 textwrap.indent(block,'    ')+'\n    return dict(locals())\n'
            exec(compile(code,'runner-selection','exec'),scope)
            try:scope.update({k:v for k,v in scope['_outer'](dict(scope)).items() if k!='_g'})
            except RuntimeError as error:scope['raised']=str(error)
        return scope,calls,records

    def test_ineligible_mismatch_keeps_original_without_native_seed_attempts(self):
        scope,calls,records=self.run_gate(['archer-queen','graveyard'])
        self.assertEqual(calls,dict(seeds=[],search=[42],probe=[]))
        self.assertIsNone(self.search_options[0]['closest'])  # strict for other decks
        self.assertEqual(self.search_options[0]['bound'],'hp_bound')  # every search prunes by tower HP
        self.assertEqual(scope['aligned']['initialization_only']['rndSeed'],42)
        self.assertEqual(scope['context']['seed_attempts'],0)
        self.assertFalse(scope['context']['seed_search_allowed'])
        self.assertEqual(records['seed-search.json']['policy']['skip_reason'],'no_seed_sensitive_card')
        self.assertEqual(records['seed-search.json']['attempts'],[])

    def test_ineligible_exhausted_abilities_fail_without_random_retry(self):
        scope,calls,records=self.run_gate(['little-prince'],fail_abilities=True)
        self.assertEqual(calls,dict(seeds=[],search=[42],probe=[]))
        self.assertIn('未发布回放',scope['raised'])
        self.assertIn('保留原种子，未搜索其他种子',scope['raised'])
        self.assertEqual(records['seed-search.json']['selected_seed'],42)

    def test_eligible_mismatch_calibrates_and_searches_but_exact_never_searches(self):
        for card in ('hunter','skeleton-king'):
            scope,calls,records=self.run_gate([card])
            self.assertNotIn('raised',scope)
            self.assertEqual(calls,dict(seeds=[42],search=[42,100],probe=['seed-0-deal-0']))
            self.assertEqual(scope['context']['random_seed'],100)
            self.assertTrue(scope['context']['final_hp_matched'])
            self.assertEqual(scope['context']['seed_attempts'],1)
            # Closest six-tower combination first; the seed reruns it within 16 attempts.
            self.assertEqual(self.search_options[0]['closest'],'hp_key')
            self.assertEqual(self.search_options[1],dict(initial={'3':1},closest='hp_key',max_attempts=1,patience=None,incumbent=123,bound=scope['hp_bound']))
            _,calls,_=self.run_gate([card],tier='exact')
            self.assertEqual(calls,dict(seeds=[],search=[42],probe=[]))

    def test_zero_attempt_messages_never_claim_seeds_were_tried(self):
        note=load('seed_search_note')
        self.assertIn('保留原种子，未搜索其他种子',note(0,False))
        self.assertNotIn('已另试',note(0,True))
        self.assertIn('已另试 2 个种子',note(2,True))
        java=(ROOT/'app/src/local/royale/replay/android/ConsoleActions.java').read_text()
        self.assertIn('if(seedSearching(state))return',java)
        self.assertNotIn('contains("随机种子")',java)

if __name__=='__main__':unittest.main()


class SeedStopTests(unittest.TestCase):
    def test_user_can_stop_search_and_play_closest_so_far(self):
        block=SOURCE[SOURCE.index('# The user may end the search at any time'):SOURCE.index("selected_candidate.clear();selected_candidate.update(chosen)")]
        self.assertIn("def seed_stop():return (destination/'seed-stop-request.json').exists()",SOURCE)
        # Closest ability combinations only for Hunter/Skeleton King decks; others stay strict.
        self.assertIn("closest_abilities=seed_search_policy(read(source),'different')['allowed']",SOURCE)
        self.assertIn("closest=hp_key if closest_abilities else None,stop_early=seed_stop if closest_abilities else lambda:False",SOURCE)
        # Seeds rerun the chosen combination first, within a small bound.
        self.assertIn("max_attempts=SCREEN_RUNS if complete_fixed else SCREEN_RUNS_UNFIXED",SOURCE)
        self.assertIn("sorted(screened,key=lambda item:item[0])[:REFINE_SEEDS]",SOURCE)
        self.assertIn("ability_search_active=True",SOURCE)
        self.assertIn("if not getattr(error,'search_report',{}).get('explored_branches_exhausted'):raise",SOURCE)
        self.assertIn("cancelled=lambda:(destination/'stop-request.json').exists() or seed_stop(),",SOURCE)
        self.assertIn("if best[4] is None:",SOURCE)
        # Checked before each seed and between calibration probes, never inside a native attempt.
        self.assertIn("if seed_stop():seed_report['stopped_by_user']=True;break",block)
        self.assertIn("if seed_stop():raise Cancelled('seed search stopped by user')",block)
        # A real cancel still cancels; only the seed stop falls through to the closest result.
        self.assertIn("if not seed_stop():raise",block)
        self.assertIn('seed_search_active=True',block)
        java=(ROOT/'app/src/local/royale/replay/android/ConsoleActions.java').read_text()
        self.assertIn('"seed-stop-request.json"',java)
        for name in ('FloatingConsole.java','MainActivity.java'):
            source=(ROOT/'app/src/local/royale/replay/android'/name).read_text()
            self.assertIn('停止匹配，用当前最接近的开播',source)
            self.assertIn('ConsoleActions.seedSearching(state)',source)


class ClosestAbilitySearchTests(unittest.TestCase):
    def load(self):
        import importlib.util,sys,types
        from unittest import mock
        stub=types.SimpleNamespace(source_completed=lambda report,count:report.get('done') is True,source_failure=lambda report:'failed')
        spec=importlib.util.spec_from_file_location('ability_search_t',ROOT.parent/'official-web-replay/ability_search.py')
        module=importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules,source_completion=stub):spec.loader.exec_module(module)
        return module

    def run_search(self,stop_after=None,match=None):
        search=self.load().search
        prep=dict(events=[dict(kind='activate_ability')]*3)
        def execute(candidate,number):
            choices=candidate['ability_target_choices']
            if '1' not in choices:return dict(error=112,native_code=3,event_index=1),dict(attempt='a%d'%number)
            return dict(done=True,score=10-int(choices['1'])*3),dict(attempt='a%d'%number)
        calls=[]
        def stop():calls.append(1);return stop_after is not None and len(calls)>stop_after
        return search(prep,execute,lambda c,r:r['score']==match,closest=lambda c,r:abs(r['score']-4),stop_early=stop)

    def test_closest_complete_branch_is_played_when_none_matches(self):
        candidate,report,result=self.run_search()
        self.assertTrue(result['closest_selected']);self.assertFalse(result['final_hp_matched'])
        self.assertEqual(report['score'],4);self.assertEqual(result['attempts'][result['chosen_attempt']]['evidence']['attempt'],'a3')

    def test_user_stop_returns_best_so_far(self):
        candidate,report,result=self.run_search(stop_after=0)
        self.assertTrue(result['stopped_by_user']);self.assertEqual(report['score'],10)

    def test_exact_match_still_wins_and_old_callers_still_fail_closed(self):
        candidate,report,result=self.run_search(match=7)
        self.assertNotIn('closest_selected',result);self.assertEqual(report['score'],7)
        search=self.load().search
        def execute(candidate,number):
            if '0' not in candidate['ability_target_choices']:return dict(error=112,native_code=2,event_index=0),{}
            return dict(done=True),{}
        with self.assertRaises(RuntimeError):search(dict(events=[dict(kind='activate_ability')]),execute,lambda c,r:False)


class ClosestAbilityRankTests(unittest.TestCase):
    def test_six_tower_difference_ranks_combinations(self):
        block=SOURCE[SOURCE.index('def hp_key(candidate,result):'):SOURCE.index('def execute_candidate(candidate,number):')]
        self.assertIn('key=(difference if difference is not None else 1<<40,PAGE_MATCH_TIERS.index(tier))',block)
        self.assertIn("if not attempt_prefix and (not closest_best or key<closest_best['key'])",block)

    def test_initial_choices_are_tried_first_and_still_branch(self):
        module=ClosestAbilitySearchTests.load(self)
        tried=[]
        def execute(candidate,number):
            choices=candidate['ability_target_choices'];tried.append(dict(choices))
            if '2' not in choices:return dict(error=112,native_code=2,event_index=2),dict(attempt='s%d'%number)
            return dict(done=True,score=int(choices['2'])),dict(attempt='s%d'%number)
        prep=dict(events=[dict(kind='activate_ability')]*3)
        candidate,report,result=module.search(prep,execute,lambda c,r:False,initial={'1':1},closest=lambda c,r:r['score'],max_attempts=16)
        self.assertEqual(tried[0],{'1':1})
        self.assertEqual(candidate['ability_target_choices'],{'1':1,'2':0})
        self.assertTrue(all(row['choices'].get('1')==1 for row in result['attempts']))


class SignalPolicyTests(unittest.TestCase):
    def setUp(self):
        import importlib.util,types
        spec=importlib.util.spec_from_file_location('signal_policy_t',ROOT.parent/'official-web-replay/signal_policy.py')
        self.policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.policy)
        self.lldb=types.SimpleNamespace(eStopReasonNone=0,eStopReasonInvalid=1,eStopReasonSignal=5,eStopReasonBreakpoint=3)

    def process(self,*threads):
        import types
        rows=[]
        for reason,signal,pc in threads:
            frame=types.SimpleNamespace(GetPC=lambda pc=pc:pc)
            rows.append(types.SimpleNamespace(GetStopReason=lambda r=reason:r,GetStopReasonDataAtIndex=lambda i,s=signal:s,
                GetThreadID=lambda:7,GetFrameAtIndex=lambda i,f=frame:f,GetStopDescription=lambda n:'signal'))
        return rows

    def test_game_runtime_signal_outside_component_is_handed_back(self):
        rows=self.policy.foreign_signal(self.lldb,self.process((5,11,0x1000),(0,0,0x5000)),[(0x9000,0xa000)])
        self.assertEqual([r['signal'] for r in rows],[11])

    def test_component_fault_trap_kill_or_breakpoint_fail_closed(self):
        regions=[(0x9000,0xa000)]
        for threads in (((5,11,0x9100),),((5,5,0x1000),),((5,9,0x1000),),((3,0,0x1000),),((0,0,0x1000),)):
            self.assertIsNone(self.policy.foreign_signal(self.lldb,self.process(*threads),regions))

    def test_both_gates_use_the_policy_and_record_it(self):
        gate=(ROOT/'device/phone_bootstrap_gate.py').read_text()
        scene=(ROOT.parent/'official-web-replay/run_scene_gate.py').read_text()
        for source in (gate,scene):
            self.assertIn('stop=foreign_signal(lldb,process,regions)',source)
            self.assertIn("passed=result.setdefault('passed_signals',[])",source)
        self.assertIn("result['stop_reasons']=stop_reasons(lldb,process)",gate)
        self.assertIn("'signal_policy.py'",(ROOT/'scripts/refresh_playback_payload.py').read_text())


class PrincessOrderTests(unittest.TestCase):
    """RoyaleAPI princess0/princess1 is not always arena left/right (02RYPY228YCQ)."""
    def rows(self,page,alive,destroyed=()):
        import sys,types
        tower_profiles=types.ModuleType('tower_profiles')
        entries=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
        tower_profiles.bindings=lambda p:{0:dict(spawn_entries=entries),1:dict(spawn_entries=entries)}
        sys.modules['tower_profiles']=tower_profiles
        import importlib;import ability_search;importlib.reload(ability_search)
        source=dict(decks=[dict(proposed_native_owner=o,oracle_final_hp=dict(zip(('king','princess0','princess1'),page[o]))) for o in (0,1)])
        xs=(9000,3500,14500);ids=(35000000,35000001,35000001)
        tw=[dict(owner=o,data_id=ids[i],x=xs[i],hp=hp) for o in (0,1) for i,hp in enumerate(alive[o]) if hp is not None]
        gone=[dict(owner=o,data_id=ids[i],x=xs[i],hp=0,health_at_destruction=0,native_destructor_observed=True) for o,i in destroyed]
        report=dict(battle_state=dict(towers=tw,destroyed_towers=gone))
        return ability_search,source,report

    def test_real_swapped_top_player_is_exact_and_recorded(self):
        # 02RYPY228YCQ: page owner1 579 / 0; simulation owner1 left destroyed, right 579.
        mod,source,report=self.rows({0:(3179,759,791),1:(3179,579,0)},{0:(3179,759,791),1:(3179,None,579)},[(1,1)])
        self.assertTrue(mod.terminal_hp_matches(source,{},report))
        rows=mod.final_tower_rows(source,{},report)
        self.assertEqual({(r['owner'],r['page_order']) for r in rows if r['tower']!='king'},{(0,'direct'),(1,'swapped')})
        self.assertEqual([r['page'] for r in rows if r['owner']==1],[3179,0,579])

    def test_swapping_never_rescues_a_wrong_branch(self):
        # Same page, a branch from the same search that ended differently.
        mod,source,report=self.rows({0:(3179,759,791),1:(3179,579,0)},{0:(2882,2908,None),1:(1960,2837,None)})
        self.assertFalse(mod.terminal_hp_matches(source,{},report))
        mod,source,report=self.rows({0:(3179,759,791),1:(3179,579,0)},{0:(3179,812,791),1:(3179,None,579)},[(1,1)])
        self.assertFalse(mod.terminal_hp_matches(source,{},report))  # 812 != 759 in either order

    def test_direct_order_kept_on_ties_and_real_direct_cases(self):
        # 002YQ9LLV989: page owner1 4786 / 1532 equals arena left / right.
        mod,source,report=self.rows({0:(7728,4818,0),1:(7728,4786,1532)},{0:(7728,4818,None),1:(7728,4786,1532)},[(0,2)])
        rows=mod.final_tower_rows(source,{},report)
        self.assertTrue(mod.terminal_hp_matches(source,{},report))
        self.assertTrue(all(r['page_order']=='direct' for r in rows))
        mod,source,report=self.rows({0:(100,50,50),1:(100,50,50)},{0:(100,50,50),1:(100,50,50)})
        self.assertTrue(all(r['page_order']=='direct' for r in mod.final_tower_rows(source,{},report)))


class TowerTroopTests(unittest.TestCase):
    """Royal Chef (08CY0LPY90V0): its towers have their own data IDs."""
    def test_chef_king_fall_zeroes_its_princess_towers(self):
        import sys,types,importlib
        chef=[dict(data_id=1471932914,grid_x=18),dict(data_id=-1103717791,grid_x=7),dict(data_id=-1103717791,grid_x=29)]
        std=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
        tower_profiles=types.ModuleType('tower_profiles');tower_profiles.bindings=lambda p:{0:dict(spawn_entries=std),1:dict(spawn_entries=chef)}
        sys.modules['tower_profiles']=tower_profiles
        import ability_search;importlib.reload(ability_search)
        source=dict(decks=[dict(proposed_native_owner=0,oracle_final_hp=dict(king=7728,princess0=3408,princess1=4275)),
                           dict(proposed_native_owner=1,oracle_final_hp=dict(king=0,princess0=0,princess1=0))])
        alive=[dict(owner=0,data_id=35000000,x=9000,hp=7728),dict(owner=0,data_id=35000001,x=3500,hp=3408),dict(owner=0,data_id=35000001,x=14500,hp=4275)]
        gone=[dict(owner=1,data_id=1471932914,x=9000,hp=0,health_at_destruction=0,native_destructor_observed=True)]
        report=dict(battle_state=dict(towers=alive,destroyed_towers=gone))
        rows=ability_search.final_tower_rows(source,{},report)
        self.assertEqual([(r['owner'],r['tower'],r['simulated'],r['evidence']) for r in rows if r['owner']==1],
                         [(1,'king',0,'destroyed'),(1,'princess0',0,'king_fell'),(1,'princess1',0,'king_fell')])
        self.assertTrue(ability_search.terminal_hp_matches(source,{},report))

    def test_native_observers_accept_the_prepared_tower_ids(self):
        shared=ROOT.parent/'official-web-replay'
        header=(shared/'source_execution.h').read_text()
        self.assertEqual(header.count('if(!replay_tower('),2)
        self.assertNotIn('if(id/1000000!=35)continue;',header)
        self.assertIn('web_source::expected_tower_ids[o*3+i]=bootstrap_towers[o][i].id;',(shared/'native_bootstrap_probe.cpp').read_text())
        self.assertIn('web_source::expected_tower_ids[o*3+i]=scene_towers[o][i].id;',(shared/'native_scene_probe.cpp').read_text())


class SignedTowerIdTests(unittest.TestCase):
    def test_destroyed_chef_tower_with_signed_id_is_matched(self):
        import sys,types,importlib
        chef=[dict(data_id=1471932914,grid_x=18),dict(data_id=-1103717791,grid_x=7),dict(data_id=-1103717791,grid_x=29)]
        std=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
        tp=types.ModuleType('tower_profiles');tp.bindings=lambda p:{0:dict(spawn_entries=std),1:dict(spawn_entries=chef)}
        sys.modules['tower_profiles']=tp
        import ability_search;importlib.reload(ability_search)
        source=dict(decks=[dict(proposed_native_owner=0,oracle_final_hp=dict(king=7728,princess0=3408,princess1=4275)),
                           dict(proposed_native_owner=1,oracle_final_hp=dict(king=7549,princess0=2115,princess1=0))])
        alive=[dict(owner=0,data_id=35000000,x=9000,hp=7728),dict(owner=0,data_id=35000001,x=3500,hp=3408),dict(owner=0,data_id=35000001,x=14500,hp=4275),
               dict(owner=1,data_id=1471932914,x=9000,hp=7549),dict(owner=1,data_id=3191249505,x=3500,hp=2115)]
        gone=[dict(owner=1,data_id=-1103717791,x=14500,hp=0,health_at_destruction=0,native_destructor_observed=True)]
        report=dict(battle_state=dict(towers=alive,destroyed_towers=gone))
        rows=ability_search.final_tower_rows(source,{},report)
        self.assertEqual([r['evidence'] for r in rows if r['owner']==1],['alive','alive','destroyed'])
        self.assertTrue(ability_search.terminal_hp_matches(source,{},report))


class StrayStopTests(unittest.TestCase):
    """A queued SIGSTOP left by our own interrupt must never freeze the game."""
    def load(self, root):
        import signal as _signal
        tree=ast.parse(SOURCE)
        nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name=='release_stray_stop')
               or (isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='STOP_SIGNAL_MASK')]
        sent=[]
        fake_os=type('os',(),{'kill':staticmethod(lambda pid,sig:sent.append((pid,sig)))})
        class FakePath(type(Path())):
            def __new__(cls,*parts):
                parts=list(parts)
                if parts and str(parts[0])=='/proc':parts[0]=root
                return Path(*parts)
        scope=dict(signal=_signal,os=fake_os,Path=FakePath)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'stray','exec'),scope)
        return scope['release_stray_stop'],sent

    def task(self, root, tid, state, tracer=0, pending='0000000000000000', shared='0000000000000000'):
        path=Path(root)/'7'/'task'/str(tid);path.mkdir(parents=True)
        (path/'stat').write_text('%d (Thread (x)) %s 1 2 3'%(tid,state))
        (path/'status').write_text('Name:\tx\nTracerPid:\t%d\nSigPnd:\t%s\nShdPnd:\t%s\n'%(tracer,pending,shared))

    def test_stopped_or_pending_stop_without_tracer_gets_sigcont(self):
        import signal as _signal
        with tempfile.TemporaryDirectory() as root:
            self.task(root,7,'T');self.task(root,8,'S',shared='0000000000040000')
            release,sent=self.load(root)
            found=release(7)
            self.assertEqual([row['tid'] for row in found],[7,8])
            self.assertEqual(sent,[(7,_signal.SIGCONT)])

    def test_running_game_or_attached_debugger_is_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            self.task(root,7,'S');self.task(root,8,'R')
            release,sent=self.load(root)
            self.assertEqual(release(7),[]);self.assertEqual(sent,[])
        with tempfile.TemporaryDirectory() as root:
            self.task(root,7,'t',tracer=99);self.task(root,8,'T',tracer=99)
            release,sent=self.load(root)
            self.assertIsNone(release(7));self.assertEqual(sent,[])
        with tempfile.TemporaryDirectory() as root:
            release,sent=self.load(root)
            self.assertIsNone(release(7));self.assertEqual(sent,[])

    def test_called_before_attach_after_detach_and_in_recovery(self):
        run=SOURCE[SOURCE.index('    def run(self,directory,attempt'):SOURCE.index('def lldb_mmap_addresses')]
        self.assertLess(run.index("raise RuntimeError('another debugger owns game')"),run.index('stray=release_stray_stop'))
        self.assertLess(run.index('stray=release_stray_stop'),run.index('AttachToProcessWithID'))
        self.assertLess(run.index('process.Detach().Success()'),run.rindex('release_stray_stop'))
        recover=SOURCE[SOURCE.index('def recover_failed_attempt'):SOURCE.index('def finish_completed')]
        self.assertIn('tracer_gone',recover);self.assertIn("if tracer_gone:release_stray_stop(identity['pid'])",recover)


class DebuggerLossRestartTests(unittest.TestCase):
    """A debugger that loses the game says nothing about the replay: restart the
    client and rerun the same step, keeping every finished candidate."""
    def classify(self):
        tree=ast.parse(SOURCE)
        nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name=='debugger_lost')
               or (isinstance(n,ast.Assign) and getattr(n.targets[0],'id','')=='DEBUGGER_LOSS_MARKERS')]
        scope={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'loss','exec'),scope)
        return scope['debugger_lost']

    def test_only_debugger_loss_is_classified(self):
        lost=self.classify()
        for error in ('RuntimeError: original task remains pending','RuntimeError: native process state 5; retain original task',
                      'RuntimeError: native expression failed: error: Expression execution was interrupted: signal SIGSTOP.'):
            self.assertTrue(lost(dict(errors=[error])))
        for receipt in (dict(errors=[]),dict(),dict(errors=['RuntimeError: 第19条技能的合法目标数为2，技能目标未唯一确定（适配器112）']),
                        dict(errors=['RuntimeError: original task remains pending','RuntimeError: native code fingerprint changed'])):
            self.assertFalse(lost(receipt))

    def test_probe_restarts_bounded_and_never_for_scenes(self):
        probe=SOURCE[SOURCE.index('        def probe(name,'):SOURCE.index("        status('calibrating'")]
        self.assertIn('if not scene and debugger_lost(result) and len(restarts)<DEBUGGER_LOSS_RESTARTS and progress[0]:',probe)
        # Another restart only after a step completed in the restarted client.
        self.assertLess(probe.index('progress[0]=0'),probe.index('restart_client(name)'))
        self.assertLess(probe.index('checked_receipt(result,execute=execute,scene=scene)'),probe.index('progress[0]+=1'))
        self.assertLess(probe.index('restart_client(name)'),probe.index("return probe(name+'-r'+str(len(restarts))"))
        restart=SOURCE[SOURCE.index('        def restart_client(name):'):SOURCE.index('        def current_prep():')]
        # Released with its own process first; continues only with an identical preparation.
        self.assertLess(restart.index('recover_failed_attempt(destination,name,identity)'),restart.index('metadata(source,fresh_preparation'))
        self.assertIn("if not generation_released(identity):raise",restart)
        self.assertIn("stable(read(fresh_preparation/'preparation.json'))!=stable(read(first_preparation/'preparation.json'))",restart)
        self.assertIn('current_prep()',probe)
        # Readers follow the suffixed name of a rerun step.
        self.assertIn("name=last_attempt",SOURCE)
        self.assertIn("roundtrip=read(destination/(last_attempt+'-source-execution.json'))",SOURCE)


class BranchAndBoundTests(unittest.TestCase):
    """A synthetic 12-ability match: each wrong choice deals extra damage at once,
    so a branch already below the page HP can be dropped at its next ambiguity."""
    DEPTH=12
    def model(self,truth):
        module=ClosestAbilitySearchTests.load(self)
        prep=dict(events=[dict(kind='activate_ability')]*self.DEPTH)
        def damage(choices):return sum(300*(choices[str(i)]!=truth[i]) for i in range(self.DEPTH) if str(i) in choices)
        def execute(candidate,number):
            choices=candidate['ability_target_choices']
            nxt=next((i for i in range(self.DEPTH) if str(i) not in choices),None)
            hp=4000-damage(choices)
            if nxt is None:return dict(done=True,hp=hp),dict(attempt='a%d'%number)
            return dict(error=112,native_code=2,event_index=nxt,hp=hp),dict(attempt='a%d'%number)
        bound=lambda c,r:(max(0,4000-r['hp']),{('t',0):r['hp']})  # page HP 4000 = the truth's final HP
        return module,prep,execute,bound
    def test_exact_search_prunes_overshooting_branches(self):
        truth=[1,0,1,1,0,0,1,0,1,1,0,1]
        module,prep,execute,bound=self.model(truth)
        exact=lambda c,r:all(c['ability_target_choices'][str(i)]==truth[i] for i in range(self.DEPTH))
        candidate,report,result=module.search(prep,execute,exact,bound=bound,max_attempts=4096)
        self.assertTrue(exact(candidate,report))
        self.assertLessEqual(len(result['attempts']),2*self.DEPTH+1)
        self.assertGreater(result['pruned'],0)
        # Without the bound the same order exhausts 4096 runs and still has not found it.
        with self.assertRaises(RuntimeError) as plain:module.search(prep,execute,exact,max_attempts=4096)
        self.assertEqual(len(plain.exception.search_report['attempts']),4096)
    def test_closest_search_never_loses_the_best_branch(self):
        truth=[0]*self.DEPTH
        module,prep,execute,bound=self.model(truth)
        closest=lambda c,r:(abs(r['hp']-4000),0)
        candidate,report,result=module.search(prep,execute,lambda c,r:False,closest=closest,bound=bound,max_attempts=4096)
        self.assertEqual(report['hp'],4000)
    def test_rising_hp_switches_pruning_off(self):
        module=ClosestAbilitySearchTests.load(self)
        prep=dict(events=[dict(kind='activate_ability')]*2)
        def execute(candidate,number):
            choices=candidate['ability_target_choices']
            if '0' not in choices:return dict(error=112,native_code=2,event_index=0,hp=100),{}
            if '1' not in choices:return dict(error=112,native_code=2,event_index=1,hp=200),{}
            return dict(done=True,hp=0),{}
        bound=lambda c,r:(0 if r['hp']==100 else 5,{('t',0):r['hp']})
        with self.assertRaises(RuntimeError) as raised:
            module.search(prep,execute,lambda c,r:False,bound=bound)
        self.assertFalse(raised.exception.search_report['bound_monotonic'])


class SeedFallbackTests(unittest.TestCase):
    def test_dead_initial_combination_falls_back_to_this_seeds_own_branches(self):
        module=ClosestAbilitySearchTests.load(self)
        prep=dict(events=[dict(kind='activate_ability')]*2)
        tried=[]
        def execute(candidate,number):
            choices=candidate['ability_target_choices'];tried.append(dict(choices))
            if choices=={'0':1}:return dict(error=114,native_code=4,event_index=1,dispatch=[]),{}  # fixed branch dies
            if '0' not in choices:return dict(error=112,native_code=2,event_index=0),{}
            return dict(done=True,score=int(choices['0'])),{}
        candidate,report,result=module.search(prep,execute,lambda c,r:False,initial={'0':1},
            closest=lambda c,r:(r['score'],0),max_attempts=16)
        self.assertEqual(tried[0],{'0':1})
        self.assertEqual(tried[1],{})
        self.assertEqual(report['score'],0)
    def test_plateau_stops_once_exact_is_impossible(self):
        module=ClosestAbilitySearchTests.load(self)
        depth=10;prep=dict(events=[dict(kind='activate_ability')]*depth)
        def execute(candidate,number):
            choices=candidate['ability_target_choices']
            nxt=next((i for i in range(depth) if str(i) not in choices),None)
            if nxt is None:return dict(done=True,hp=1000+sum(choices.values())),{}
            return dict(error=112,native_code=2,event_index=nxt,hp=1000),{}
        bound=lambda c,r:(5,{('t',0):r['hp']})  # every branch already provably off the page
        candidate,report,result=module.search(prep,execute,lambda c,r:False,closest=lambda c,r:(r['hp'],0),
            bound=bound,patience=6,max_attempts=4096)
        self.assertTrue(result['exact_impossible'])
        self.assertLess(len(result['attempts']),60)


class SuccessiveHalvingTests(unittest.TestCase):
    run_gate=SeedPolicyTests.run_gate
    source=SeedPolicyTests.source
    def test_screen_every_seed_once_then_refine_only_the_closest(self):
        diffs={42:900,1:800,2:300,3:700,4:200,5:600}
        scope,calls,records=self.run_gate(['hunter'],seeds=(1,2,3,4,5),differences=diffs)
        self.assertNotIn('raised',scope)
        # One deal probe per seed while screening.
        self.assertEqual(calls['probe'],['seed-%d-deal-0'%n for n in range(5)])
        # 1 original + 5 screened + 3 refined searches; refinement visits the 3 closest seeds, closest first.
        self.assertEqual(calls['search'],[42,1,2,3,4,5,4,2,5])
        self.assertEqual(self.search_options[6]['max_attempts'],24)
        self.assertEqual(scope['context']['random_seed'],4)
        phases=[row['phase'] for row in records['seed-search.json']['attempts']]
        self.assertEqual(phases,['screen']*5+['refine']*3)


class UnfixedScreeningTests(unittest.TestCase):
    run_gate=SeedPolicyTests.run_gate
    source=SeedPolicyTests.source
    def test_seeds_get_their_own_search_when_no_combination_completed(self):
        scope,calls,records=self.run_gate(['hunter'],fail_abilities=True)
        # The original seed's search fails; every screened seed then gets a real search budget.
        self.assertEqual(calls['search'][:2],[42,100])
        self.assertEqual(self.search_options[1]['initial'],{})
        self.assertEqual(self.search_options[1]['max_attempts'],12)
        self.assertEqual(self.search_options[1]['patience'],6)


class PreflightRejectionTests(unittest.TestCase):
    """Code 30 = game not an idle lobby, nothing executed: release, wait, retry once more."""
    def test_gate_releases_the_component_on_a_preflight_rejection(self):
        gate=(ROOT/'device/phone_bootstrap_gate.py').read_text()
        self.assertIn("preflight_rejected=(f[:4]==[1,1,1,1] and f[4]==30 and f[87]==1 and not any(f[80:83]))",gate)
        self.assertIn("if not initialized and not clean_deal_failure and not preflight_rejected:raise",gate)
        # Released and unloaded BEFORE the rejection is reported.
        self.assertLess(gate.index("if call('release')!=1"),gate.index("if preflight_rejected:raise RuntimeError('resource preflight rejected"))
        self.assertLess(gate.index("result['component_unloaded']=True"),gate.index("if preflight_rejected:raise RuntimeError('resource preflight rejected"))
    def test_runner_waits_for_the_lobby_and_retries_the_same_step(self):
        probe=SOURCE[SOURCE.index('        def probe(name,'):SOURCE.index("        status('calibrating'")]
        self.assertIn("(result.get('resource_preflight_rejected') or result.get('publication_refused'))",probe)
        self.assertIn("and result.get('component_unloaded') and preflight_retries[0]<PREFLIGHT_RETRIES",probe)
        self.assertLess(probe.index('wait_idle_lobby(identity,progress=status,cancellation=cancellation,timeout=180)'),
                        probe.index("return probe(name+'-p'+str(preflight_retries[0])"))
        self.assertIn('PREFLIGHT_RETRIES=8',SOURCE)
    def test_seed_search_stops_when_an_attempt_still_owns_the_game(self):
        self.assertIn("if 'native attempt retained' in str(error) or 'still owns game' in str(error):",SOURCE)


class ReproducibilityTests(unittest.TestCase):
    run_gate=SeedPolicyTests.run_gate
    source=SeedPolicyTests.source
    def test_seed_plan_depends_on_the_match_not_the_saved_bytes(self):
        tree=ast.parse(SOURCE)
        nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','')=='SEED_ATTEMPTS' for t in n.targets)]
        nodes+=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('replay_key','seed_plan')]
        scope=dict(hashlib=hashlib,json=__import__('json'));exec(compile(ast.Module(body=nodes,type_ignores=[]),'k','exec'),scope)
        base=dict(replay_tag='T',source_html='/a.html',source_sha256='a'*64,decks=[dict(source_side='team',proposed_native_owner=0,cards=[dict(base_card_key='x',form='basic',source_level=11)])],
                  actions=[dict(kind='play_card',source_tick_20hz=5,source_side='team',base_card_key='x',source_position={'x':1,'y':2})])
        resaved=dict(base,source_html='/b.html',source_sha256='b'*64)
        self.assertEqual(scope['replay_key'](base),scope['replay_key'](resaved))
        moved=copy.deepcopy(base);moved['actions'][0]['source_tick_20hz']=6
        self.assertNotEqual(scope['replay_key'](base),scope['replay_key'](moved))
        plan=scope['seed_plan']('k',1,remembered=777)
        self.assertEqual(plan[0],777);self.assertEqual(len(plan),61)
        self.assertEqual(scope['seed_plan']('k',1)[:3],plan[1:4])
    def test_closest_seed_is_remembered_and_tried_first_next_time(self):
        scope,calls,records=self.run_gate(['hunter'],seeds=(1,2,3),differences={42:900,1:800,2:300,3:700})
        memory=scope['seed_memory']
        self.assertEqual(memory['match-key']['seed'],2);self.assertEqual(memory['match-key']['difference'],300)
        # Next run of the same match: the remembered seed is offered first.
        self.assertIsNone(self.remembered[0])
        self.assertIn('if rank(tier,difference)<rank(previous.get(',SOURCE)
        self.assertIn("seed_plan(match_key,original_seed,remembered=remembered_seed)",SOURCE)
    def test_native_release_allows_a_task_that_never_entered(self):
        native=(ROOT.parent/'official-web-replay/native_bootstrap_probe.cpp').read_text()
        self.assertIn('(!probe->layout.freed&&!probe->resource_preflight_rejected&&probe->entered.load())',native)
        gate=(ROOT/'device/phone_bootstrap_gate.py').read_text()
        block=gate[gate.index("if result['publication']==0:"):gate.index("if result['publication']!=1:raise")]
        self.assertLess(block.index("call('release')"),block.index("raise RuntimeError('publication refused"))
        self.assertIn("result['publication_refused']=True",block)
