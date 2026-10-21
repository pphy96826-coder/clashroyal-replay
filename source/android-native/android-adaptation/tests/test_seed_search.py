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
    nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name==name)
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
        self.assertLess(block.index("trial['initialization_only']['rndSeed']=seed"),block.index('trial=calibrate(trial,deal,trial_seen)'))
        self.assertLess(block.index('trial=calibrate(trial,deal,trial_seen)'),block.index('search(trial,execute_candidate'))
        # Only fully executed runs compete; the original seed stays a candidate; an exact match stops the search.
        self.assertIn("best=(rank(tier,difference),original_seed",block)
        self.assertIn("if rank(trial_tier,trial_difference)<best[0]:",block)
        self.assertIn("if best[2]=='exact':break",block)
        self.assertIn("selected_candidate.clear();selected_candidate.update(chosen)",block)
        self.assertIn("raise Cancelled('cancelled during seed search')",block)
        tail=SOURCE[SOURCE.index("receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']"):]
        self.assertIn("context.update(final_hp_matched=hp_matched,page_match=tier,page_hp_difference=difference",tail)
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

    def run_gate(self, cards, tier='different', fail_abilities=False):
        """Execute the real runner selection block with native calls replaced by counters."""
        start=SOURCE.index('            ability_error=None')
        end=SOURCE.index('            full=finalize(aligned,execution,receipt)',start)
        block=textwrap.dedent(SOURCE[start:end])
        source=self.source(cards,[])
        aligned=dict(initialization_only=dict(rndSeed=42),events=[dict(tick=20)])
        selected={};calls=dict(seeds=[],search=[],probe=[]);records={}
        def search(candidate,execute,match,*,cancelled):
            calls['search'].append(candidate['initialization_only']['rndSeed'])
            if fail_abilities:
                error=RuntimeError('strict ability search exhausted')
                error.search_report=dict(explored_branches_exhausted=True)
                raise error
            selected.update(receipt='receipt',preparation='prep')
            return candidate,dict(seed=candidate['initialization_only']['rndSeed']),dict(inferred=False)
        def plan(sha,original):calls['seeds'].append(original);return [100]
        def compare(source,candidate,report):
            return ('exact',0) if report['seed']==100 else (tier,0 if tier=='exact' else 123)
        def calibrate(candidate,deal,seen):candidate['native_deal_ready']=True;return candidate
        with tempfile.TemporaryDirectory() as directory:
            scope=dict(aligned=aligned,delayed=copy.deepcopy(aligned),source='source',read=lambda path:source,
                       seed_search_policy=load('seed_search_policy'),seed_search_note=load('seed_search_note'),
                       PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different'),SEED_ATTEMPTS=60,
                       rank=lambda t,d:(('exact','same_towers','same_winner','different').index(t),d or 0),
                       search=search,execute_candidate=None,terminal_hp_matches=lambda *args:True,page_comparison=compare,page_towers=lambda *args:[],
                       restore=lambda result:None,selected_candidate=selected,context={},
                       destination=Path(directory),preparation=Path(directory),request=dict(source_sha256='a'*64),
                       write_new=lambda path,value:records.update({path.name:copy.deepcopy(value)}),
                       seed_plan=plan,copy=copy,seed_stop=lambda:False,status=lambda *args,**kwargs:None,
                       calibrate=calibrate,deck_fingerprint=lambda candidate:(),
                       probe=lambda name:calls['probe'].append(name),Cancelled=type('Cancelled',(Exception,),{}))
            try:exec(compile(block,'runner-selection','exec'),scope)
            except RuntimeError as error:scope['raised']=str(error)
        return scope,calls,records

    def test_ineligible_mismatch_keeps_original_without_native_seed_attempts(self):
        scope,calls,records=self.run_gate(['archer-queen','graveyard'])
        self.assertEqual(calls,dict(seeds=[],search=[42],probe=[]))
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
        # Abilities stay strict: no closest fallback anywhere in the runner.
        self.assertNotIn('closest=',SOURCE)
        self.assertIn("if not getattr(error,'search_report',{}).get('explored_branches_exhausted'):raise",SOURCE)
        self.assertIn("cancelled=lambda:(destination/'stop-request.json').exists() or seed_stop())",SOURCE)
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
