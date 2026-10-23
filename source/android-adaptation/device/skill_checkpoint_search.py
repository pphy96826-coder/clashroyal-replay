"""Enumerate fresh legal skill prefixes without publishing any replay scene."""
import copy
from source_completion import source_completed,source_failure

def requested_seed(test,original,plan):
    value=test.get('random_seed',original)
    if type(value)is not int or value not in [original]+list(plan):raise ValueError('checkpoint seed is outside verified deterministic plan')
    return value

def search(preparation,execute,*,tick=2800,owner=1,slot=1,minimum_exclusive=2417,max_attempts=32,cancelled=lambda:False):
    if preparation.get('ability_actor_names'):raise ValueError('free checkpoint search cannot lock actors')
    pending=[{}];seen=set();history=[];solutions=[]
    while pending and len(history)<max_attempts:
        if cancelled():raise RuntimeError('checkpoint search cancelled')
        choices=pending.pop();key=tuple(sorted(choices.items()))
        if key in seen:continue
        seen.add(key);candidate=copy.deepcopy(preparation)
        candidate.update(ability_target_choices=choices,ability_actor_names={},skill_checkpoint_tick=tick,prune_below_oracle=True)
        report,evidence=execute(candidate,len(history))
        row=dict(choices=choices,evidence=evidence,error=report.get('error'),tick=report.get('tick'),native_accepted=report.get('native_accepted'),
          hp_floor_violation=report.get('hp_floor_violation'),skill_checkpoints=report.get('skill_checkpoints',[]),failure=source_failure(report))
        history.append(row)
        if report.get('error')==112 and type(report.get('native_code'))is int and 1<report['native_code']<=1024:
            index=report.get('event_index')
            if type(index)is not int or not 0<=index<len(candidate['events']) or candidate['events'][index]['kind']!='activate_ability':raise ValueError('checkpoint ambiguity is not a source skill')
            if str(index) not in choices:pending.extend(dict(choices,**{str(index):v}) for v in reversed(range(report['native_code'])))
        elif report.get('error')==126:
            point=next((p for p in report.get('skill_checkpoints',[]) if p['native_tick']==tick),None)
            expected=sum(e['source_tick_20hz']<tick for e in candidate['events'])
            prefix=dict(report,error=0,finished=1)
            if not point or report.get('tick')!=tick or report.get('hp_floor_violation') or not source_completed(prefix,expected):raise ValueError('checkpoint native prefix receipts not complete')
            hp=point['all_tower_hp'][owner][slot]
            row.update(checkpoint_reached=True,checkpoint_hp=hp,goal_satisfied=hp>minimum_exclusive,prefix_receipts_verified=True)
            if row['goal_satisfied']:solutions.append(dict(choices=choices,evidence=evidence,checkpoint_hp=hp,all_tower_hp=point['all_tower_hp']))
    return dict(schema='royale-replay.free-skill-checkpoint-result.v1',simulation_test_completed=True,source_sha256=preparation['source_sha256'],
      checkpoint_tick=tick,owner=owner,tower_slot=slot,minimum_exclusive=minimum_exclusive,fixed_actor_names={},random_seed=preparation['initialization_only']['rndSeed'],
      attempts=history,solutions=solutions,remaining=len(pending),reachable_prefix_tree_exhausted=not pending,budget_exhausted=bool(pending),
      full_source_completed=False,future_skills_validated=False,scene_published=False)
