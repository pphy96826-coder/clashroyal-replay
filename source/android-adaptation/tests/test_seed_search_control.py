import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
spec=importlib.util.spec_from_file_location('seed_control',Path(__file__).resolve().parents[1]/'device/seed_search_control.py');control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
class Cancelled(Exception):pass
def run(seed,tier=2,difference=100):return ((tier,difference),seed,('exact','same_towers','same_winner','different')[tier],difference,{'fully_executed':True})
class SeedControlTests(unittest.TestCase):
 def choose(self,evaluate,stop=lambda:False,seeds=(8,9,10)):
  return control.choose_trials(run(7),seeds,evaluate,stop,lambda *_:None,Cancelled)
 def test_stop_before_next_trial_keeps_complete_initial_result(self):
  evaluate=Mock();best,attempts,stopped=self.choose(evaluate,lambda:True);self.assertEqual(best[1],7);self.assertEqual(attempts,[]);self.assertTrue(stopped);evaluate.assert_not_called()
 def test_inflight_completed_result_competes_before_stopping(self):
  stop=Mock(side_effect=[False,True]);best,attempts,stopped=self.choose(lambda seed,n:run(seed,1,10),stop);self.assertEqual(best[1],8);self.assertTrue(attempts[0]['executed']);self.assertTrue(stopped)
 def test_partial_calibration_never_replaces_best(self):
  evaluate=Mock(side_effect=control.BestRequested());best,attempts,stopped=self.choose(evaluate);self.assertEqual(best[1],7);self.assertFalse(attempts[0]['executed']);self.assertTrue(stopped)
 def test_full_cancellation_propagates(self):
  with self.assertRaises(Cancelled):self.choose(Mock(side_effect=Cancelled()))
 def test_exact_stops_without_running_remaining_seeds(self):
  evaluate=Mock(side_effect=lambda seed,n:run(seed,0,0));best,attempts,stopped=self.choose(evaluate);self.assertEqual(best[1],8);self.assertEqual(evaluate.call_count,1);self.assertFalse(stopped)
 def test_failed_trials_cannot_win(self):
  best,attempts,stopped=self.choose(Mock(side_effect=ValueError('invalid candidate')));self.assertEqual(best[1],7);self.assertTrue(all(not row['executed'] for row in attempts));self.assertFalse(stopped)
 def test_seed_identity_mismatch_is_rejected(self):
  best,attempts,_=self.choose(lambda *_:run(999,0,0));self.assertEqual(best[1],7);self.assertFalse(attempts[0]['executed'])
 def test_nonmonotonic_ranking_keeps_global_best_tested_run(self):
  values={8:run(8,3,1),9:run(9,1,300),10:run(10,2,10)};best,attempts,_=self.choose(lambda seed,n:values[seed]);self.assertEqual(best[1],9);self.assertEqual(len(attempts),3)
 def test_signal_requires_exact_source_generation_and_explicit_choice(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'signal.json';identity={'pid':123,'process_start_time':'42'};value={'schema':'royale-replay.accept-best-seed.v1','play_best':True,'source_sha256':'a'*64,'game_pid':123,'game_start_time':'42'}
   self.assertFalse(control.requested(path,'a'*64,identity));path.write_text(json.dumps(value));self.assertTrue(control.requested(path,'a'*64,identity))
   for key,other in [('play_best',False),('source_sha256','b'*64),('game_pid',124),('game_start_time','43'),('game_pid','123')]:
    bad=dict(value);bad[key]=other;path.write_text(json.dumps(bad));self.assertFalse(control.requested(path,'a'*64,identity))
 def test_malformed_or_oversized_signal_is_not_a_request(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'signal.json'
   for text in ('broken','null','['+' '*5000+']'):
    path.write_text(text);self.assertFalse(control.requested(path,'a'*64,{'pid':123,'process_start_time':'42'}))

class SeedEligibilityTests(unittest.TestCase):
 def reasons(self,events,cards=()):
  source={'decks':[{'source_side':s,'cards':[{'base_data_id':c,'form':f} for c,f in cards]} for s in ('team','opponent')]}
  return control.search_reasons({'events':events},source)
 def play(self,card,side='team',tick=1):return {'kind':'play_card','base_data_id':card,'source_side':side,'source_tick_20hz':tick}
 def ability(self,side='team',tick=2):return {'kind':'activate_ability','source_side':side,'source_tick_20hz':tick}
 def test_hunter_in_deck_without_play_does_not_trigger(self):self.assertEqual(self.reasons([],[ (26000044,'basic') ]),[])
 def test_hunter_actually_played_either_side_triggers(self):
  for side in ('team','opponent'):self.assertEqual(self.reasons([self.play(26000044,side)]),['hunter_played'])
 def test_skeleton_king_deployed_without_skill_does_not_trigger(self):self.assertEqual(self.reasons([self.play(26000069)]),[])
 def test_skeleton_king_skill_same_side_after_deployment_triggers(self):self.assertEqual(self.reasons([self.play(26000069),self.ability()]),['skeleton_king_ability'])
 def test_opponent_skill_cannot_be_assigned_to_skeleton_king(self):self.assertEqual(self.reasons([self.play(26000069),self.ability('opponent')]),[])
 def test_skill_before_skeleton_king_deployment_does_not_trigger(self):self.assertEqual(self.reasons([self.ability(tick=1),self.play(26000069,tick=2)]),[])
 def test_other_champion_skills_do_not_trigger(self):self.assertEqual(self.reasons([self.play(26000099),self.ability()]),[])
 def test_ambiguous_multiple_deployed_champions_do_not_invent_skeleton_skill(self):self.assertEqual(self.reasons([self.play(26000069),self.play(26000099),self.ability()]),[])
 def test_other_hero_form_also_prevents_ambiguous_skill_attribution(self):self.assertEqual(self.reasons([self.play(26000069),self.play(26000000),self.ability()],[(26000000,'hero')]),[])
 def test_both_reasons_are_unique_and_source_sorted(self):
  events=[self.ability(tick=4),self.play(26000044,tick=3),self.play(26000069,tick=2),self.play(26000044,tick=1)]
  self.assertEqual(self.reasons(events),['hunter_played','skeleton_king_ability'])
if __name__=='__main__':unittest.main()
