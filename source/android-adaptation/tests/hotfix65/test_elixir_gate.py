from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[2]
SHARED=ROOT.parent/'windows-adaptation/project/official-web-replay'
SHARED=ROOT.parent/'windows-adaptation/project/official-web-replay'
sys.path.insert(0,str(SHARED))
import test_seed_search as seed_tests  # noqa: E402
load=seed_tests.load

PAGE={0:(2151,1630,2000),1:(4824,2037,2146)}
XS=(9000,3500,14500);IDS=(35000000,35000001,35000001)


def tower_stub():
    module=types.ModuleType('tower_profiles')
    entries=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
    module.bindings=lambda p:{0:dict(spawn_entries=entries),1:dict(spawn_entries=entries)}
    sys.modules['tower_profiles']=module


def source(leaked=(14.37,11.66)):
    return dict(source_duration_seconds=267,decks=[
        dict(proposed_native_owner=o,source_side=('team','opponent')[o],oracle_elixir_leaked=None if leaked is None else leaked[o],
             oracle_final_hp=dict(zip(('king','princess0','princess1'),PAGE[o]))) for o in (0,1)])


def report(leaked=(143700,116600),tick=267*20,abilities=()):
    towers=[dict(owner=o,data_id=IDS[i],x=XS[i],hp=hp) for o in (0,1) for i,hp in enumerate(PAGE[o])]
    elixir=[dict(current=20000,spent=1300000,gained=1500000,leaked=value) for value in leaked]
    diagnostics=[dict(owner=o,actor=dict(id=1,cost=c)) for o,c in abilities]
    return dict(finished=1,tick=tick,elixir=elixir,elixir_at_page_end=dict(tick=267*20,sides=elixir),
                diagnostics=diagnostics,battle_state=dict(towers=towers))


class PageParsingTests(unittest.TestCase):
    def test_leaked_elixir_follows_the_hp_popup_order(self):
        from import_replay import elixir_leaked_from_html,attach_elixir_leaked
        def header(value,total):
            return ('<div data-content="Elixir Leaked"><div class="value"><span class="name">Elixir Leaked </span> '+value+
                    ' </div></div><div class="value"><span class="hp-popup" data-king="1" data-princess0="2" data-princess1="3" data-total="'+total+'">x</span></div>')
        html=header('14.37','7876')+'<td class="title">Leaked</td><td> 23.66 </td>'+header('11.66','9871')
        self.assertEqual(elixir_leaked_from_html(html),dict(team=14.37,opponent=11.66))
        document=dict(decks=[dict(source_side='team'),dict(source_side='opponent')])
        attach_elixir_leaked(document,html)
        self.assertEqual([d['oracle_elixir_leaked'] for d in document['decks']],[14.37,11.66])
        # A missing or doubled value is never guessed.
        self.assertIsNone(elixir_leaked_from_html(header('14.37','1')))
        self.assertIsNone(elixir_leaked_from_html(header('1.0','1')+header('2.0','2').replace('Elixir Leaked </span> 2.0','')))
        attach_elixir_leaked(document,'')
        self.assertEqual([d['oracle_elixir_leaked'] for d in document['decks']],[None,None])

    def test_device_import_records_the_page_values(self):
        text=(ROOT/'device/device_import.py').read_text()
        self.assertIn('attach_elixir_leaked(document, text)',text)
        refresh=(Path.cwd()/'work/build_mumu_development_home.py').read_text()
        self.assertIn("'import_replay.py'",refresh)
        self.assertIn("'device_import.py'",refresh)


class ElixirCheckTests(unittest.TestCase):
    def setUp(self):
        tower_stub()
        import ability_search
        self.mod=ability_search

    def test_leaked_elixir_must_match_to_two_decimals(self):
        mod=self.mod
        self.assertEqual(mod.elixir_check(source(),report()),(True,0.0))
        self.assertTrue(mod.elixir_check(source(),report(leaked=(143799,116651)))[0])  # the page truncates
        # Calibrated on 092PYR8PUC9R (six towers exact): 1.5028 -> 1.50, 0.9579 -> 0.95.
        self.assertTrue(mod.elixir_matches(1.5028,1.5));self.assertTrue(mod.elixir_matches(0.9579,0.95))
        self.assertFalse(mod.elixir_matches(0.9499,0.95));self.assertFalse(mod.elixir_matches(0.96,0.95))
        matched,difference=mod.elixir_check(source(),report(leaked=(153700,116600)))
        self.assertFalse(matched);self.assertEqual(difference,1.0)
        self.assertEqual(mod.elixir_check(source(None),report()),(None,None))
        self.assertEqual(mod.elixir_check(source(),dict(report(),elixir=None,elixir_at_page_end=None)),(None,None))

    def test_leak_is_measured_at_the_page_end_time(self):
        mod=self.mod
        # The run went on 16 s past the page's end and leaked 17 more: only the page-end snapshot counts.
        late=dict(report(),elixir=[dict(current=100000,spent=1300000,gained=1500000,leaked=v+170000) for v in (143700,116600)])
        self.assertEqual(mod.elixir_check(source(),late),(True,0.0))
        self.assertEqual({r['measured_at'] for r in mod.elixir_rows(source(),late)},{'page_end'})
        # The battle ended before the page's end: its final leak is all it will ever leak.
        early=dict(report(leaked=(143700,100000)),elixir_at_page_end=None)
        rows=mod.elixir_rows(source(),early)
        self.assertEqual(rows[0]['measured_at'],'battle_end');self.assertFalse(rows[1]['matched'])
        # A run paused at an ambiguity only gives a lower bound.
        paused=dict(report(leaked=(100000,100000)),elixir_at_page_end=None,finished=0)
        self.assertEqual(mod.elixir_rows(source(),paused)[0]['measured_at'],'paused')
        self.assertEqual(mod.damage_lower_bound(source(),{},paused)[0],0)

    def test_page_end_tick_reaches_the_native_run(self):
        text=(SHARED/'bootstrap_input.py').read_text()
        self.assertIn("'static constexpr int bootstrap_page_end='",text)
        self.assertIn("'page_end_tick':int(round(duration*20))",(SHARED/'prepare_native_replay.py').read_text())
        self.assertIn('web_source::elixir_checkpoint=bootstrap_page_end;',(SHARED/'native_bootstrap_probe.cpp').read_text())
        header=(SHARED/'source_execution.h').read_text()
        self.assertIn('if(result.checkpoint_tick<0&&before+1==elixir_checkpoint){',header)
        self.assertIn('\\"elixir_at_page_end\\":"+checkpoint+',header)

    def test_a_play_without_enough_elixir_is_impossible(self):
        mod=self.mod
        short=report()
        short['elixir'][1]=dict(short['elixir'][1],spent=1295321)  # charged a fraction: not enough elixir
        matched,_=mod.elixir_check(source(),short)
        self.assertFalse(matched)
        self.assertTrue(mod.elixir_rows(source(None),short)[1]['shortfall'])
        self.assertFalse(mod.elixir_check(source(None),short)[0])  # impossible even without page values
        self.assertGreaterEqual(mod.damage_lower_bound(source(),{},dict(short,finished=0))[0],mod.ELIXIR_MISMATCH_COST)
        self.assertIn('实战中不可能',load('elixir_gate')(source(),{},short))

    def test_the_match_may_end_anywhere_within_the_end_time_tolerance(self):
        mod=self.mod
        end=267*20
        # At the page's whole-second end blue already leaked 14.398 (shows 14.39); three ticks
        # earlier both players match the page together, as on replay 02JYPPC02YUL.
        late=report(leaked=(143980,116627))
        late['elixir_window']=dict(first_tick=end-20,leaked=[[143718,116627]]*18+[[143980,116627]]*23)
        rows=mod.elixir_rows(source(),late)
        self.assertTrue(all(r['matched'] for r in rows))
        self.assertEqual({r['measured_at'] for r in rows},{'page_end_window'})
        self.assertEqual(rows[0]['window_offset_ticks'],-3)
        self.assertEqual(mod.elixir_check(source(),late)[0],True)
        # Both players must match at the SAME tick.
        apart=report(leaked=(143980,126627))
        apart['elixir_window']=dict(first_tick=end-20,leaked=[[143718,126627]]*20+[[143980,116627]]*21)
        self.assertFalse(mod.elixir_check(source(),apart)[0])
        # Outside the tolerance never counts.
        far=report(leaked=(143980,116627))
        far['elixir_window']=dict(first_tick=end-40,leaked=[[143718,116627]]*5+[[143980,116627]]*76)
        self.assertFalse(mod.elixir_check(source(),far)[0])

    def test_progress_never_shows_a_placeholder_tier(self):
        playback=seed_tests.SOURCE
        self.assertNotIn("当前最接近：'+tier_names[best[2]]",playback)
        self.assertIn("return '尚无溢出圣水与网页一致的完整组合' if best[4] is None else tier_names[best[2]]+cost_text(best[3],page_breakdown(read(source),best[4][0],best[4][1]))",playback)
        header=(SHARED/'source_execution.h').read_text()
        self.assertIn('inline constexpr int elixir_window_ticks=20;',header)

    def test_exact_requires_elixir_too(self):
        mod=self.mod
        self.assertTrue(mod.terminal_hp_matches(source(),{},report()))
        self.assertFalse(mod.terminal_hp_matches(source(),{},report(leaked=(153700,116600))))
        self.assertTrue(mod.terminal_hp_matches(source(None),{},report(leaked=(153700,116600))))

    def test_implied_ability_spend(self):
        rows=self.mod.elixir_rows(source(),report(leaked=(153700,116600),abilities=((0,1),(0,2),(1,1))))
        self.assertEqual(rows[0]['ability_spent'],3);self.assertEqual(rows[1]['ability_spent'],1)
        # One elixir more leaked than the page: abilities + final elixir should be one higher.
        self.assertEqual(rows[0]['implied_ability_and_final'],round(3+2+15.37-14.37,2))
        self.assertIsNone(self.mod.elixir_rows(source(),report(abilities=((0,-1),)))[0].get('ability_spent'))

    def test_partial_leak_beyond_the_page_prunes(self):
        mod=self.mod
        lower,_=mod.damage_lower_bound(source(),{},report())
        self.assertEqual(lower,0)
        lower,_=mod.damage_lower_bound(source(),{},report(leaked=(153700,116600)))
        self.assertEqual(lower,mod.ELIXIR_MISMATCH_COST+2000)
        # Below the page is still reachable: no penalty.
        lower,_=mod.damage_lower_bound(source(),{},report(leaked=(100000,116600)))
        self.assertEqual(lower,0)

    def test_page_comparison_puts_every_elixir_match_first(self):
        cmp=load('page_comparison')
        self.assertEqual(cmp(source(),{},report()),('exact',0))
        tier,cost=cmp(source(),{},report(leaked=(153700,116600)))
        self.assertEqual(tier,'same_towers');self.assertEqual(cost,self.mod.ELIXIR_MISMATCH_COST+2000)
        playback=seed_tests.SOURCE
        self.assertIn('return (type(difference) is int and difference>=ELIXIR_MISMATCH_COST,PAGE_MATCH_TIERS.index(tier)',playback)

    def test_gate_message_names_both_values(self):
        gate=load('elixir_gate')
        self.assertIsNone(gate(source(),{},report()))
        self.assertIsNone(gate(source(None),{},report(leaked=(1,1))))
        message=gate(source(),{},report(leaked=(153700,116600),abilities=((0,1),)))
        self.assertIn('溢出圣水与网页不一致',message);self.assertIn('网页 14.37，模拟 15.37',message)
        self.assertIn('本次技能实付 1',message);self.assertNotIn('红方',message)


class ElixirSearchTests(unittest.TestCase):
    def search(self,keys):
        load=seed_tests.ClosestAbilitySearchTests('test_user_stop_returns_best_so_far').load
        module=load()
        prep=dict(events=[dict(kind='activate_ability')])
        def execute(candidate,number):
            choices=candidate['ability_target_choices']
            if '0' not in choices:return dict(error=112,native_code=2,event_index=0),dict(attempt='a%d'%number)
            return dict(done=True,choice=choices['0']),dict(attempt='a%d'%number)
        return module,lambda:module.search(prep,execute,lambda c,r:False,closest=lambda c,r:(keys[r['choice']],1))

    def test_complete_runs_with_the_wrong_leak_never_become_closest(self):
        module,run=self.search({0:module_cost(1),1:900})
        candidate,report,result=run()
        self.assertEqual(report['choice'],1)
        self.assertTrue(any(row.get('elixir_rejected') for row in result['attempts']))

    def test_nothing_is_kept_when_every_complete_run_leaks_wrong(self):
        module,run=self.search({0:module_cost(1),1:module_cost(5)})
        with self.assertRaises(RuntimeError) as caught:run()
        self.assertTrue(caught.exception.search_report['explored_branches_exhausted'])

    def test_a_branch_past_the_page_leak_is_always_pruned(self):
        tower_stub()
        import ability_search
        branches=[]
        prep=dict(events=[dict(kind='activate_ability')]*2)
        def execute(candidate,number):
            choices=candidate['ability_target_choices']
            if '0' not in choices:return dict(error=112,native_code=2,event_index=0),{}
            branches.append(dict(choices))
            return dict(error=112,native_code=2,event_index=1),{}
        bound=lambda c,r:(ability_search.ELIXIR_MISMATCH_COST+10 if c['ability_target_choices'].get('0')==0 else 0,{})
        with self.assertRaises(RuntimeError):ability_search.search(prep,execute,lambda c,r:False,closest=lambda c,r:(0,0),bound=bound,max_attempts=6)
        # Children of the over-leaking branch 0 are never run.
        self.assertFalse(any(b.get('0')==0 and '1' in b for b in branches))


def module_cost(extra):
    return 1000000+extra


class ElixirGateRunnerTests(unittest.TestCase):
    def test_mismatching_elixir_is_never_published(self):
        runner=seed_tests.SeedPolicyTests('test_zero_attempt_messages_never_claim_seeds_were_tried')
        scope,_,_=runner.run_gate(['archer-queen'])
        self.assertNotIn('raised',scope)
        runner.elixir_refusal='溢出圣水与网页不一致：蓝方 网页 14.37，模拟 15.37'
        scope,_,records=runner.run_gate(['archer-queen'])
        self.assertIn('溢出圣水与网页不一致',scope['raised'])
        self.assertIn('未放行，未发布回放',scope['raised'])
        self.assertIn('page-comparison.json',records)  # the evidence is kept

    def test_seed_search_fixes_the_elixir_consistent_heroes(self):
        runner=seed_tests.SeedPolicyTests('test_zero_attempt_messages_never_claim_seeds_were_tried')
        runner.elixir_consistent=dict(key=(3,5127),choices={'40':1,'52':0,'60':1})
        scope,calls,records=runner.run_gate(['hunter'],fail_abilities=True,seeds=(100,101))
        self.assertTrue(records['seed-search.json']['ability_choices_from_elixir'])
        self.assertEqual(records['seed-search.json']['fixed_ability_choices'],{'40':1,'52':0,'60':1})
        self.assertEqual(runner.search_options[1]['initial'],{'40':1,'52':0,'60':1})
        # Elixir only constrains: the seed still enumerates its own branches.
        self.assertEqual(runner.search_options[1]['max_attempts'],12)
        self.assertEqual(runner.search_options[1]['patience'],6)
        # Without elixir evidence nothing is fixed.
        runner.elixir_consistent={}
        scope,calls,records=runner.run_gate(['hunter'],fail_abilities=True,seeds=(100,))
        self.assertFalse(records['seed-search.json']['ability_choices_from_elixir'])
        self.assertEqual(runner.search_options[1]['initial'],{})

    def test_only_branches_still_within_the_page_leak_are_kept(self):
        playback=seed_tests.SOURCE
        block=playback[playback.index('        def track_elixir(candidate,result):'):playback.index('        def execute_candidate(candidate,number):')]
        self.assertIn("if not rows or any(r['simulated']>=r['page']+ELIXIR_TOLERANCE+elixir_margin(read(source))-1e-6 for r in rows):return",block)
        self.assertIn("key=(len(choices),result.get('tick')",block)
        self.assertIn("if not attempt_prefix:track_elixir(candidate,result)",playback)
        self.assertIn("elixir_inferred=bool(closest_abilities and elixir_consistent and best[4] is None and not context.get('skill_pool_mode'))",playback)

    def test_failure_message_keeps_the_elixir_values(self):
        from failure_recovery import explanation
        text=explanation(RuntimeError('溢出圣水与网页不一致：红方 网页 11.66，模拟 14.05（按网页反推：技能费用 + 终局剩余圣水应为 35.63，本次技能实付 26）（已另试 64 个种子）；未放行，未发布回放。'))
        self.assertIn('红方 网页 11.66，模拟 14.05',text);self.assertIn('必须与网页一致才放行',text)

    def runner(self):
        return seed_tests.SeedPolicyTests('test_zero_attempt_messages_never_claim_seeds_were_tried')

    def test_an_original_run_with_the_wrong_leak_is_discarded(self):
        runner=self.runner()
        # Original seed 42 leaks the wrong elixir; seed 100 matches the page's elixir.
        runner.elixir_gate_fn=lambda source,candidate,report:'溢出圣水与网页不一致：红方' if report['seed']==42 else None
        scope,calls,records=runner.run_gate(['hunter'],differences={42:1000500,100:300},seeds=(100,))
        self.assertNotIn('raised',scope)
        self.assertEqual(scope['context']['random_seed'],100)
        self.assertEqual(records['seed-search.json']['original_tier'],'different')
        self.assertEqual(records['seed-search.json']['fixed_ability_choices'],{})  # never seeds the search

    def test_seed_runs_with_the_wrong_leak_are_discarded(self):
        runner=self.runner()
        runner.elixir_gate_fn=lambda source,candidate,report:'溢出圣水与网页不一致：红方'
        scope,calls,records=runner.run_gate(['hunter'],differences={42:1000500,100:1000300},seeds=(100,))
        self.assertIn('溢出圣水与网页不一致',scope['raised'])
        self.assertIn('没有溢出圣水和技能目标都与网页一致的分支',scope['raised'])
        row=records['seed-search.json']['attempts'][0]
        self.assertFalse(row['executed']);self.assertIn('已丢弃',row['error'])

    def test_native_reports_engine_elixir_totals(self):
        header=(SHARED/'source_execution.h').read_text()
        for offset in ('client_layout::elixir_snapshot','client_layout::active_avatar.leaked','ability+0xb4'):self.assertIn(offset,header)
        layout=(SHARED/'client_layout.h').read_text()
        self.assertIn('avatar_3842{0x300,0x348,0x34c,0x350}',layout)
        self.assertIn('avatar_3852{0x308,0x350,0x354,0x358}',layout)
        self.assertIn('",\\"elixir\\":"+elixir+',header)


if __name__=='__main__':unittest.main()
