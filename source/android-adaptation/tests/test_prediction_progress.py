from pathlib import Path
import sys,unittest,json,tempfile,copy,io
base=Path.cwd();repo=Path(__file__).resolve().parents[2];sys.path[:0]=[str(repo/'android-adaptation/device'),str(repo/'windows-adaptation/project/official-web-replay')]
from prediction_progress import Progress
class ProgressTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.source={'actions':[{}],'decks':[{'proposed_native_owner':o,'oracle_elixir_leaked':v} for o,v in enumerate((14.37,11.66))]}
  self.candidate={'events':[{}],'initialization_only':{'rndSeed':-1701922553},'ability_target_choices':{'18':1}}
  self.progress=Progress(self.tmp.name,self.source,lambda *_:('same_towers',491),lambda *_:dict(hp_difference=491,time_difference_seconds=15.8))
  self.progress.begin(self.candidate,'candidate-1')
 def report(self):
  return dict(error=0,finished=1,tick=5656,executed=1,native_accepted=1,commands=[{'ct':153,'c':{'t':1,'t2':1}}],dispatch=[dict(index=0,kind=153,tick=1,flags=3,code=0)],elixir=[dict(leaked=v,current=10000,spent=20000,gained=30000) for v in (143718,116627)],diagnostics=[dict(index=0,tick=2457,owner=0,actor=dict(id=1,cost=2))],ability_observations=[dict(event_index=0,phase='selected',selected_ordinal=0,actors=[dict(name='GoldenKnight')])])
 def test_start_logs_seed_and_every_choice(self):
  r=json.loads((Path(self.tmp.name)/'prediction-process.jsonl').read_text(encoding='utf-8').splitlines()[0]);self.assertEqual(r['choices'],{'18':1});self.assertEqual(r['seed'],-1701922553)
 def test_complete_reports_actual_skill_cost_and_ticks(self):
  self.progress.finish(self.candidate,self.report());p=self.progress.snapshot();self.assertEqual(p['last']['tick'],5656);self.assertEqual(p['last']['skills'][0]['actor'],'GoldenKnight');self.assertEqual(p['last']['skills'][0]['cost'],2);self.assertEqual(p['best']['hp_difference'],491)
 def test_rejected_elixir_cannot_be_best(self):
  r=self.report();r['elixir'][0]['leaked']=153718;self.progress.finish(self.candidate,r);self.assertIsNone(self.progress.value['best']);self.assertIn('丢弃',self.progress.value['last']['reason'])
 def test_unknown_elixir_cannot_be_described_as_qualified(self):
  r=self.report();r.pop('elixir');self.progress.finish(self.candidate,r);self.assertIsNone(self.progress.value['best']);self.assertIn('未提供',self.progress.value['last']['reason'])
 def test_partial_ambiguity_lists_actual_actors(self):
  r=dict(error=112,finished=0,tick=2457,event_index=18,native_code=2,native_accepted=18,ability_observations=[dict(event_index=18,phase='eligible',actors=[dict(name='BossBandit'),dict(name='GoldenKnight')])]);self.progress.finish(self.candidate,r);p=self.progress.value;self.assertIsNone(p['best']);self.assertEqual(p['last']['next_actors'],['BossBandit','GoldenKnight']);self.assertIn('19',p['last']['reason'])
 def test_partial_overflow_records_prune(self):
  r=self.report();r.update(finished=0,error=112,native_code=2,event_index=18);r['elixir'][0]['leaked']=153718;self.progress.finish(self.candidate,r);self.assertIn('剪枝',self.progress.value['last']['reason'])
 def test_fractional_spend_never_qualified(self):
  r=self.report();r['elixir'][0]['spent']=19999;self.progress.finish(self.candidate,r);self.assertIsNone(self.progress.value['best'])
 def test_snapshot_is_detached_and_has_live_stage_epoch(self):
  p=self.progress.snapshot();p['history'].append('fake');self.assertEqual(self.progress.value['history'],[]);self.assertGreater(p['phase_started_at'],0)
 def test_telemetry_failure_does_not_break_simulation(self):
  self.progress.observe('finish',self.candidate,{'ability_observations':[None]});self.assertIn('narration_error',self.progress.value)
 def test_early_terminal_narration_does_not_blame_negative_skill_phrase(self):
  r=dict(error=114,finished=0,tick=200,executed=0,native_accepted=0,event_index=0,command_code=4)
  self.progress.finish(self.candidate,r);row=self.progress.value['last'];self.assertIn('failure_explanation',row)
  # Real negative phrases are classified by the shared hotfix70 regression.
  self.assertNotIn('技能所属单位无法唯一确定',row['failure_explanation'])
 def test_log_contains_entire_finished_branch(self):
  self.progress.finish(self.candidate,self.report());rows=[json.loads(x) for x in (Path(self.tmp.name)/'prediction-process.jsonl').read_text(encoding='utf-8').splitlines()];self.assertEqual(rows[-1]['choices'],{'18':1});self.assertEqual(rows[-1]['event_count'],1);self.assertTrue(rows[-1]['complete'])

if __name__=='__main__':unittest.main()
