"""Saved-page values are unlocated; never rewrite native tower coordinates."""
import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'windows-adaptation/project/official-web-replay'))
from ability_search import final_tower_rows,terminal_hp_matches,damage_lower_bound

def comparisons():
    names={'page_tower_comparison','page_comparison','page_breakdown','cost_text'}
    tree=ast.parse((ROOT/'android-adaptation/device/device_playback.py').read_text())
    scope={}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'tower-comparison','exec'),scope)
    return scope

class Tests(unittest.TestCase):
    def setUp(self):
        entries=[dict(data_id=35000000,grid_x=18),dict(data_id=35000001,grid_x=7),dict(data_id=35000001,grid_x=29)]
        self.binding=patch('tower_profiles.bindings',return_value={o:dict(spawn_entries=entries) for o in (0,1)})
        self.binding.start();self.addCleanup(self.binding.stop)
        self.source=dict(source_duration_seconds=284,decks=[
            dict(source_side='team',proposed_native_owner=1,oracle_final_hp=dict(king=4824,princess0=2158,princess1=2819)),
            dict(source_side='opponent',proposed_native_owner=0,oracle_final_hp=dict(king=4824,princess0=2526,princess1=0))])
        self.report=dict(finished=1,tick=5686,battle_state=dict(towers=[
            dict(owner=o,data_id=data,x=x,hp=hp) for o,values in [(1,(4824,1999,2819)),(0,(4824,None,2437))]
            for data,x,hp in zip((35000000,35000001,35000001),(9000,3500,14500),values) if hp is not None],
            destroyed_towers=[dict(owner=0,data_id=35000001,x=3500,hp=0,health_at_destruction=0,native_destructor_observed=True)]))

    def test_actual_5122_case_is_248_in_every_comparison_without_changing_coordinates(self):
        import copy
        original=copy.deepcopy((self.source,self.report))
        rows=final_tower_rows(self.source,{},self.report)
        self.assertEqual(sum(r['difference'] for r in rows),248)
        self.assertEqual([r['difference'] for r in rows],[0,159,0,0,0,89])
        a,b=[r for r in rows if r['owner']==0 and r['tower']!='king']
        self.assertEqual((a['x'],a['simulated'],a['page'],a['raw_page'],a['page_tower_key']),(3500,0,0,2526,'princess1'))
        self.assertEqual((b['x'],b['simulated'],b['page'],b['raw_page']),(14500,2437,2526,0))
        self.assertFalse(a['page_side_verified']);self.assertTrue(a['page_pairing_inferred'])
        self.assertEqual((self.source,self.report),original)
        funcs=comparisons()
        self.assertEqual(funcs['page_comparison'](self.source,{},self.report),('same_towers',248))
        detail=funcs['page_breakdown'](self.source,{},self.report)
        self.assertEqual(detail['hp_difference'],248);self.assertEqual(detail['time_penalty'],0)
        self.assertIn('elixir_strict_matched',detail);self.assertIn('elixir_tolerance_margin',detail)
        text=funcs['cost_text'](248,detail)
        self.assertIn('塔血差 248',text);self.assertIn('2526→2437（差89）',text)
        self.assertIn('按最小血差自动配对',text)
        self.assertFalse(terminal_hp_matches(self.source,{},self.report))

    def test_actual_final_receipt_write_preserves_single_tower_detail(self):
        # Execute the production publication statement, not a reimplemented merge.
        import json,tempfile
        tree=ast.parse((ROOT/'android-adaptation/device/device_playback.py').read_text())
        writes=[n for n in ast.walk(tree) if isinstance(n,ast.Call)
                and isinstance(n.func,ast.Name) and n.func.id=='write_new'
                and n.args and 'page-comparison.json' in ast.unparse(n.args[0])]
        self.assertEqual(len(writes),1)
        funcs=comparisons();detail=funcs['page_breakdown'](self.source,{},self.report)
        for tier,difference in [('exact',0),('same_towers',248)]:
            with tempfile.TemporaryDirectory() as d:
                scope=dict(destination=Path(d),tier=tier,difference=difference,breakdown=detail,
                           page_towers=final_tower_rows,read=lambda _:self.source,source=None,aligned={},execution=self.report,
                           write_new=lambda p,value:p.write_text(json.dumps(value)))
                exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(writes[0])],type_ignores=[])),'receipt','exec'),scope)
                saved=json.loads((Path(d)/'page-comparison.json').read_text())
                self.assertEqual(saved['towers'],detail['towers']);self.assertEqual(len(saved['towers']),6)
                self.assertEqual(saved['tier'],tier);self.assertEqual(saved['match_cost'],difference)

    def test_missing_or_invalid_destruction_is_unknown_never_invented_zero(self):
        for destroyed in [[],[dict(owner=0,data_id=35000001,x=3500,hp=0,health_at_destruction=10,native_destructor_observed=True)]]:
            self.report['battle_state']['destroyed_towers']=destroyed
            row=next(r for r in final_tower_rows(self.source,{},self.report) if r['owner']==0 and r['tower']=='princess0')
            self.assertIsNone(row['simulated']);self.assertIsNone(row['difference'])
            self.assertEqual(comparisons()['page_comparison'](self.source,{},self.report),('unknown',None))

    def test_hp_gains_and_losses_cannot_cancel_as_total_hp(self):
        towers=self.report['battle_state']['towers']
        next(t for t in towers if t['owner']==1 and t['x']==3500)['hp']=2258
        next(t for t in towers if t['owner']==1 and t['x']==14500)['hp']=2719
        self.assertEqual(sum(r['difference'] for r in final_tower_rows(self.source,{},self.report)),289)

    def test_ties_are_recorded_and_never_claim_physical_side_confirmation(self):
        self.source['decks'][0]['oracle_final_hp'].update(princess0=100,princess1=200)
        pair=[r for r in final_tower_rows(self.source,{},self.report) if r['owner']==1 and r['tower']!='king']
        self.assertTrue(all(r['page_pairing_ambiguous'] for r in pair))
        self.assertTrue(all(r['page_order']=='direct' and not r['page_side_verified'] for r in pair))

    def test_king_is_never_swapped_with_princess_or_other_player(self):
        self.source['decks'][0]['oracle_final_hp']['king']=1
        rows=final_tower_rows(self.source,{},self.report)
        self.assertEqual(rows[0]['difference'],4823)
        self.assertEqual(sum(r['difference'] for r in rows),248+4823)
        lower,_=damage_lower_bound(self.source,{},self.report)
        self.assertLessEqual(lower,sum(r['difference'] for r in rows))

if __name__=='__main__':unittest.main()

