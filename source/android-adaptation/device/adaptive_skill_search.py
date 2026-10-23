"""Feedback scheduler for independent seed/skill frontiers; no learned model yet.

Only complete, accepted source streams compete for playback. Frontier snapshots
contain choices and feedback, never native objects or resumable battle pointers.
Pausing a seed preserves its work queue; every candidate is a fresh simulation.
"""
import copy
import math
import time
from source_completion import source_completed, source_failure

POLICY = 'feedback-seed-skill-v1'


def search(preparation, seeds, prepare_seed, execute, matches, score, *,
           max_attempts=128, max_seeds=8, max_seconds=900,
           cancelled=lambda: False, stop_requested=lambda: False,
           on_best=lambda *args: None, on_snapshot=lambda value: None,
           on_decision=lambda value: None, boundary_errors=(), clock=time.monotonic):
    """Interleave seed-local legal-actor trees using measured progress and cost.

    Utility is an explicit heuristic, NOT a calibrated success probability.
    A stagnating seed is paused, never declared impossible. Approximate floor
    continuation is allowed only after strict frontiers of the bounded seed
    pool have all been explored, and only if no strict complete result exists.
    No claim about untested seeds or global exhaustive search is made.
    """
    if type(max_attempts) is not int or not 1 <= max_attempts <= 4096:
        raise ValueError('invalid adaptive candidate bound')
    if type(max_seeds) is not int or not 1 <= max_seeds <= 61:
        raise ValueError('invalid adaptive seed bound')
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('invalid adaptive time bound')
    initial = preparation['initialization_only']['rndSeed']
    plan = []
    for seed in [initial] + list(seeds):
        if type(seed) is not int or not -2**31 <= seed < 2**31:
            raise ValueError('seed must be int32')
        if seed not in plan: plan.append(seed)
    omitted = len(plan) > max_seeds
    plan = plan[:max_seeds]
    states = [dict(seed=s, pending=[{}], seen=[], pruned=[], visits=0, complete=0,
                   improvements=0, stagnant=0, seconds=0., progress=0, last=-1,
                   best_difference=None, phase='strict') for s in plan]
    prepared = {initial: copy.deepcopy(preparation)}
    history = []; decisions = []; best = None; previous = None
    phase = 'strict'; stopped = bounded = False; started = clock()
    exact = False

    def snapshot():
        return dict(schema='royale-replay.adaptive-search.v1', policy=POLICY,
            phase=phase, seeds=copy.deepcopy(states), attempts=copy.deepcopy(history),
            decisions=copy.deepcopy(decisions), elapsed_seconds=max(0., clock()-started),
            selected_evidence=copy.deepcopy(best[3]) if best else None,
            selected_hp_difference=best[0][1] if best else None,
            seed_pool=plan, additional_seeds_not_admitted=omitted,
            exhaustive=False, unique_solution_proven=False,
            frontier_resume_scope='same search invocation; fresh native simulation',
            learned_model_used=False)

    def save(): on_snapshot(snapshot())

    while len(history) < max_attempts:
        if cancelled(): raise RuntimeError('反馈搜索已取消；未提交后续候选')
        if best and stop_requested(): stopped = True; break
        if clock()-started >= max_seconds: bounded = True; break
        active = [s for s in states if s['pending']]
        if not active:
            if phase == 'strict' and best is None and any(s['pruned'] for s in states):
                phase = 'fallback'
                for s in states:
                    s.update(phase=phase, seen=[], pending=[p['choices'] for p in
                        sorted(s['pruned'], key=lambda p: p['difference'], reverse=True)])
                save(); continue
            break
        total = sum(s['visits'] for s in states)
        measured = sum(s['seconds'] for s in states) / max(1, total)
        features = []
        for s in active:
            cost = max(.01, s['seconds']/s['visits'] if s['visits'] else measured or 1.)
            # Smoothed productivity, progress and exploration guide allocation;
            # partial HP distances never enter terminal-quality improvement.
            productivity = (s['improvements'] + .5*s['complete'] + 1)/(s['visits']+2)
            exploration = math.sqrt(2*math.log(total+2)/(s['visits']+1))
            advancement = s['progress']/max(1, len(preparation['events']))
            utility = (productivity + exploration + .25*advancement) / (cost*(1+.25*s['stagnant']))
            features.append(dict(seed=s['seed'], utility=utility, mean_seconds=cost,
                visits=s['visits'], complete=s['complete'], improvements=s['improvements'],
                stagnant=s['stagnant'], progress=s['progress'], frontier=len(s['pending'])))
        # Forced exploration prevents a cheap dead-end region from starving
        # paused or untried seeds. Decisions remain deterministic given timings.
        if phase == 'fallback' and best is None:
            def prefix_gap(s):
                choices=s['pending'][-1]
                return min(p['difference'] for p in s['pruned']
                    if all(choices.get(k)==v for k,v in p['choices'].items()))
            state=min(active,key=prefix_gap)
            reason='有限种子池的严格分支已用尽：优先续算剪枝时六塔血差最小的前缀'
        elif total and total % 6 == 0:
            state = min(active, key=lambda s: (s['last'], plan.index(s['seed'])))
            reason = '定期探索：恢复等待最久的种子，避免永久淘汰暂时受阻的分支'
        else:
            chosen = max(features, key=lambda f: f['utility'])
            state = next(s for s in active if s['seed'] == chosen['seed'])
            reason = '按完整结果改善、指令进展、受阻次数及实际耗时分配下一次模拟'
        action = 'continue' if previous == state['seed'] else ('new_seed' if not state['visits'] else 'revisit')
        decision = dict(number=len(history), seed=state['seed'], phase=phase,
                        action=action, previous_seed=previous, reason=reason, features=features)
        decisions.append(decision); on_decision(copy.deepcopy(decision)); save()
        before = clock(); choices = state['pending'][-1]
        try:
            if state['seed'] not in prepared:
                fresh = prepare_seed(state['seed'], plan.index(state['seed']))
                if fresh['initialization_only']['rndSeed'] != state['seed']:
                    raise ValueError('calibrated seed identity differs')
                prepared[state['seed']] = copy.deepcopy(fresh)
            candidate = copy.deepcopy(prepared[state['seed']])
            candidate.update(ability_actor_names={}, ability_target_choices=copy.deepcopy(choices),
                             prune_below_oracle=phase == 'strict')
            report, evidence = execute(candidate, len(history))
        except boundary_errors as error:
            bounded = True
            if best and stop_requested(): stopped = True; bounded = False
            decision.update(boundary_error=type(error).__name__, submitted_candidate_retained=True)
            break
        state['pending'].pop(); state['seen'].append(copy.deepcopy(choices))
        elapsed = max(0., clock()-before)
        state['visits'] += 1; state['seconds'] += elapsed; state['last'] = total
        previous = state['seed']
        prior_progress = state['progress']
        state['progress'] = max(prior_progress, report.get('native_accepted', 0))
        row = dict(seed=state['seed'], phase=phase, choices=copy.deepcopy(choices),
                   evidence=evidence, error=report.get('error'), seconds=elapsed,
                   native_accepted=report.get('native_accepted', 0), complete=False,
                   failure=source_failure(report) if report.get('error') else None,
                   improvement=0, decision_number=len(decisions)-1)
        improved = False
        if source_completed(report, len(candidate['events'])):
            value = score(candidate, report)
            if type(value) is not int or value < 0: raise ValueError('invalid terminal six-tower difference')
            matched = bool(matches(candidate, report))
            state['complete'] += 1
            if state['best_difference'] is None or value < state['best_difference']:
                improved = True; state['improvements'] += 1
                state['best_difference'] = value
            rank = (phase == 'fallback', value)
            row.update(complete=True, hp_difference=value, final_hp_matched=matched)
            if best is None or rank < best[0]:
                row['improvement'] = max(0, best[0][1]-value) if best else 0
                best = (rank, candidate, report, evidence, matched)
                on_best(candidate, report, value, evidence)
            exact = phase == 'strict' and value == 0 and matched
        elif report.get('error') == 112 and type(report.get('native_code')) is int and 1 < report['native_code'] <= 1024:
            index = report.get('event_index')
            if type(index) is not int or not 0 <= index < len(candidate['events']) or candidate['events'][index]['kind'] != 'activate_ability':
                raise ValueError('ambiguity is not a source skill')
            if str(index) not in choices:
                for ordinal in reversed(range(report['native_code'])):
                    child = dict(choices, **{str(index): ordinal})
                    if child not in state['seen'] and child not in state['pending']:
                        state['pending'].append(child)
                row['forked_event_index'] = index
                row['legal_candidates'] = report['native_code']
        elif report.get('error') == 123 and isinstance(report.get('hp_floor_violation'), dict):
            value = score(candidate, report)
            if type(value) is not int or value < 0: raise ValueError('invalid pruned six-tower difference')
            row.update(pruned_below_oracle=True, pruned_hp_difference=value,
                       hp_floor_violation=report['hp_floor_violation'])
            state['pruned'].append(dict(choices=copy.deepcopy(choices), difference=value))
        elif report.get('error') in (125, 126):
            raise ValueError('observer guard/checkpoint report cannot enter generic adaptive search')
        state['stagnant'] = 0 if improved or state['progress'] > prior_progress else state['stagnant']+1
        history.append(row)
        decision.update(observed_seconds=elapsed, observed_complete=row['complete'],
                        terminal_improvement=row['improvement'], frontier_after=len(state['pending']))
        save()
        if exact: break
    if len(history) >= max_attempts and any(s['pending'] for s in states): bounded = True
    detail = snapshot()
    detail.update(stopped_by_user=stopped, budget_exhausted=bounded,
        remaining=sum(len(s['pending']) for s in states),
        explored_branches_exhausted=not any(s['pending'] for s in states) and not bounded and not stopped,
        floor_fallback_used=bool(best and best[0][0]), continued_by_fresh_simulation=phase == 'fallback',
        inferred=any(row['choices'] for row in history), ambiguous=any('forked_event_index' in row for row in history),
        final_hp_matched=bool(best and best[4]), complete_branch_before_seed_search=bool(best),
        stop_reason='exact_terminal_hp' if exact else ('user' if stopped else ('budget' if bounded else 'bounded_seed_pool_exhausted')))
    on_snapshot(detail)
    if best: return best[1], best[2], detail
    error = RuntimeError('反馈搜索尚未找到完整且被原生接受的对局；未发布回放。未搜索分支和调度记录已保留。')
    error.search_report = detail
    raise error
