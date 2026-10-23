"""Continue a hash-bound native checkpoint using fresh objects, never pointers."""
from pathlib import Path
import json,hashlib,re,copy
from source_completion import source_completed

SCHEMA='royale-replay.seed-locked-playback.v1'
FIELDS=('kind','source_tick_20hz','original_source_tick_20hz','base_data_id','proposed_native_owner','source_fields','source_position')
def semantics(events):return [{k:e.get(k) for k in FIELDS} for e in events]

def load(files,source_sha,plan):
    if plan.get('schema')!=SCHEMA or plan.get('source_sha256')!=source_sha:raise ValueError('locked playback source differs')
    seed=plan.get('random_seed')
    if type(seed)is not int or not -2**31<=seed<2**31:raise ValueError('invalid locked seed')
    prior=Path(plan['checkpoint_directory']);job=prior.parent.parent
    if (prior.name!='phone-playback' or prior.parent.name!='result' or not re.fullmatch('[a-f0-9-]{36}',job.name)
        or not job.parent.samefile(files/'local-imports')):raise ValueError('checkpoint is outside owned imports')
    raw=(prior/'skill-checkpoint-result.json').read_bytes()
    if not 0<len(raw)<=4*1024*1024 or hashlib.sha256(raw).hexdigest()!=plan.get('checkpoint_result_sha256'):raise ValueError('checkpoint proof changed')
    proof=json.loads(raw);state=json.loads((prior/'status.json').read_text())
    if (proof.get('schema')!='royale-replay.free-skill-checkpoint-result.v1' or proof.get('source_sha256')!=source_sha
        or proof.get('random_seed')!=seed or proof.get('fixed_actor_names')!={} or proof.get('checkpoint_tick')!=2800
        or proof.get('owner')!=1 or proof.get('tower_slot')!=1 or proof.get('minimum_exclusive')!=2417
        or not proof.get('simulation_test_completed') or proof.get('scene_published') is not False
        or state.get('state')!='stopped' or state.get('monitor_active') is not False or state.get('generation_released') is not True):raise ValueError('checkpoint is not a released qualifying free-skill test')
    attempt=plan.get('selected_attempt')
    matches=[s for s in proof.get('solutions',[]) if s.get('evidence',{}).get('attempt')==attempt]
    if len(matches)!=1 or not re.fullmatch(r'bootstrap-v3|ability-candidate-[0-9]{1,3}',attempt or ''):raise ValueError('checkpoint solution is not unique')
    report=json.loads((prior/(attempt+'-source-execution.json')).read_text())
    number='0' if attempt=='bootstrap-v3' else attempt.removeprefix('ability-candidate-')
    preparation=json.loads((prior/'native-preparation'/('ability-candidate-'+number+'.json')).read_text())
    point=next((p for p in report.get('skill_checkpoints',[]) if p['native_tick']==2800),None)
    count=sum(e['source_tick_20hz']<2800 for e in preparation['events'])
    if (report.get('error')!=126 or report.get('tick')!=2800 or report.get('hp_floor_violation') or not point
        or point['all_tower_hp'][1][1]<=2417 or point['all_tower_hp']!=matches[0].get('all_tower_hp')
        or preparation.get('source_sha256')!=source_sha or preparation['initialization_only']['rndSeed']!=seed
        or preparation.get('ability_actor_names')!={} or not source_completed(dict(report,error=0,finished=1),count)):
        raise ValueError('checkpoint source prefix is not native-verified')
    actors={str(r['event_index']):r['actors'][r['selected_ordinal']]['name'] for r in report.get('ability_observations',[])
        if r.get('phase')=='selected' and 0<=r.get('selected_ordinal',-1)<len(r.get('actors',[]))}
    expected_skills={str(i) for i,e in enumerate(preparation['events']) if e['kind']=='activate_ability' and e['source_tick_20hz']<2800}
    if set(actors)!=expected_skills or any(not re.fullmatch('[A-Za-z0-9_]{1,64}',name) for name in actors.values()):raise ValueError('checkpoint lacks skill identities')
    return dict(schema=SCHEMA,source_sha256=source_sha,random_seed=seed,checkpoint_tick=2800,checkpoint_hps=point['all_tower_hp'],prefix_count=count,
      prefix_actor_names=actors,source_events=semantics(preparation['events']),checkpoint_result_sha256=hashlib.sha256(raw).hexdigest())

def configure(preparation,contract):
    if preparation['source_sha256']!=contract['source_sha256'] or semantics(preparation['events'])!=contract['source_events']:raise ValueError('continuation source events differ')
    if preparation['initialization_only']['rndSeed']!=contract['random_seed']:raise ValueError('continuation changed locked seed')
    result=copy.deepcopy(preparation)
    result.update(ability_actor_names=dict(contract['prefix_actor_names']),ability_target_choices={},skill_checkpoint_tick=2800,stop_at_skill_checkpoint=False)
    return result

def verify_execution(report,contract):
    if report.get('tick',0)<2800:return False
    point=next((p for p in report.get('skill_checkpoints',[]) if p['native_tick']==2800),None)
    if not point or point['all_tower_hp']!=contract['checkpoint_hps']:raise ValueError('fresh continuation did not reproduce checkpoint HP')
    count=contract['prefix_count']
    if report.get('executed',0)<count or report.get('native_accepted',0)<count:raise ValueError('continuation prefix is not fully accepted')
    prefix=dict(error=0,finished=1,executed=count,native_accepted=count,commands=report.get('commands',[])[:count],dispatch=report.get('dispatch',[])[:count])
    if not source_completed(prefix,count):raise ValueError('continuation prefix receipts differ')
    actual={str(r['event_index']):r['actors'][r['selected_ordinal']]['name'] for r in report.get('ability_observations',[])
        if r.get('phase')=='selected' and 0<=r.get('selected_ordinal',-1)<len(r.get('actors',[]))}
    if any(actual.get(k)!=v for k,v in contract['prefix_actor_names'].items()):raise ValueError('continuation prefix selected another actor')
    return True
