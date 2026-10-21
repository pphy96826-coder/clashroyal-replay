"""Bounded fresh-simulation tree search. Same final HP is an inference only."""
import copy
from source_completion import source_completed,source_failure


KING_DATA_ID = 35000000


def final_tower_rows(source, preparation, report):
    """The one rule for every final-tower comparison (ability check and page tiers).

    Each of the six towers gets the page HP and the simulated HP. Simulated HP is
    the live tower's HP; 0 when its destruction was observed, or for a princess
    tower whose own king fell; None (unknown) when there is no such evidence.
    """
    from tower_profiles import bindings
    state = report.get('battle_state') or {}
    alive = state.get('towers', [])
    destroyed = [t for t in state.get('destroyed_towers', [])
                 if t.get('native_destructor_observed') is True and t.get('hp') == 0
                 and t.get('health_at_destruction', 0) <= 0]
    rows = []
    for deck in source['decks']:
        owner = deck['proposed_native_owner']
        oracle = deck.get('oracle_final_hp') or {}
        king_fell = any(t['owner'] == owner and t['data_id'] == KING_DATA_ID and t['hp'] == 0 for t in alive+destroyed)
        for key, entry in zip(('king', 'princess0', 'princess1'), bindings(preparation)[owner]['spawn_entries']):
            spot = (owner, entry['data_id'] & 0xffffffff, entry['grid_x']*500)
            found = [t for t in alive if (t['owner'], t['data_id'], t['x']) == spot]
            gone = [t for t in destroyed if (t['owner'], t['data_id'], t['x']) == spot]
            if len(found) == 1: simulated, evidence = found[0]['hp'], 'alive'
            elif not found and gone: simulated, evidence = 0, 'destroyed'
            elif not found and key != 'king' and king_fell: simulated, evidence = 0, 'king_fell'
            else: simulated, evidence = None, 'unknown'  # absent or ambiguous: never guessed
            page = oracle.get(key) if type(oracle.get(key)) is int else None
            rows.append(dict(owner=owner, tower=key, x=spot[2], page=page, simulated=simulated, evidence=evidence, page_order='direct'))
        _princess_order(rows[-2:])
    return rows


def _princess_order(pair):
    """RoyaleAPI's princess0/princess1 order is not consistently left/right in arena
    coordinates (seen both ways for the same side and orientation). Use the page's
    two values in swapped order only on HP evidence: the swap must give more exact
    matches of NONZERO HP than the page order. A destroyed (0) tower alone never
    decides the side. The order used is recorded per tower."""
    a, b = pair
    if None in (a['page'], b['page'], a['simulated'], b['simulated']): return
    def evidence(first, second):
        return (a['simulated'] == first != 0) + (b['simulated'] == second != 0)
    def exact(first, second):
        return (a['simulated'] == first) + (b['simulated'] == second)
    if (evidence(b['page'], a['page']) > evidence(a['page'], b['page'])
            and exact(b['page'], a['page']) >= exact(a['page'], b['page'])):
        a['page'], b['page'] = b['page'], a['page']
        a['page_order'] = b['page_order'] = 'swapped'


def terminal_hp_matches(source, preparation, report):
    rows = final_tower_rows(source, preparation, report)
    return bool(rows) and all(r['page'] is not None and r['simulated'] == r['page'] for r in rows)


def search(preparation, execute, matches, *, max_attempts=256, cancelled=lambda:False,
           closest=None, stop_early=lambda:False):
    """closest(candidate, report) -> sortable key (lower is closer). When given,
    the closest fully executed candidate is kept: stop_early() returns it at
    once, and it is returned instead of an error when no branch matches. The
    result then says final_hp_matched=False, closest_selected=True."""
    if type(max_attempts) is not int or not 1<=max_attempts<=4096:
        raise ValueError('invalid candidate search bound')
    pending=[{}];seen=set();history=[];ambiguous=False;best=None
    def closest_result(stopped):
        key,candidate,report,index=best
        return candidate,report,dict(attempts=history,ambiguous=ambiguous,final_hp_matched=False,inferred=True,
            unique_solution_proven=False,closest_selected=True,stopped_by_user=stopped,chosen_attempt=index,remaining=len(pending))
    while pending and len(history)<max_attempts:
        if cancelled(): raise RuntimeError('技能候选搜索已取消；未提交后续候选')
        if best is not None and stop_early(): return closest_result(True)
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
                    final_hp_matched=bool(ambiguous),inferred=bool(ambiguous),unique_solution_proven=False,
                    chosen_attempt=len(history)-1)
            if closest is not None:
                key=closest(candidate,report)
                if best is None or key<best[0]:best=(key,candidate,report,len(history)-1)
        elif report.get('error')==112 and type(report.get('native_code')) is int and 1<report['native_code']<=1024:
            index=report.get('event_index')
            if type(index) is not int or not 0<=index<len(candidate['events']) or candidate['events'][index]['kind']!='activate_ability':
                raise ValueError('ambiguous report is not a source ability')
            if str(index) in choices: continue  # Invalidated branch; never repeat.
            ambiguous=True
            pending.extend(dict(choices,**{str(index):v}) for v in reversed(range(report['native_code'])))
        elif not ambiguous:
            raise RuntimeError(source_failure(report))
    if best is not None:return closest_result(False)
    reason='搜索达到上限，仍有未验证组合' if pending else '已探索的技能分支均未通过整局校验；未走到的后续技能分歧尚未探索'
    if history:
        best=max(history,key=lambda row:row['native_accepted'])
        if best.get('failure'):reason+='。执行最远分支：'+best['failure']
    error=RuntimeError(reason+'；未发布回放，不把终局血量相同当作过程唯一正确。')
    error.search_report=dict(attempts=history,remaining=len(pending),exhaustive=False,
        explored_branches_exhausted=not pending,full_match_possibilities_exhausted=False)
    raise error
