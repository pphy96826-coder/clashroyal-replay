"""Bounded fresh-simulation tree search. Same final HP is an inference only."""
import copy
from source_completion import source_completed,source_failure


def terminal_hp_matches(source, preparation, report):
    from tower_profiles import oracle_tower_pairs
    for deck in source['decks']:
        pairs=oracle_tower_pairs(deck,preparation,report.get('battle_state') or {})
        if pairs is None or any(expected!=actual for _,expected,actual in pairs):return False
    return True


def search(preparation, execute, matches, *, max_attempts=256, cancelled=lambda:False,
           allow_nonmatching_complete=False, score=None, on_best=lambda *args:None,
           stop_requested=lambda:False, boundary_errors=()):
    """Resolve legal actors before independently searching stochastic seeds.

    For an RNG-eligible source, a completely accepted branch is playable even
    when its current seed misses terminal HP. Requiring HP equality here would
    prevent the outer seed search from ever receiving its first complete run.
    Partial/rejected branches never qualify; the native completion gate stays.
    """
    if type(max_attempts) is not int or not 1<=max_attempts<=4096:
        raise ValueError('invalid candidate search bound')
    pending=[{}];seen=set();history=[];ambiguous=False;best=None;stopped=False;bounded=False
    while pending and len(history)<max_attempts:
        if cancelled(): raise RuntimeError('技能候选搜索已取消；未提交后续候选')
        if best is not None and stop_requested():stopped=True;break
        choices=pending.pop()
        key=tuple(sorted(choices.items()))
        if key in seen: continue
        seen.add(key)
        candidate=copy.deepcopy(preparation)
        candidate['ability_target_choices']=choices
        # execute MUST return only after clean, detached private-battle release.
        try:report,evidence=execute(candidate,len(history))
        except boundary_errors:
            if best is None:raise
            stopped=bool(stop_requested());bounded=not stopped;break
        history.append(dict(choices=choices,evidence=evidence,error=report.get('error'),
            native_accepted=report.get('native_accepted',0),failure=source_failure(report) if report.get('error') else None,
            first_settlement_tick=(report.get('battle_state') or {}).get('first_settlement_tick')))
        if source_completed(report,len(candidate['events'])):
            matched=bool(matches(candidate,report))
            if score is not None:
                value=score(candidate,report)
                if type(value) is not int or value<0:raise ValueError('invalid complete skill HP difference')
                history[-1].update(complete=True,hp_difference=value,final_hp_matched=matched)
                if best is None or value<best[0]:
                    best=(value,candidate,report,evidence,matched)
                    on_best(candidate,report,value,evidence)
                if value==0:break
                continue
            if not ambiguous or matched or allow_nonmatching_complete:
                return candidate,report,dict(attempts=history,ambiguous=ambiguous,
                    final_hp_matched=matched,inferred=bool(ambiguous),unique_solution_proven=False,
                    complete_branch_before_seed_search=bool(allow_nonmatching_complete and not matched))
        elif report.get('error')==112 and type(report.get('native_code')) is int and 1<report['native_code']<=1024:
            index=report.get('event_index')
            if type(index) is not int or not 0<=index<len(candidate['events']) or candidate['events'][index]['kind']!='activate_ability':
                raise ValueError('ambiguous report is not a source ability')
            if str(index) in choices: continue  # Invalidated branch; never repeat.
            ambiguous=True
            pending.extend(dict(choices,**{str(index):v}) for v in reversed(range(report['native_code'])))
        elif not ambiguous:
            raise RuntimeError(source_failure(report))
    if best is not None:
        value,candidate,report,evidence,matched=best
        return candidate,report,dict(attempts=history,ambiguous=ambiguous,inferred=bool(ambiguous),
            final_hp_matched=matched,unique_solution_proven=False,selected_evidence=evidence,
            selected_hp_difference=value,skill_first=True,remaining=len(pending),
            explored_branches_exhausted=not pending,stopped_by_user=stopped,
            budget_exhausted=bounded or bool(pending and len(history)>=max_attempts),
            complete_branch_before_seed_search=True)
    reason='搜索达到上限，仍有未验证组合' if pending else '已探索的技能分支均未通过整局校验；未走到的后续技能分歧尚未探索'
    if history:
        best=max(history,key=lambda row:row['native_accepted'])
        if best.get('failure'):reason+='。执行最远分支：'+best['failure']
    error=RuntimeError(reason+'；未发布回放，不把终局血量相同当作过程唯一正确。')
    error.search_report=dict(attempts=history,remaining=len(pending),exhaustive=False,
        explored_branches_exhausted=not pending,full_match_possibilities_exhausted=False)
    raise error


def fixed_choice_trial(preparation, choices, execute, matches):
    """Fresh native resolution of fixed event ordinals; never reuse actor pointers."""
    candidate=copy.deepcopy(preparation)
    candidate['ability_target_choices']=copy.deepcopy(choices)
    report,evidence=execute(candidate,0)
    if not source_completed(report,len(candidate['events'])):
        raise RuntimeError(source_failure(report))
    return candidate,report,dict(inferred=bool(choices),final_hp_matched=bool(matches(candidate,report)),
        unique_solution_proven=False,selected_evidence=evidence,fixed_skill_choices=True)
