import json,hashlib,sys,tempfile,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'device'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'windows-adaptation/project/official-web-replay'))
import locked_seed_playback as locked

class LockedSeedPlaybackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.files=Path(self.tmp.name)/'files'
  self.prior=self.files/'local-imports/11111111-1111-1111-1111-111111111111/result/phone-playback';(self.prior/'native-preparation').mkdir(parents=True)
  self.sha='a'*64;self.seed=-1701922553;self.hp=[[4824,1418,3052],[4824,2690,2946]]
  self.prep=dict(source_sha256=self.sha,initialization_only={'rndSeed':self.seed},ability_actor_names={},events=[dict(kind='activate_ability',source_tick_20hz=100),dict(kind='activate_ability',source_tick_20hz=200),dict(kind='play_card',source_tick_20hz=3000)])
  self.report=dict(error=126,tick=2800,executed=2,native_accepted=2,finished=0,commands=[dict(ct=189,c=dict(t=t,t2=t)) for t in (100,200)],
   dispatch=[dict(index=i,kind=189,tick=t,flags=3,code=0) for i,t in enumerate((100,200))],skill_checkpoints=[dict(native_tick=2800,all_tower_hp=self.hp)],hp_floor_violation=None,
   ability_observations=[dict(phase='selected',event_index=i,selected_ordinal=0,actors=[dict(name=name)]) for i,name in enumerate(('GoldenKnight','BossBandit'))])
  proof=dict(schema='royale-replay.free-skill-checkpoint-result.v1',source_sha256=self.sha,random_seed=self.seed,fixed_actor_names={},checkpoint_tick=2800,owner=1,tower_slot=1,minimum_exclusive=2417,
   simulation_test_completed=True,scene_published=False,solutions=[dict(evidence={'attempt':'ability-candidate-4'},all_tower_hp=self.hp)])
  self.write('skill-checkpoint-result.json',proof);self.write('status.json',dict(state='stopped',monitor_active=False,generation_released=True))
  self.write('ability-candidate-4-source-execution.json',self.report);self.write('native-preparation/ability-candidate-4.json',self.prep)
  self.plan=dict(schema=locked.SCHEMA,source_sha256=self.sha,random_seed=self.seed,checkpoint_directory=str(self.prior),selected_attempt='ability-candidate-4',checkpoint_result_sha256=hashlib.sha256((self.prior/'skill-checkpoint-result.json').read_bytes()).hexdigest())
 def write(self,name,value):(self.prior/name).write_text(json.dumps(value),encoding='utf-8')
 def contract(self):return locked.load(self.files,self.sha,self.plan)
 def test_verified_checkpoint_locks_only_prefix_and_continues_full_source(self):
  contract=self.contract();prep=locked.configure(self.prep,contract)
  self.assertEqual(prep['ability_actor_names'],{'0':'GoldenKnight','1':'BossBandit'})
  self.assertEqual(prep['events'],self.prep['events']);self.assertFalse(prep['stop_at_skill_checkpoint']);self.assertEqual(prep['initialization_only']['rndSeed'],self.seed)
  self.assertTrue(locked.verify_execution(self.report,contract));self.assertNotIn('ability_target_choices',self.prep)
 def test_tampered_proof_rejected(self):
  self.plan['checkpoint_result_sha256']='b'*64
  with self.assertRaises(ValueError):self.contract()
 def test_wrong_seed_rejected(self):
  self.plan['random_seed']=123
  with self.assertRaises(ValueError):self.contract()
 def test_unreleased_previous_job_rejected(self):
  self.write('status.json',dict(state='playing',monitor_active=True,generation_released=False))
  with self.assertRaises(ValueError):self.contract()
 def test_private_path_escape_rejected(self):
  self.plan['checkpoint_directory']=str(self.files/'other/result/phone-playback')
  with self.assertRaises(ValueError):self.contract()
 def test_retimed_source_rejected(self):
  prep=copy.deepcopy(self.prep);prep['events'][0]['source_tick_20hz']+=1
  with self.assertRaises(ValueError):locked.configure(prep,self.contract())
 def test_new_checkpoint_hp_mismatch_rejected(self):
  r=copy.deepcopy(self.report);r['skill_checkpoints'][0]['all_tower_hp'][1][1]-=1
  with self.assertRaises(ValueError):locked.verify_execution(r,self.contract())
 def test_wrong_skill_identity_rejected(self):
  r=copy.deepcopy(self.report);r['ability_observations'][0]['actors'][0]['name']='BossBandit'
  with self.assertRaises(ValueError):locked.verify_execution(r,self.contract())
 def test_rejected_prefix_command_rejected(self):
  r=copy.deepcopy(self.report);r['dispatch'][0]['code']=4
  with self.assertRaises(ValueError):locked.verify_execution(r,self.contract())
 def test_before_checkpoint_never_marked_verified(self):
  self.assertFalse(locked.verify_execution(dict(tick=100),self.contract()))
if __name__=='__main__':unittest.main()
