"""hotfix55-65 matching shared by the Windows console's native-call adapters.

Selection logic is copied from the pinned Android reference; Windows callbacks
own compilation/publication and never resubmit a published native task.
"""
import copy,hashlib,json,time
from pathlib import Path
from align_native_deal import calibrate,deck_fingerprint
from ability_search import search,terminal_hp_matches,damage_lower_bound,ELIXIR_MISMATCH_COST
SEED_ATTEMPTS=60
SCREEN_RUNS=12
SCREEN_RUNS_UNFIXED=12
REFINE_SEEDS=3
REFINE_RUNS=24
PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different','unknown')
class Cancelled(RuntimeError):pass
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write_new(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
def search_reasons(preparation,source):
    """Only actual Hunter plays or an identifiable Skeleton King ability.

    Deck membership alone is insufficient. Generic ability markers with
    multiple deployed ability-capable cards cannot identify a Skeleton King.
    """
    hunter,skeleton_king=26000044,26000069
    champions={26000065,26000069,26000072,26000074,26000077,26000093,26000099,26000103}
    capable={deck['source_side']:champions|{card['base_data_id'] for card in deck['cards'] if card.get('form')=='hero'} for deck in source['decks']}
    played={};reasons=[]
    for event in sorted(preparation['events'],key=lambda row:row['source_tick_20hz']):
        side=event['source_side'];card=event.get('base_data_id')
        if event['kind']=='play_card':
            if card==hunter and 'hunter_played' not in reasons:reasons.append('hunter_played')
            if card in capable.get(side,champions):played.setdefault(side,set()).add(card)
        elif event['kind']=='activate_ability' and played.get(side)=={skeleton_king}:
            if 'skeleton_king_ability' not in reasons:reasons.append('skeleton_king_ability')
    return reasons

def page_tower_comparison(source, preparation, report):
    """Compare a fully executed run with the page's final towers.

    Compare each king and source-ordered surviving princess HP, never totals.
    A compacted one-element HP list cannot establish which tower was destroyed.
    """
    from ability_search import final_tower_rows
    state=report.get('battle_state') or {}
    crowns={};page_crowns={};difference=0;same_towers=True;exact=True
    for deck in source['decks']:
        owner=deck['proposed_native_owner']
        rows=[r for r in final_tower_rows(source,preparation,report) if r['owner']==owner]
        pairs=[(r['tower'],r['page'],r['simulated']) for r in rows]
        if not pairs or any(expected is None or actual is None for _,expected,actual in pairs):return 'different',None
        for key,expected_hp,hp in pairs:
            difference+=abs(hp-expected_hp);exact=exact and hp==expected_hp
            same_towers=same_towers and (hp==0)==(expected_hp==0)
            loser=1-owner
            crowns[loser]=crowns.get(loser,0)+(3 if key=='king' and hp==0 else (1 if hp==0 and key!='king' else 0))
            page_crowns[loser]=page_crowns.get(loser,0)+(3 if key=='king' and expected_hp==0 else (1 if expected_hp==0 and key!='king' else 0))
    def winner(c):a,b=min(c.get(0,0),3),min(c.get(1,0),3);return 0 if a>b else 1 if b>a else None
    if exact:return 'exact',0
    if same_towers:return 'same_towers',difference
    if winner(crowns)==winner(page_crowns):return 'same_winner',difference
    return 'different',difference

def seed_search_policy(source,tier):
    reasons=search_reasons(dict(events=source.get('actions',[])),source)
    cards=sorted({'hunter' if 'hunter' in str(r).lower() else 'skeleton-king' for r in reasons})
    allowed=bool(reasons)
    return dict(eligible_cards=cards,allowed=allowed,search_needed=allowed and tier not in ('exact','unknown'),
                skip_reason='exact_match' if tier=='exact' else 'final_towers_unknown' if tier=='unknown' else None if allowed else 'no_seed_sensitive_card')

def time_note(context):
    seconds=context.get('page_time_difference_seconds')
    return '' if seconds is None else '，终局时间相差 '+('%.1f'%abs(seconds))+' 秒'

def elixir_note(context):
    return '，双方溢出圣水与网页一致' if context.get('page_elixir_matched') is True else ''

def cost_text(cost, breakdown=None):
    """Explain a single candidate's cost; never mix rows from different seeds."""
    from ability_search import ELIXIR_MISMATCH_COST
    if type(cost) is not int:return ''
    if breakdown is not None:
        hp=breakdown.get('hp_difference');delta=breakdown.get('time_difference_seconds')
        time_cost=breakdown.get('time_penalty');elixir_cost=breakdown.get('elixir_penalty')
        def value(v):return '未知' if v is None else str(v)
        timing='终局时间差未知' if delta is None else ('终局时间一致' if delta==0 else
            '终局'+('晚' if delta>0 else '早')+('%.2f'%abs(delta))+' 秒')
        parts=['综合差距 '+str(cost)+' = 塔血差 '+value(hp)+' + 时间罚分 '+value(time_cost)+' + 圣水罚分 '+value(elixir_cost),
               timing+'（允许 ±1 秒）']
        for owner in (0,1):
            row=next((r for r in breakdown.get('elixir',[]) if r.get('owner')==owner),{})
            page=row.get('page');simulated=row.get('simulated')
            label='蓝方' if owner==0 else '红方'
            if page is None or simulated is None:
                parts.append(label+'溢出圣水：缺少比对数据');continue
            verdict=('通过额外 %.2f 容差（近似）'%row.get('tolerance_margin',0) if row.get('strict_matched') is False else '通过网页截断范围') if row.get('matched') is True else '不通过' if row.get('matched') is False else '未判定'
            parts.append(label+'溢出圣水：网页 %.2f / 模拟 %.4f，差 %+.4f（%s）'%(page,simulated,simulated-page,verdict))
        return '（'+'；'.join(parts)+'）'
    if cost>=ELIXIR_MISMATCH_COST:return '（溢出圣水不一致，综合差距 '+str(cost-ELIXIR_MISMATCH_COST)+'）'
    return '（综合差距 '+str(cost)+'；分项尚未核验）'

def elixir_gate(source, preparation, report):
    """Final check before publication: both players' leaked elixir must equal the
    page. Returns None when it passes (or the page has no value), else the reason."""
    from ability_search import elixir_rows
    rows=elixir_rows(source,report)
    if all(r['matched'] in (True,None) for r in rows):return None
    parts=[]
    for r in rows:
        if r['matched'] is False:
            if r.get('shortfall'):
                parts.append(('蓝方' if r['owner']==0 else '红方')+' 有出牌或技能在圣水不足时执行（实付不是整数圣水），实战中不可能');continue
            part=('蓝方' if r['owner']==0 else '红方')+' 网页 '+('%.2f'%r['page'])+'，模拟 '+('%.2f'%r['simulated'])
            if r.get('measured_at')=='battle_end':part+='（模拟在网页结算时间前已结束）'
            if r.get('implied_ability_and_final') is not None and r.get('measured_at')=='page_end':
                part+='（按网页反推：技能费用 + 终局剩余圣水应为 '+('%.2f'%r['implied_ability_and_final'])+'，本次技能实付 '+str(r.get('ability_spent'))+'）'
            parts.append(part)
    return '截至网页结算时间，溢出圣水与网页不一致：'+'；'.join(parts)

def seed_search_note(attempts, allowed):
    if attempts:return '已另试 '+str(attempts)+' 个种子'
    if not allowed:return '卡组无骷髅之王或猎人，保留原种子，未搜索其他种子'
    return '保留原种子，未搜索其他种子'

def page_towers(source, preparation, report):
    from ability_search import final_tower_rows
    return final_tower_rows(source,preparation,report)

def page_comparison(source, preparation, report):
    """Rank a fully executed run against the page: (tier, cost).

    cost = summed six-tower HP difference + TIME_WEIGHT_PER_TICK x end-time ticks
    beyond the tolerance, so the match end time weighs more than tower HP, plus
    ELIXIR_MISMATCH_COST + ELIXIR_WEIGHT x elixir when either player's leaked
    elixir differs from the page. Towers that all match with a different end
    time or leaked elixir is not 'exact' but 'same_towers'."""
    from ability_search import terminal_time,TIME_WEIGHT_PER_TICK,elixir_check,elixir_cost,elixir_strict_check
    tier,difference=page_tower_comparison(source,preparation,report)
    if difference is None:return tier,difference
    excess=terminal_time(source,report)['excess_ticks'] or 0
    elixir_matched,_=elixir_check(source,report)
    if tier=='exact' and (excess>0 or elixir_matched is False or elixir_strict_check(source,report) is False):tier='same_towers'
    return tier,difference+TIME_WEIGHT_PER_TICK*excess+elixir_cost(source,report)

def page_breakdown(source, preparation, report):
    """Display values: tower HP difference and end-time difference in seconds."""
    from ability_search import terminal_time,elixir_check,elixir_rows,elixir_strict_check,elixir_margin,elixir_cost,TIME_WEIGHT_PER_TICK
    _,hp=page_tower_comparison(source,preparation,report)
    time=terminal_time(source,report)
    elixir_matched,elixir_difference=elixir_check(source,report)
    return dict(hp_difference=hp,time_difference_seconds=None if time['delta_ticks'] is None else round(time['delta_ticks']/20,2),
                time_penalty=None if time['excess_ticks'] is None else TIME_WEIGHT_PER_TICK*time['excess_ticks'],
                elixir_penalty=elixir_cost(source,report),
                elixir_matched=elixir_matched,elixir_strict_matched=elixir_strict_check(source,report),elixir_tolerance_margin=elixir_margin(source),elixir_leaked_difference=elixir_difference,elixir=elixir_rows(source,report),
                page_seconds=None if time['page_ticks'] is None else time['page_ticks']/20,
                simulated_seconds=None if time['simulated_tick'] is None else round(time['simulated_tick']/20,2))

def replay_key(source):
    """Identity of the MATCH, not of the saved HTML bytes: re-saving the same
    replay page changes the file hash but not the tag, decks or any play."""
    decks=sorted((d['source_side'],d['proposed_native_owner'],d.get('tower'),
                  [(c.get('base_card_key'),c.get('form'),c.get('source_level')) for c in d['cards']]) for d in source['decks'])
    actions=[(a['kind'],a['source_tick_20hz'],a['source_side'],a.get('base_card_key'),a.get('source_position')) for a in source['actions']]
    return hashlib.sha256(json.dumps([source['replay_tag'],decks,actions],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def seed_plan(match_key, original, count=SEED_ATTEMPTS, remembered=None):
    """Deterministic int32 seeds derived from the match identity (see replay_key).
    A seed remembered from an earlier run of the same match is tried first."""
    seeds=[remembered] if type(remembered) is int and remembered!=original else []
    target=count+len(seeds)
    for n in range(count*4):
        value=int.from_bytes(hashlib.sha256((match_key+':seed:'+str(n)).encode()).digest()[:4],'big')
        value=value-2**32 if value>=2**31 else value
        if value!=original and value not in seeds:seeds.append(value)
        if len(seeds)>=target:break
    return seeds


def match(source,aligned,delayed,destination,execute_attempt,deal_attempt,*,cancelled=lambda:False,stop_early=lambda:False,status=lambda *args,**kwargs:None,context=None):
    context={} if context is None else context
    preparation=destination/'matching';preparation.mkdir()
    files=destination;prep=None
    def probe(name):return deal_attempt(prep,name)
    def hp_bound(candidate,result):return damage_lower_bound(read(source),candidate,result)
    selected_candidate={}
    attempt_prefix=''
    # The user may end either search at any time and play the closest
    # complete result so far; checked between native attempts only.
    def seed_stop():return stop_early()
    snapshots={}
    from ability_search import ELIXIR_MISMATCH_COST
    def rank(tier,difference):
        # Only runs that leak the page's elixir can be published: they come first.
        return (type(difference) is int and difference>=ELIXIR_MISMATCH_COST,PAGE_MATCH_TIERS.index(tier),difference if difference is not None else 1<<30)
    def restore(search_result):
        chosen=search_result['attempts'][search_result['chosen_attempt']]['evidence']['attempt']
        selected_candidate.clear();selected_candidate.update(snapshots[chosen])
    # Hunter/Skeleton King decks: a wrong ability target changes the battle far
    # more than the shared random seed. Among fully executed ability
    # combinations (original seed) keep the one with the smallest page cost
    # (six-tower HP difference plus the weighted end-time difference), then search seeds with
    # that combination fixed. Other decks keep the strict exact-HP rule.
    closest_abilities=seed_search_policy(read(source),'different')['allowed']
    closest_best={}
    def hp_key(candidate,result):
        tier,difference=page_comparison(read(source),candidate,result)
        key=(difference if difference is not None else 1<<40,PAGE_MATCH_TIERS.index(tier))
        if difference is not None and difference<ELIXIR_MISMATCH_COST and not attempt_prefix and (not closest_best or key<closest_best['key']):closest_best.update(key=key,tier=tier,difference=difference)
        return key
    # The page's leaked elixir pins what each hero ability cost: a branch whose
    # leak has already passed the page's can never end at it. Keep the deepest
    # ability combination (original seed) still within it, even when that run
    # ended early, so the seed search can fix the elixir-consistent heroes.
    elixir_consistent={}
    def track_elixir(candidate,result):
        from ability_search import elixir_rows,ELIXIR_TOLERANCE,elixir_margin
        rows=[r for r in elixir_rows(read(source),result) if r['page'] is not None and r['simulated'] is not None]
        if not rows or any(r['simulated']>=r['page']+ELIXIR_TOLERANCE+elixir_margin(read(source))-1e-6 for r in rows):return
        choices=dict(candidate.get('ability_target_choices') or {})
        key=(len(choices),result.get('tick') if type(result.get('tick')) is int else 0)
        if choices and (not elixir_consistent or key>elixir_consistent['key']):elixir_consistent.update(key=key,choices=choices)
    def execute_candidate(candidate,number):
        nonlocal prep
        prep=preparation/(attempt_prefix+'ability-candidate-'+str(number)+'.json');write_new(prep,candidate)
        name=(attempt_prefix+'candidate-'+str(number)) if attempt_prefix else ('bootstrap-v3' if number==0 else 'ability-candidate-'+str(number))
        if not attempt_prefix:status('simulating','匹配技能分支 '+str(number+1)+'；尚无合格组合时不会放行。')
        result,candidate_receipt=execute_attempt(prep,name)
        selected_candidate.update(receipt=candidate_receipt,preparation=prep)
        snapshots[name]=dict(selected_candidate)
        if not attempt_prefix:track_elixir(candidate,result)
        return result,dict(attempt=name,preparation=str(prep))

    ability_error=None;elixir_rejection=None
    original_seed=aligned['initialization_only']['rndSeed']
    try:
        aligned,execution,search_result=search(aligned,execute_candidate,
            lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
            cancelled=cancelled,bound=hp_bound,
            closest=hp_key if closest_abilities else None,stop_early=seed_stop if closest_abilities else lambda:False,
            patience=24 if closest_abilities else None)
        restore(search_result)
        context.update(ability_closest_selected=bool(search_result.get('closest_selected')))
    except Exception as error:
        if hasattr(error,'search_report'):write_new(destination/'ability-search.json',error.search_report)
        if not getattr(error,'search_report',{}).get('explored_branches_exhausted'):raise
        ability_error=error
    if ability_error is None:
        write_new(destination/'ability-search.json',search_result)
        # Always compare the simulated end with the page (the search only does so for ambiguous abilities).
        tier,difference=page_comparison(read(source),aligned,execution)
        best=(rank(tier,difference),original_seed,tier,difference,(aligned,execution,search_result,dict(selected_candidate)))
        if type(difference) is int and difference>=ELIXIR_MISMATCH_COST:
            # Leaked elixir differs: the heroes are wrong, so this run is discarded, not kept as a fallback.
            elixir_rejection=elixir_gate(read(source),aligned,execution)
            tier,difference='different',None
            best=((True,len(PAGE_MATCH_TIERS),0),original_seed,'different',None,None)
    else:
        tier,difference='different',None
        best=((True,len(PAGE_MATCH_TIERS),0),original_seed,'different',None,None)
    seed_policy=seed_search_policy(read(source),tier)
    context.update(seed_search_allowed=seed_policy['allowed'],seed_search_cards=seed_policy['eligible_cards'],
                   seed_search_skip_reason=seed_policy['skip_reason'])
    seed_report=dict(original_seed=original_seed,original_tier=tier,original_difference=difference,attempts=[],selected_seed=original_seed,
                     original_ability_branches_matched=ability_error is None,policy=seed_policy)
    # The user may end the search at any time and play the closest result so far.
    tier_names=dict(exact='完全一致',same_towers='终局近似',same_winner='仅胜负相同',different='不符',unknown='无法完整比对')
    match_key=replay_key(read(source));memory_path=files/'seed-memory.json'
    try:seed_memory=read(memory_path) if memory_path.is_file() else {}
    except (OSError,ValueError):seed_memory={}
    remembered=seed_memory.get(match_key) if isinstance(seed_memory.get(match_key),dict) else {}
    remembered_seed=remembered.get('seed') if remembered.get('tier') in PAGE_MATCH_TIERS[:3] else None
    seed_report.update(match_key=match_key,remembered_seed=remembered_seed)
    # A discarded original run never seeds the search; the elixir-consistent heroes do.
    fixed_choices=dict(aligned.get('ability_target_choices') or {}) if best[4] is not None else {}
    elixir_inferred=bool(closest_abilities and elixir_consistent and best[4] is None)
    if elixir_inferred:fixed_choices=dict(elixir_consistent['choices'])
    seed_report['fixed_ability_choices']=fixed_choices if closest_abilities else None
    seed_report['ability_choices_from_elixir']=elixir_inferred
    if seed_policy['search_needed']:
        card_names='、'.join('骷髅之王' if card=='skeleton-king' else '猎人' for card in seed_policy['eligible_cards'])
        if ability_error is not None:status('simulating','原种子下技能目标没有与网页完全一致的分支；卡组含'+card_names+'，按策略尝试其他种子（技能目标仍要求完全一致，不代表已确认差异来自随机性）。')
        if elixir_inferred:status('simulating','按网页溢出圣水限定英雄技能：先试与溢出圣水相符的 '+str(len(fixed_choices))+' 次技能英雄，每个种子仍继续枚举其余技能分支。')
        # Successive halving. Screening: one deal probe, then up to twelve
        # skill-branch runs (the calibrated deal is predicted from that probe; each run
        # itself verifies it and a mismatch falls back to normal calibration).
        # Refinement: only the closest few seeds get a deeper ability search.
        screened=[]
        def nonlocal_prep_write(path,value):
            nonlocal prep
            write_new(path,value);prep=path
        def calibrated(number,seed,optimistic):
            trial=copy.deepcopy(delayed);trial['initialization_only']['rndSeed']=seed;trial_seen=[]
            for calibration in range(12):
                if seed_stop():raise Cancelled('seed search stopped by user')
                trial_seen.append(deck_fingerprint(trial))
                name='seed-'+str(number)+('-deal-' if optimistic else '-recal-')+str(calibration)
                nonlocal_prep_write(preparation/(name+'.json'),trial)
                trial=calibrate(trial,probe(name),trial_seen)
                if trial['native_deal_ready'] or optimistic:return trial
            raise RuntimeError('seed deal calibration did not converge')
        def run_seed(number,seed,trial,prefix,**options):
            nonlocal attempt_prefix
            attempt_prefix=prefix
            try:
                return search(trial,execute_candidate,
                    lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                    cancelled=lambda:cancelled() or seed_stop(),bound=hp_bound,**options)
            finally:attempt_prefix=''
        def consider(number,seed,result,row):
            nonlocal best
            trial,trial_execution,trial_search=result
            restore(trial_search)
            trial_tier,trial_difference=page_comparison(read(source),trial,trial_execution)
            if type(trial_difference) is int and trial_difference>=ELIXIR_MISMATCH_COST:
                raise RuntimeError(elixir_gate(read(source),trial,trial_execution)+'；已丢弃')
            row.update(executed=True,tier=trial_tier,difference=trial_difference,
                       towers=(trial_execution.get('battle_state') or {}).get('towers'))
            entry=(rank(trial_tier,trial_difference),seed,trial_tier,trial_difference,
                   (trial,trial_execution,trial_search,dict(selected_candidate)))
            if entry[0]<best[0]:best=entry
            return entry
        def incumbent():return best[3] if type(best[3]) is int else None
        def closest_text():
            # Only runs that passed the elixir check are kept; say so instead of a placeholder tier.
            return '尚无溢出圣水与网页一致的完整组合' if best[4] is None else tier_names[best[2]]+cost_text(best[3],page_breakdown(read(source),best[4][0],best[4][1]))
        planned_seeds=list(seed_plan(match_key,original_seed,remembered=remembered_seed))
        for number,seed in enumerate(planned_seeds):
            if cancelled():raise Cancelled('cancelled during seed search')
            if seed_stop():seed_report['stopped_by_user']=True;break
            status('simulating','终局未完全匹配；卡组含'+card_names+'，筛选随机种子 '+str(number+1)+'/'+str(len(planned_seeds))+'（之后精修最接近的 '+str(REFINE_SEEDS)+' 个），当前最接近：'+closest_text()+
                   ''+'。可随时点「停止匹配，用当前最接近的开播」。',
                   seed_search_active=True,seed_attempt=number+1,seed_total=len(planned_seeds),seed_best_tier=best[2],seed_best_difference=best[3])
            row=dict(seed=seed,phase='screen')
            try:
                trial=calibrated(number,seed,True)
                # Without a combination that completed at the original seed, one run
                # always stops at the first ambiguous ability: search that seed itself.
                # Elixir-inferred heroes only constrain: they are tried first, and the
                # seed still enumerates its own branches (pruned by leaked elixir).
                complete_fixed=bool(fixed_choices) and not elixir_inferred
                options=(dict(initial=fixed_choices,closest=hp_key,max_attempts=SCREEN_RUNS if complete_fixed else SCREEN_RUNS_UNFIXED,
                              patience=None if complete_fixed else 6,incumbent=incumbent()) if closest_abilities else {})
                try:result=run_seed(number,seed,trial,'seed-'+str(number)+'-',**options)
                except RuntimeError as error:
                    if 'native deal mismatch' not in str(error):raise
                    row['deal_recalibrated']=True
                    trial=calibrated(number,seed,False)
                    result=run_seed(number,seed,trial,'seed-'+str(number)+'-v-',**options)
                entry=consider(number,seed,result,row)
                screened.append((entry[0],number,seed,trial,dict(entry[4][0].get('ability_target_choices') or {})))
            except Cancelled:
                if not seed_stop():raise
                row.update(executed=False,error='stopped by user before this seed ran')
                seed_report['attempts'].append(row);seed_report['stopped_by_user']=True;break
            except Exception as error:
                row.update(executed=False,error=str(error)[:300])
                # A retained native attempt still owns the game: every later seed
                # would be refused, so stop here and let failure recovery release it.
                if 'native attempt retained' in str(error) or 'still owns game' in str(error):
                    seed_report['attempts'].append(row);write_new(destination/'seed-search.json',seed_report);raise
            seed_report['attempts'].append(row)
            if seed_stop():seed_report['stopped_by_user']=True;break
            if best[2]=='exact':break
        if closest_abilities and best[2]!='exact' and not seed_stop():
            for step,(_,number,seed,trial,choices) in enumerate(sorted(screened,key=lambda item:item[0])[:REFINE_SEEDS]):
                if cancelled():raise Cancelled('cancelled during seed refinement')
                if seed_stop():seed_report['stopped_by_user']=True;break
                status('simulating','精修最接近的种子 '+str(step+1)+'/'+str(REFINE_SEEDS)+'：在该种子下搜索技能组合，当前最接近：'+closest_text()+
                       ''+'。可随时点「停止匹配，用当前最接近的开播」。',
                       seed_search_active=True,seed_attempt=number+1,seed_total=len(planned_seeds),seed_best_tier=best[2],seed_best_difference=best[3])
                row=dict(seed=seed,phase='refine')
                try:
                    result=run_seed(number,seed,trial,'seed-'+str(number)+'-r-',initial=choices,closest=hp_key,
                                    max_attempts=REFINE_RUNS,patience=8,incumbent=incumbent())
                    consider(number,seed,result,row)
                except Cancelled:
                    if not seed_stop():raise
                    seed_report['stopped_by_user']=True;break
                except Exception as error:row.update(executed=False,error=str(error)[:300])
                seed_report['attempts'].append(row)
                if best[2]=='exact':break
    if best[4] is None:
        write_new(destination/'seed-search.json',seed_report)
        reason=str(ability_error) if ability_error is not None else (elixir_rejection or '没有溢出圣水与网页一致的完整分支')
        raise RuntimeError(reason+' '+seed_search_note(len(seed_report['attempts']),seed_policy['allowed'])+'；没有溢出圣水和技能目标都与网页一致的分支，未发布回放。')
    _,selected_seed,tier,difference,(aligned,execution,search_result,chosen)=best
    selected_candidate.clear();selected_candidate.update(chosen)
    seed_report.update(selected_seed=selected_seed,selected_tier=tier,selected_difference=difference)
    # Remember the closest seed of this MATCH so a re-saved page reproduces it.
    previous=seed_memory.get(match_key) if isinstance(seed_memory.get(match_key),dict) else {}
    if rank(tier,difference)<rank(previous.get('tier','unknown'),previous.get('difference')) and tier in PAGE_MATCH_TIERS[:3]:
        seed_memory[match_key]=dict(seed=selected_seed,tier=tier,difference=difference,replay_tag=read(source).get('replay_tag'),updated_at=time.time())
        temp=files/'seed-memory.tmp'
        with temp.open('w') as stream:json.dump(seed_memory,stream,ensure_ascii=False,indent=1)
        temp.replace(memory_path)
    hp_matched=tier=='exact'
    write_new(destination/'seed-search.json',seed_report)
    receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']
    context['ability_target_inferred']=search_result['inferred']
    # final_hp_matched: the whole simulated battle ends exactly at the page's tower HP.
    # random_seed_inferred: matched only with a substituted seed; not proof of the original process.
    # Per-tower record of the run actually selected, for side-by-side checks.
    breakdown=page_breakdown(read(source),aligned,execution)
    write_new(destination/'page-comparison.json',dict(tier=tier,difference=difference,match_cost=difference,**breakdown,
                                                      towers=page_towers(read(source),aligned,execution)))
    context.update(final_hp_matched=hp_matched,page_match=tier,page_hp_difference=breakdown['hp_difference'],page_match_cost=difference,
                   page_time_difference_seconds=breakdown['time_difference_seconds'],random_seed=seed_report['selected_seed'],
                   random_seed_inferred=seed_report['selected_seed']!=original_seed or bool(context.get('deal_seed_changed')),seed_attempts=sum(row.get('phase')=='screen' for row in seed_report['attempts']),
                   page_elixir_matched=breakdown['elixir_matched'])
    context['page_match_breakdown']=breakdown
    context['page_match_detail']=cost_text(difference,breakdown)
    from failure_recovery import version_hint
    context['version_check_hint']=version_hint(tier)
    # Final gate: both players must leak exactly the page's elixir, which pins
    # what was paid for abilities. Anything else is never published.
    elixir_refusal=elixir_gate(read(source),aligned,execution)
    if elixir_refusal is not None:
        raise RuntimeError(elixir_refusal+'（'+seed_search_note(len(seed_report['attempts']),seed_policy['allowed'])+'）；未放行，未发布回放。')

    return aligned,execution,search_result,selected_candidate,context
