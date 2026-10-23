from pathlib import Path
import sys,types,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests/hotfix65'),str(ROOT.parent/'windows-adaptation/project/official-web-replay')]
import test_seed_search as seed_tests
from test_elixir_gate import source,report,tower_stub
load=seed_tests.load

class ScoreBreakdownDisplayTests(unittest.TestCase):
    def setUp(self):tower_stub()

    def test_score_components_add_up_and_time_difference_is_not_raw_penalty(self):
        r=report(tick=267*20+99)
        r['battle_state']['towers'][0]['hp']-=701
        breakdown=load('page_breakdown')(source(),{},r)
        cost=load('page_comparison')(source(),{},r)[1]
        self.assertEqual((cost,breakdown['hp_difference'],breakdown['time_penalty'],breakdown['elixir_penalty']),(8601,701,7900,0))
        text=load('cost_text')(cost,breakdown)
        self.assertIn('综合差距 8601 = 塔血差 701 + 时间罚分 7900 + 圣水罚分 0',text)
        self.assertIn('终局晚4.95 秒',text)
        self.assertIn('蓝方溢出圣水',text);self.assertIn('红方溢出圣水',text)

    def test_zero_cost_still_shows_tolerated_time_and_actual_truncation_differences(self):
        r=report(leaked=(143799,116634),tick=267*20-1)
        breakdown=load('page_breakdown')(source(),{},r)
        cost=load('page_comparison')(source(),{},r)[1]
        text=load('cost_text')(cost,breakdown)
        self.assertIn('综合差距 0 = 塔血差 0 + 时间罚分 0 + 圣水罚分 0',text)
        self.assertIn('终局早0.05 秒',text)
        self.assertIn('差 +0.0099（通过网页截断范围）',text)
        self.assertIn('差 +0.0034（通过网页截断范围）',text)

    def test_elixir_failure_names_the_side_and_includes_the_actual_penalty(self):
        r=report(leaked=(153700,116600))
        breakdown=load('page_breakdown')(source(),{},r)
        cost=load('page_comparison')(source(),{},r)[1]
        self.assertEqual(breakdown['elixir_penalty'],1002000)
        text=load('cost_text')(cost,breakdown)
        self.assertIn('圣水罚分 1002000',text)
        self.assertIn('蓝方溢出圣水：网页 14.37 / 模拟 15.3700，差 +1.0000（不通过）',text)

    def test_missing_values_are_unknown_not_fake_zeroes(self):
        s=source(None);s.pop('source_duration_seconds')
        breakdown=load('page_breakdown')(s,{},dict(report(),elixir=None,elixir_at_page_end=None))
        text=load('cost_text')(0,breakdown)
        self.assertIn('时间罚分 未知',text);self.assertIn('终局时间差未知',text)
        self.assertIn('蓝方溢出圣水：缺少比对数据',text)

    def test_ready_queue_keeps_the_same_candidate_breakdown(self):
        java=(ROOT/'app/src/local/royale/replay/android/ConsoleActions.java').read_text()
        self.assertIn('check+state.optString("page_match_detail","")',java)
        self.assertIn("context['page_match_detail']=cost_text(difference,breakdown)",seed_tests.SOURCE)
