import unittest,copy
from test_elixir_gate import source,report,tower_stub
import ability_search as mod

class ApproximationTests(unittest.TestCase):
 def setUp(self):tower_stub()
 def page(self):return dict(source(),elixir_match_margin=.05)
 def test_historical_inputs_stay_strict(self):self.assertFalse(mod.elixir_check(source(),report(leaked=(143980,116627)))[0])
 def test_small_upper_error_can_be_near_but_never_exact(self):
  p=self.page();r=report(leaked=(143980,116627));self.assertTrue(mod.elixir_check(p,r)[0]);self.assertFalse(mod.elixir_strict_check(p,r));self.assertFalse(mod.terminal_hp_matches(p,{},r));self.assertGreater(mod.elixir_cost(p,r),0);self.assertLess(mod.elixir_cost(p,r),mod.ELIXIR_MISMATCH_COST)
 def test_lower_margin_is_bounded(self):
  self.assertTrue(mod.elixir_check(self.page(),report(leaked=(143200,116627)))[0]);self.assertFalse(mod.elixir_check(self.page(),report(leaked=(143199,116627)))[0])
 def test_upper_margin_is_exclusive(self):
  self.assertTrue(mod.elixir_check(self.page(),report(leaked=(144299,116627)))[0]);self.assertFalse(mod.elixir_check(self.page(),report(leaked=(144300,116627)))[0])
 def test_does_not_admit_one_elixir_wrong_skill(self):self.assertFalse(mod.elixir_check(self.page(),report(leaked=(153718,116627)))[0])
 def test_fractional_spend_is_always_rejected(self):
  r=report(leaked=(143980,116627));r['elixir'][0]['spent']=1299999;self.assertFalse(mod.elixir_check(self.page(),r)[0]);self.assertFalse(mod.elixir_strict_check(self.page(),r))
 def test_pause_prunes_only_after_relaxed_upper_bound(self):
  p=self.page();r=report(leaked=(143980,116627));self.assertLess(mod.damage_lower_bound(p,{},r)[0],mod.ELIXIR_MISMATCH_COST);self.assertGreaterEqual(mod.damage_lower_bound(p,{},report(leaked=(144300,116627)))[0],mod.ELIXIR_MISMATCH_COST)
 def test_same_tick_still_required(self):
  r=report(leaked=(153718,126627));r['elixir_window']=dict(first_tick=5320,leaked=[[143980,126627]]*20+[[153718,116627]]*21);self.assertFalse(mod.elixir_check(self.page(),r)[0])
 def test_strict_window_is_preferred_over_near_window(self):
  r=report(leaked=(153718,126627));r['elixir_window']=dict(first_tick=5339,leaked=[[143718,116627],[143980,116627]]);self.assertTrue(mod.elixir_strict_check(self.page(),r));self.assertEqual(mod.elixir_rows(self.page(),r)[0]['window_offset_ticks'],-1)
 def test_oversized_margin_is_rejected(self):
  with self.assertRaises(ValueError):mod.elixir_check(dict(source(),elixir_match_margin=.051),report())
