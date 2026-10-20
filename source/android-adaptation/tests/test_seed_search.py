from pathlib import Path
import ast
import hashlib
import unittest

ROOT=Path(__file__).resolve().parents[1]
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
        self.assertIn("if tier!='exact':",block)
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
        self.assertEqual(run(page,{0:(2151,1630,None),1:(4824,2037,2146)}),('different',None))

    def test_ready_message_never_claims_a_match_that_was_not_found(self):
        ready=SOURCE[SOURCE.index("if diagnostic is not None:ready_message="):SOURCE.index("status('ready_to_open',ready_message)")]
        self.assertIn("elif context.get('page_match')=='same_towers':ready_message=",ready)
        self.assertIn("elif not context.get('final_hp_matched'):ready_message='全部指令已执行，但终局与网页不符",ready)
        actions=(ROOT/'app/src/local/royale/replay/android/ConsoleActions.java').read_text()
        self.assertIn('return state.optString("page_match",state.optBoolean("final_hp_matched",true)?"exact":"different");',actions)
        status=(ROOT/'app/src/local/royale/replay/android/PlaybackStatus.java').read_text()
        self.assertIn('"⚠ 终局与网页不符 · 准备前台加载"',status)

if __name__=='__main__':unittest.main()
