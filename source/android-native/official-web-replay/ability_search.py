"""Bounded fresh-simulation tree search. Same final HP is an inference only."""
import copy
from source_completion import source_completed,source_failure


KING_DATA_ID = 35000000


def _uid(tower):
    """Native records print live tower IDs unsigned but destroyed ones signed
    (Royal Chef 3191249505 == -1103717791); compare them as unsigned 32-bit."""
    return tower['data_id'] & 0xffffffff


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
        entries = bindings(preparation)[owner]['spawn_entries']
        # Tower troops other than King/Princess (e.g. Royal Chef) have their own king ID.
        king_ids = {KING_DATA_ID, entries[0]['data_id'] & 0xffffffff}
        king_fell = any(t['owner'] == owner and _uid(t) in king_ids and t['hp'] == 0 for t in alive+destroyed)
        for key, entry in zip(('king', 'princess0', 'princess1'), entries):
            spot = (owner, entry['data_id'] & 0xffffffff, entry['grid_x']*500)
            found = [t for t in alive if (t['owner'], _uid(t), t['x']) == spot]
            gone = [t for t in destroyed if (t['owner'], _uid(t), t['x']) == spot]
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


def damage_lower_bound(source, preparation, report):
    """Admissible bound on the final six-tower difference from a PARTIAL run.

    Tower HP never rises, so a tower already below its page HP ends at least that
    far below it: sum(max(0, page - current)). The two princess towers of a side
    use whichever page order gives the smaller bound (the page order is not
    reliably left/right). Also returns the observed HP for the monotonic check.
    """
    rows = final_tower_rows(source, preparation, report)
    def gap(row, page):
        if page is None or row['simulated'] is None: return 0
        return max(0, page - row['simulated'])
    total = 0
    for owner in sorted({r['owner'] for r in rows}):
        king, a, b = [r for r in rows if r['owner'] == owner]
        total += gap(king, king['page'])
        total += min(gap(a, a['page']) + gap(b, b['page']), gap(a, b['page']) + gap(b, a['page']))
    observed = {(r['owner'], r['tower']): r['simulated'] for r in rows if r['simulated'] is not None}
    return total, observed


def search(preparation, execute, matches, *, max_attempts=256, cancelled=lambda:False,
           closest=None, stop_early=lambda:False, initial=None, bound=None, incumbent=None, patience=None):
    """Best-first branch and bound over ambiguous ability targets.

    closest(candidate, report) -> sortable key (lower is closer); key[0] is the
    six-tower HP difference. When given, the closest fully executed candidate is
    kept: stop_early() returns it at once, and it is returned instead of an error
    when no branch matches (final_hp_matched=False, closest_selected=True).
    initial: ability choices to try first; later ambiguities still branch from it.
    bound(candidate, report) -> (lower_bound, observed_hp) for a run paused at an
    ambiguity. Branches are explored lowest bound first (deeper first on ties) and
    a branch is dropped when its bound proves it cannot match (exact search) or
    cannot beat the closest complete run. Pruning switches off by itself if any
    tower HP is ever seen to rise, since the bound then no longer holds.
    incumbent: best six-tower difference already found elsewhere (another seed);
    branches whose bound reaches it are dropped too.
    patience: in closest mode, once every remaining branch has a positive bound
    (an exact match is impossible at this seed) and the closest result has not
    improved for this many runs, return the closest result instead of continuing.
    """
    import heapq
    if type(max_attempts) is not int or not 1<=max_attempts<=4096:
        raise ValueError('invalid candidate search bound')
    # The initial combination is tried first (deepest); if it dies under this seed
    # the search falls back to the empty root instead of giving the seed up.
    pending=[(0,-len(initial or {}),0,dict(initial or {}),None)];order=1
    if initial:pending.append((0,0,order,{},None));order+=1
    seen=set();history=[];ambiguous=bool(initial);best=None;pruned=0;monotonic=True;since_improved=0
    def closest_result(stopped):
        key,candidate,report,index=best
        return candidate,report,dict(attempts=history,ambiguous=ambiguous,final_hp_matched=False,inferred=True,
            unique_solution_proven=False,closest_selected=True,stopped_by_user=stopped,chosen_attempt=index,
            remaining=len(pending),pruned=pruned,bound_monotonic=monotonic,exact_impossible=exact_impossible())
    def best_difference():
        if best is None: return None
        difference=best[0][0] if isinstance(best[0],tuple) else best[0]
        return difference if type(difference) in (int,float) else None
    def hopeless(lower):
        if not monotonic or lower is None: return False
        if closest is None: return lower>0  # exact match needs every tower at page HP
        limits=[v for v in (best_difference(),incumbent) if type(v) in (int,float)]
        return bool(limits) and lower>=min(limits)
    def exact_impossible():
        return monotonic and bound is not None and best is not None and all(item[0]>0 for item in pending)
    while pending and len(history)<max_attempts:
        if cancelled(): raise RuntimeError('技能候选搜索已取消；未提交后续候选')
        if best is not None and stop_early(): return closest_result(True)
        if patience is not None and closest is not None and since_improved>=patience and exact_impossible():
            return closest_result(False)
        lower,_,_,choices,parent_hp=heapq.heappop(pending)
        if hopeless(lower): pruned+=1; continue
        key=tuple(sorted(choices.items()))
        if key in seen: continue
        seen.add(key)
        candidate=copy.deepcopy(preparation)
        candidate['ability_target_choices']=choices
        # execute MUST return only after clean, detached private-battle release.
        report,evidence=execute(candidate,len(history))
        row=dict(choices=choices,evidence=evidence,error=report.get('error'),
            native_accepted=report.get('native_accepted',0),failure=source_failure(report) if report.get('error') else None,
            first_settlement_tick=(report.get('battle_state') or {}).get('first_settlement_tick'))
        history.append(row)
        if source_completed(report,len(candidate['events'])):
            if not ambiguous or matches(candidate,report):
                return candidate,report,dict(attempts=history,ambiguous=ambiguous,
                    final_hp_matched=bool(ambiguous),inferred=bool(ambiguous),unique_solution_proven=False,
                    chosen_attempt=len(history)-1,pruned=pruned,bound_monotonic=monotonic)
            if closest is not None:
                key=closest(candidate,report)
                if best is None or key<best[0]:best=(key,candidate,report,len(history)-1);since_improved=0
                else:since_improved+=1
        elif report.get('error')==112 and type(report.get('native_code')) is int and 1<report['native_code']<=1024:
            index=report.get('event_index')
            if type(index) is not int or not 0<=index<len(candidate['events']) or candidate['events'][index]['kind']!='activate_ability':
                raise ValueError('ambiguous report is not a source ability')
            if str(index) in choices: continue  # Invalidated branch; never repeat.
            ambiguous=True
            child_lower,observed=0,None
            since_improved+=1
            if bound is not None:
                child_lower,observed=bound(candidate,report)
                row['lower_bound']=child_lower
                if parent_hp and any(observed.get(t,v)>v for t,v in parent_hp.items()):monotonic=False
                if hopeless(child_lower): pruned+=1; continue
            for v in range(report['native_code']):
                # Deeper (more decided) branches first among equal bounds, then lower ordinal.
                heapq.heappush(pending,(child_lower,-len(choices)-1,order,dict(choices,**{str(index):v}),observed));order+=1
        elif not ambiguous:
            raise RuntimeError(source_failure(report))
    if best is not None:return closest_result(False)
    reason='搜索达到上限，仍有未验证组合' if pending else '已探索的技能分支均未通过整局校验；未走到的后续技能分歧尚未探索'
    if history:
        best=max(history,key=lambda row:row['native_accepted'])
        if best.get('failure'):reason+='。执行最远分支：'+best['failure']
    error=RuntimeError(reason+'；未发布回放，不把终局血量相同当作过程唯一正确。')
    error.search_report=dict(attempts=history,remaining=len(pending),exhaustive=False,pruned=pruned,bound_monotonic=monotonic,
        explored_branches_exhausted=not pending,full_match_possibilities_exhausted=False)
    raise error
