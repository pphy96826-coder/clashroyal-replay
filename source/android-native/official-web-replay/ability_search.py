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


# The page records the match length in whole seconds. On 13 replays whose six
# towers matched the page exactly, simulated end tick / 20 was within one second
# of it (-19..+8 ticks), so +-20 ticks counts as the same end time.
TIME_TOLERANCE_TICKS = 20
# End time weighs more than tower HP: each tick beyond the tolerance costs as much
# as 100 HP of tower difference (one second = 2000 HP).
TIME_WEIGHT_PER_TICK = 100


def terminal_time(source, report):
    """Page match length vs. the simulated end tick (only for a finished battle)."""
    seconds = source.get('source_duration_seconds')
    tick = report.get('tick') if report.get('finished') == 1 and type(report.get('tick')) is int else None
    if type(seconds) not in (int, float) or tick is None:
        return dict(page_ticks=None, simulated_tick=tick, delta_ticks=None, excess_ticks=None)
    page_ticks = int(round(seconds * 20))
    delta = tick - page_ticks
    return dict(page_ticks=page_ticks, simulated_tick=tick, delta_ticks=delta,
                excess_ticks=max(0, abs(delta) - TIME_TOLERANCE_TICKS))


# The page shows each player's elixir leaked (the battle log's elixirLeaked) with
# two decimals; the engine keeps it exactly (x10000). Card plays and their times
# come from the page, so leaked elixir barely depends on the random seed: it
# follows from the elixir actually spent, above all which hero paid for each
# ability. It is measured at the page's end time, wherever the run itself ends:
# a cheaper wrong hero leaks more by then; a dearer one leaves too little elixir
# (a later card is under-charged, never refused, in replay) and leaks less.
# A run must leak the page's amount for both players to be accepted.
ELIXIR_SCALE = 10000
ELIXIR_TOLERANCE = 0.01   # the page truncates to two decimals (0.9579 shows 0.95)


def elixir_matches(simulated, page):
    """The page's value is the engine's leaked elixir truncated to two decimals,
    e.g. 1.5028 -> 1.50 and 0.9579 -> 0.95 on a replay whose six towers match."""
    return page - 1e-6 <= simulated < page + ELIXIR_TOLERANCE - 1e-6
# Ranking: any run whose leaked elixir differs is worse than every run that
# matches; among those, each elixir of difference costs 2000 (like one second).
ELIXIR_MISMATCH_COST = 1000000
ELIXIR_WEIGHT = 2000


def elixir_rows(source, report):
    """Per player: page and simulated elixir leaked, plus the engine's totals.

    implied_ability_and_final: elixir the page's leaked value leaves for
    abilities plus the elixir still held at the end, i.e. this run's ability
    spend + final elixir corrected by the leaked difference (the generated total
    and the card spend come from this run; card plays are the page's)."""
    native, at = elixir_snapshot(report)
    window_tick, window_values, page_end_tick = elixir_window_match(source, report)
    rows = []
    for deck in source.get('decks', []):
        owner = deck['proposed_native_owner']
        page = deck.get('oracle_elixir_leaked')
        page = float(page) if type(page) in (int, float) else None
        entry = native[owner] if isinstance(native, list) and len(native) == 2 and isinstance(native[owner], dict) else None
        simulated = entry['leaked'] / ELIXIR_SCALE if entry and type(entry.get('leaked')) is int else None
        row = dict(owner=owner, page=page, simulated=simulated, measured_at=at)
        if entry:
            row.update(spent=entry.get('spent', 0) / ELIXIR_SCALE, gained=entry.get('gained', 0) / ELIXIR_SCALE,
                       final=entry.get('current', 0) / ELIXIR_SCALE)
        ability = ability_spend(report, owner)
        if ability is not None:
            row['ability_spent'] = ability
            if entry and simulated is not None and page is not None:
                row['implied_ability_and_final'] = round(ability + row['final'] + simulated - page, 2)
        row['matched'] = None if page is None or simulated is None else elixir_matches(simulated, page)
        if window_tick is not None:
            # Both players match the page at one tick within the end-time tolerance.
            row.update(simulated=window_values[owner] / ELIXIR_SCALE, matched=True, measured_at='page_end_window',
                       window_offset_ticks=window_tick - page_end_tick)
        if elixir_shortfall(report, owner):
            row.update(shortfall=True, matched=False)
        rows.append(row)
    return rows


def elixir_window_match(source, report):
    """The page's end time is whole seconds, so the match may have ended up to
    TIME_TOLERANCE_TICKS either side of it. (tick, leaked per owner, page end
    tick) of the tick in that window nearest the page's end where BOTH players'
    leaked elixir matches the page at once; (None, None, page end) if none."""
    window = report.get('elixir_window')
    checkpoint = report.get('elixir_at_page_end')
    page_end = checkpoint.get('tick') if isinstance(checkpoint, dict) else None
    pages = {d['proposed_native_owner']: d.get('oracle_elixir_leaked') for d in source.get('decks', [])}
    if (not isinstance(window, dict) or type(window.get('first_tick')) is not int or type(page_end) is not int
            or sorted(pages) != [0, 1] or any(type(v) not in (int, float) for v in pages.values())):
        return None, None, page_end
    ticks = [(window['first_tick'] + k, values) for k, values in enumerate(window.get('leaked') or [])
             if isinstance(values, list) and len(values) == 2]
    for tick, values in sorted(ticks, key=lambda item: abs(item[0] - page_end)):
        if abs(tick - page_end) <= TIME_TOLERANCE_TICKS and all(
                elixir_matches(values[owner] / ELIXIR_SCALE, float(pages[owner])) for owner in (0, 1)):
            return tick, values, page_end
    return None, None, page_end


def elixir_snapshot(report):
    """(per-player totals, where) compared with the page: the snapshot taken when
    the run reached the page's end tick ('page_end'); else the totals where the run
    stopped ('battle_end' if the battle ended before the page's end time, else
    'paused' for a run stopped at an ambiguity, which is only a lower bound)."""
    checkpoint = report.get('elixir_at_page_end')
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get('sides'), list):
        return checkpoint['sides'], 'page_end'
    return report.get('elixir'), 'battle_end' if report.get('finished') == 1 else 'paused'


def elixir_shortfall(report, owner):
    """True when this player was charged a fraction of an elixir: every card and
    ability costs whole elixir, so a fractional spent total means a play was made
    without enough elixir, which a real player cannot do. (No such run has been
    seen; if the engine refused the play instead, the run already fails.)"""
    native = report.get('elixir')
    entry = native[owner] if isinstance(native, list) and len(native) == 2 and isinstance(native[owner], dict) else None
    return bool(entry) and type(entry.get('spent')) is int and entry['spent'] % ELIXIR_SCALE != 0


def ability_spend(report, owner):
    """Elixir this run paid for its abilities (actor costs from the diagnostics)."""
    costs = [d['actor'].get('cost') for d in report.get('diagnostics') or []
             if d.get('owner') == owner and isinstance(d.get('actor'), dict)]
    if not costs or any(type(c) is not int or c < 0 for c in costs): return None if costs else 0
    return sum(costs)


def elixir_check(source, report):
    """(matched, difference): matched is None when the page or the run lacks
    the value; difference is the summed |simulated - page| leaked elixir."""
    rows = [r for r in elixir_rows(source, report) if r['matched'] is not None]
    if not rows: return None, None
    compared = [r for r in rows if r['page'] is not None and r['simulated'] is not None]
    return all(r['matched'] for r in rows), round(sum(abs(r['simulated'] - r['page']) for r in compared), 4)


def elixir_cost(source, report):
    """Ranking cost of the leaked-elixir difference (0 when matched or unknown)."""
    matched, difference = elixir_check(source, report)
    if matched in (True, None): return 0
    return ELIXIR_MISMATCH_COST + int(round(ELIXIR_WEIGHT * difference))


def terminal_hp_matches(source, preparation, report):
    """Exact: all six towers at the page HP, the battle ends at the page's time,
    and both players leaked the page's elixir."""
    rows = final_tower_rows(source, preparation, report)
    if not rows or not all(r['page'] is not None and r['simulated'] == r['page'] for r in rows):
        return False
    if terminal_time(source, report)['excess_ticks'] not in (0, None): return False
    return elixir_check(source, report)[0] in (True, None)


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
    # Leaked elixir never decreases either: a player already past the page's
    # amount at the pause can only end further from it.
    for row in elixir_rows(source, report):
        if row.get('shortfall'):
            total += ELIXIR_MISMATCH_COST
            break
        if row['page'] is not None and row['simulated'] is not None and row['simulated'] >= row['page'] + ELIXIR_TOLERANCE - 1e-6:
            total += ELIXIR_MISMATCH_COST + int(round(ELIXIR_WEIGHT * (row['simulated'] - row['page'])))
            break
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
        # Leaked elixir past the page's (or a play without enough elixir) means the
        # heroes are wrong: always dropped, whatever the tower bound does.
        if lower is not None and lower >= ELIXIR_MISMATCH_COST: return True
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
                cost=key[0] if isinstance(key,tuple) else key
                if type(cost) in (int,float) and cost>=ELIXIR_MISMATCH_COST:
                    # Leaked elixir differs from the page: impossible, never kept as closest.
                    row['elixir_rejected']=True;since_improved+=1
                elif best is None or key<best[0]:best=(key,candidate,report,len(history)-1);since_improved=0
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
