"""Bounded fresh-simulation tree search. Same final HP is an inference only."""
import copy
from source_completion import source_completed,source_failure


def terminal_hp_matches(source, preparation, report):
    from tower_profiles import bindings
    towers = (report.get('battle_state') or {}).get('towers', [])
    destroyed = [t for t in (report.get('battle_state') or {}).get('destroyed_towers', [])
                 if t.get('native_destructor_observed') is True and t.get('health_at_destruction',1)<=0 and t.get('hp')==0]
    for deck in source['decks']:
        owner = deck['proposed_native_owner']
        oracle = deck.get('oracle_final_hp') or {}
        for key, entry in zip(('king', 'princess0', 'princess1'), bindings(preparation)[owner]['spawn_entries']):
            if type(oracle.get(key)) is not int: return False
            found = [t for t in towers if (t['owner'], t['data_id'], t['x']) ==
                     (owner, entry['data_id'] & 0xffffffff, entry['grid_x']*500)]
            if not found:
                found = [t for t in destroyed if (t['owner'], t['data_id'], t['x']) ==
                         (owner, entry['data_id'] & 0xffffffff, entry['grid_x']*500)]
            # Absence is unknown, not guessed zero or a fabricated match.
            if len(found) != 1 or found[0]['hp'] != oracle[key]: return False
    return True


def search(preparation, execute, matches, *, max_attempts=256, cancelled=lambda:False):
    if type(max_attempts) is not int or not 1<=max_attempts<=4096:
        raise ValueError('invalid candidate search bound')
    pending=[{}];seen=set();history=[];ambiguous=False
    while pending and len(history)<max_attempts:
        if cancelled(): raise RuntimeError('技能候选搜索已取消；未提交后续候选')
        choices=pending.pop()
        key=tuple(sorted(choices.items()))
        if key in seen: continue
        seen.add(key)
        candidate=copy.deepcopy(preparation)
        candidate['ability_target_choices']=choices
        # execute MUST return only after clean, detached private-battle release.
        report,evidence=execute(candidate,len(history))
        history.append(dict(choices=choices,evidence=evidence,error=report.get('error'),
            native_accepted=report.get('native_accepted',0),failure=source_failure(report) if report.get('error') else None,
            first_settlement_tick=(report.get('battle_state') or {}).get('first_settlement_tick')))
        if source_completed(report,len(candidate['events'])):
            if not ambiguous or matches(candidate,report):
                return candidate,report,dict(attempts=history,ambiguous=ambiguous,
                    final_hp_matched=bool(ambiguous),inferred=bool(ambiguous),unique_solution_proven=False)
        elif report.get('error')==112 and type(report.get('native_code')) is int and 1<report['native_code']<=1024:
            index=report.get('event_index')
            if type(index) is not int or not 0<=index<len(candidate['events']) or candidate['events'][index]['kind']!='activate_ability':
                raise ValueError('ambiguous report is not a source ability')
            if str(index) in choices: continue  # Invalidated branch; never repeat.
            ambiguous=True
            pending.extend(dict(choices,**{str(index):v}) for v in reversed(range(report['native_code'])))
        elif not ambiguous:
            raise RuntimeError(source_failure(report))
    reason='搜索达到上限，仍有未验证组合' if pending else '已探索的技能分支均未通过整局校验；未走到的后续技能分歧尚未探索'
    if history:
        best=max(history,key=lambda row:row['native_accepted'])
        if best.get('failure'):reason+='。执行最远分支：'+best['failure']
    error=RuntimeError(reason+'；未发布回放，不把终局血量相同当作过程唯一正确。')
    error.search_report=dict(attempts=history,remaining=len(pending),exhaustive=False,
        explored_branches_exhausted=not pending,full_match_possibilities_exhausted=False)
    raise error
