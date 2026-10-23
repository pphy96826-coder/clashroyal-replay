"""Build qualified skill plans once; screen seeds cheaply, then refine a shortlist."""
import copy,hashlib,json,re
from collections import deque
from source_completion import source_completed,source_failure
from alns_skills import Explorer
from ability_search import elixir_rows,elixir_check,elixir_margin,ELIXIR_TOLERANCE


def ordered(preparation,report):
    if not source_completed(report,len(preparation['events'])):return False
    diagnostics=report.get('diagnostics') or []
    if len(diagnostics)!=len(preparation['events']):return False
    for i,(event,command,detail) in enumerate(zip(preparation['events'],report['commands'],diagnostics)):
        body=command.get('c',{});card=event['kind']=='play_card';owner=preparation['participants'][event['source_side']]['native_owner']
        if (command.get('ct')!=(153 if card else 189) or body.get('t')!=event['source_tick_20hz'] or
            detail.get('index')!=i or detail.get('tick')!=event['source_tick_20hz'] or detail.get('owner')!=owner or
            detail.get('card')!=(event['base_data_id'] if card else 0)):return False
        if card and (body.get('px')!=event['source_position']['x'] or body.get('py')!=event['source_position']['y']):return False
    return True


def actor_plan(preparation,report):
    plan={};costs={}
    for row in report.get('ability_observations') or []:
        if row.get('phase')!='selected':continue
        i=row.get('event_index');ordinal=row.get('selected_ordinal');actors=row.get('actors') or []
        if type(i) is not int or not 0<=i<len(preparation['events']) or preparation['events'][i]['kind']!='activate_ability':raise ValueError('invalid selected skill index')
        if type(ordinal) is not int or not 0<=ordinal<len(actors):raise ValueError('selected skill actor missing')
        name=actors[ordinal].get('name','')
        if not re.fullmatch('[A-Za-z0-9_]{1,64}',name) or sum(a.get('name')==name for a in actors)!=1:raise ValueError('skill actor identity is not unique')
        if str(i) in plan:raise ValueError('duplicate selected skill observation')
        plan[str(i)]=name
    expected={str(i) for i,e in enumerate(preparation['events']) if e['kind']=='activate_ability'}
    if set(plan)!=expected:raise ValueError('not every skill has a verified actor')
    for row in report.get('diagnostics') or []:
        if str(row.get('index')) in expected:
            cost=(row.get('actor') or {}).get('cost')
            if type(cost) is not int or cost<0:raise ValueError('skill payment not verified')
            costs[str(row['index'])]=cost
    if set(costs)!=expected:raise ValueError('not every skill has a verified payment')
    return plan,costs


class EmptyPool(RuntimeError):pass
class PoolScopeChanged(RuntimeError):pass


class Pool:
    def __init__(self,source,compare,record=lambda *args:None):
        self.source=source;self.compare=compare;self.record=record;self.entries=[];self.seed=None;self.history=[];self.elite=None;self.explorer=Explorer();self.alns_total_budget=24;self.allocations=[];self.seed_states={};self.refinement_history=[];self.pool_scope=None
    screen_limit=2
    @property
    def refinement_used(self):return len(self.refinement_history)
    def qualified(self,candidate,report):
        rows=elixir_rows(self.source,report)
        return ordered(candidate,report) and len(rows)==2 and all(r['matched'] is True for r in rows)
    def _result(self,attempts,valid,pending=0):
        report=dict(attempts=attempts,candidate_pool_size=len(self.entries),pool_seed=self.seed,
            remaining=pending,pool_enumeration_complete=pending==0,inferred=True,unique_solution_proven=False,
            seed_branch_expansion=False)
        if not valid:
            error=EmptyPool('没有完整、顺序合格且双方溢出圣水一致的技能候选')
            report.update(explored_branches_exhausted=pending==0,full_match_possibilities_exhausted=False)
            error.search_report=report;raise error
        _,candidate,result,index=min(valid,key=lambda row:row[0]);report.update(chosen_attempt=index,final_hp_matched=self.compare(self.source,candidate,result)[0]=='exact',closest_selected=self.compare(self.source,candidate,result)[0]!='exact')
        return candidate,result,report
    def enumerate(self,preparation,execute,*,cancelled=lambda:False,stop_early=lambda:False,max_attempts=256,stop_on_exact=False,**unused):
        if self.entries:raise ValueError('candidate pool is already frozen')
        pending=deque([{}]);seen=set();attempts=[];valid=[];self.seed=preparation['initialization_only']['rndSeed']
        while pending and len(attempts)<max_attempts:
            if cancelled():raise RuntimeError('技能候选枚举已取消；未提交下一分支')
            if valid and stop_early():break
            choices=pending.popleft();key=tuple(sorted(choices.items()))
            if key in seen:continue
            seen.add(key);candidate=copy.deepcopy(preparation);candidate.update(ability_target_choices=choices,ability_actor_names={})
            result,evidence=execute(candidate,len(attempts));row=dict(choices=choices,evidence=evidence,error=result.get('error'),native_accepted=result.get('native_accepted',0),failure=source_failure(result) if result.get('error') else None)
            attempts.append(row)
            if self.qualified(candidate,result):
                try:plan,costs=actor_plan(candidate,result)
                except ValueError as error:row['pool_rejection']=str(error);continue
                signature=tuple(sorted(plan.items()));tier,cost=self.compare(self.source,candidate,result)
                if not any(e['signature']==signature for e in self.entries):self.entries.append(dict(signature=signature,actors=plan,costs=costs,origin_cost=cost,origin_tier=tier,choices=copy.deepcopy(choices),evidence=copy.deepcopy(evidence)))
                valid.append(((cost if cost is not None else 1<<40,('exact','same_towers','same_winner','different','unknown').index(tier)),candidate,result,len(attempts)-1));row['pool_qualified']=True
                if stop_on_exact and tier=='exact':break
            elif source_completed(result,len(candidate['events'])):row['pool_rejection']='顺序或双方溢出圣水不合格'
            elif result.get('error')==112 and type(result.get('native_code')) is int and 1<=result['native_code']<=1024:
                i=result.get('event_index')
                if type(i) is not int or not 0<=i<len(candidate['events']) or candidate['events'][i]['kind']!='activate_ability':raise ValueError('ambiguity is not a source skill')
                # Only irreversible elixir/payment failures prune this enumeration.
                rows=elixir_rows(self.source,result)
                if any(r.get('shortfall') or (r['page'] is not None and r['simulated'] is not None and r['simulated']>=r['page']+ELIXIR_TOLERANCE+elixir_margin(self.source)-1e-6) for r in rows):row['pool_rejection']='溢出超标或圣水不足，后续无法恢复';continue
                prefix={k:v for k,v in choices.items() if int(k)<i}
                children=[dict(prefix,**{str(i):v}) for v in range(result['native_code'])]
                fresh=[c for c in children if tuple(sorted(c.items())) not in seen]
                if fresh:pending.appendleft(fresh[0]);pending.extend(fresh[1:])
            self.record('enumerating',dict(seed=self.seed,attempts=len(attempts),remaining=len(pending),qualified=len(self.entries)))
        self.history.append(dict(seed=self.seed,attempts=copy.deepcopy(attempts),remaining=len(pending),qualified=len(self.entries)))
        return self._result(attempts,valid,len(pending))
    def _seed_state(self,preparation,scope,verify_reuse):
        clean=copy.deepcopy(preparation)
        for name in ('ability_actor_names','ability_target_choices','same_cost_alns'):clean.pop(name,None)
        fingerprint=hashlib.sha256(json.dumps(clean,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        seed=preparation['initialization_only']['rndSeed'];key=(seed,fingerprint)
        label=json.dumps(scope,sort_keys=True,separators=(',',':'),allow_nan=False)
        if scope is not None:
            if self.pool_scope is not None and self.pool_scope!=label:raise PoolScopeChanged('pool scope changed; stopped without replaying a native task')
            self.pool_scope=label
        state=self.seed_states.get(key)
        if state is None:
            if any(number==seed for number,_ in self.seed_states):
                self.explorer.states={k:v for k,v in self.explorer.states.items() if k[0]!=seed};self.explorer.visited.pop(seed,None)
            state=dict(seed=seed,fingerprint=fingerprint,scope=label,records=[],tried=set(),screen_attempts=0,screen_finished=False,deferred_refinements=0,refine_steps=0)
            self.seed_states[key]=state
        elif state.get('aborted'):
            raise RuntimeError('native attempt retained; candidate pool stopped after interrupted execution')
        elif state['records']:
            if state['scope']!=label or scope is None or verify_reuse is None:
                raise PoolScopeChanged('pool scope changed or release verification missing; no cached result reused')
            try:verified=verify_reuse([(r['report'],r['evidence']) for r in state['records']])
            except Exception as error:raise PoolScopeChanged('pool scope changed: cached release/generation proof failed') from error
            if verified is not True:raise PoolScopeChanged('pool scope changed: cached release/generation proof refused')
        return state
    @staticmethod
    def _signature(plan):return tuple(sorted(plan.items()))
    def _pending(self,state):
        return [e for e in self.entries if self._signature(e['actors']) not in state['tried']]
    def _next_entry(self,state):
        pending=self._pending(state)
        if not pending:return None
        tried=[dict(s) for s in state['tried']]
        def priority(entry):
            value=entry.get('origin_cost');score=value if type(value) in (int,float) else 1<<40
            distance=min((Explorer.distance(entry['actors'],p) for p in tried),default=0)
            return (-distance,score)
        return min(pending,key=priority)
    def evaluate(self,preparation,execute,*,cancelled=lambda:False,stop_early=lambda:False,alns_budget=0,scope=None,verify_reuse=None,**unused):
        if not self.entries:raise EmptyPool('候选池为空；需要先在首个合格种子建立候选池')
        if type(alns_budget) is not int or not 0<=alns_budget<=4:raise ValueError('ALNS per-seed budget outside 0..4')
        if cancelled():raise RuntimeError('种子候选验证已取消；未提交下一候选')
        state=self._seed_state(preparation,scope,verify_reuse);attempts=[];valid=[];bases=[]
        def accept(record,reused):
            candidate=record['candidate'];report=record['report'];costs=record['costs'];record['qualified']=False
            row=dict(choices={},fixed_actors=copy.deepcopy(candidate['ability_actor_names']),evidence=copy.deepcopy(record['evidence']),
                error=report.get('error'),native_accepted=report.get('native_accepted',0),reused=reused,
                failure=source_failure(report) if report.get('error') else None)
            if record.get('decision'):row['alns']=copy.deepcopy(record['decision'])
            index=len(attempts);attempts.append(row)
            if not self.qualified(candidate,report):
                row['pool_rejection']='未完整执行、顺序或溢出圣水不合格'
                if not source_completed(report,len(candidate['events'])):bases.append((candidate,report,record['evidence'],costs))
                return
            try:plan,paid=actor_plan(candidate,report)
            except ValueError as error:row['pool_rejection']=str(error);return
            if plan!=candidate['ability_actor_names'] or paid!=costs:
                row['pool_rejection']='实际技能身份或实付顺序改变';return
            bases.append((candidate,report,record['evidence'],costs));tier,cost=self.compare(self.source,candidate,report)
            key=(cost if cost is not None else 1<<40,('exact','same_towers','same_winner','different','unknown').index(tier))
            valid.append((key,candidate,report,index));row['pool_qualified']=True;record['qualified']=True
            if self.elite is None or key<self.elite['key']:
                self.elite=dict(key=key,actors=copy.deepcopy(plan),costs=copy.deepcopy(costs),evidence=copy.deepcopy(record['evidence']))
        for record in state['records']:accept(record,True)
        def exact():return any(key[0]==0 and self.compare(self.source,c,r)[0]=='exact' for key,c,r,_ in valid)
        def check_release(result,evidence):
            if verify_reuse is not None and verify_reuse([(result,evidence)]) is not True:
                raise PoolScopeChanged('pool scope changed: fresh candidate clean release not proven')
        def execute_entry(entry,phase):
            if cancelled():raise RuntimeError('种子候选验证已取消；未提交下一候选')
            candidate=copy.deepcopy(preparation);candidate.update(ability_target_choices={},ability_actor_names=copy.deepcopy(entry['actors']))
            candidate.pop('same_cost_alns',None)
            signature=self._signature(entry['actors']);state['tried'].add(signature)
            try:
                result,evidence=execute(candidate,len(attempts));check_release(result,evidence)
            except BaseException:
                state['aborted']=True;raise
            record=dict(candidate=copy.deepcopy(candidate),report=copy.deepcopy(result),evidence=copy.deepcopy(evidence),costs=copy.deepcopy(entry['costs']))
            state['records'].append(record);accept(record,False)
            if phase=='screen':state['screen_attempts']+=1
            else:self.refinement_history.append(dict(seed=state['seed'],kind='deferred-pool',actors=copy.deepcopy(entry['actors']),evidence=copy.deepcopy(evidence)))
        # Screening is capped over the lifetime of this seed, not per call.
        while not state['screen_finished'] and state['screen_attempts']<self.screen_limit:
            if exact() or (valid and stop_early()):break
            entry=self._next_entry(state)
            if entry is None:break
            execute_entry(entry,'screen')
        state['screen_finished']=True
        budget=min(alns_budget,max(0,self.alns_total_budget-self.refinement_used));before=self.refinement_used
        reason='首轮最多验证两组代表候选，其余组合延后' if not alns_budget else '入围种子轮流新增验证一个组合'
        if not bases and not self._pending(state):budget=0;reason='没有费用身份已核实的可继续基准组合'
        if exact():budget=0;reason='已找到完整、顺序及严格溢出校验通过的全项匹配'
        elif alns_budget and budget==0:reason='整场新组合预算已用尽'
        def execute_mutation(candidate,index):
            try:
                result,evidence=execute(candidate,index);check_release(result,evidence);return result,evidence
            except BaseException:
                state['aborted']=True;raise
        # All verified pool probes contribute to diversity coverage; replaying
        # the saved evidence only updates task-local search state.
        self.explorer.run(preparation,bases,execute_mutation,self.qualified,actor_plan,self.compare,self.source,budget=0)
        for _ in range(budget):
            if cancelled():raise RuntimeError('种子精修已取消；未提交下一候选')
            if exact() or (valid and stop_early()):break
            entry=self._next_entry(state)
            use_pool=entry is not None and (len(self.entries)<=self.explorer.small_space_limit or
                state['deferred_refinements']<2 or state['refine_steps']%2==1)
            mutations=[]
            if not use_pool:
                mutations=self.explorer.run(preparation,bases,execute_mutation,self.qualified,actor_plan,self.compare,self.source,
                    offset=len(attempts),budget=1,cancelled=cancelled,stop_early=stop_early)
            if not mutations:
                if entry is None:break
                execute_entry(entry,'refine');state['deferred_refinements']+=1
                self.explorer.run(preparation,bases,execute_mutation,self.qualified,actor_plan,self.compare,self.source,budget=0)
            for candidate,result,evidence,costs,decision in mutations:
                signature=self._signature(candidate['ability_actor_names']);state['tried'].add(signature)
                record=dict(candidate=copy.deepcopy(candidate),report=copy.deepcopy(result),evidence=copy.deepcopy(evidence),costs=copy.deepcopy(costs),decision=copy.deepcopy(decision))
                state['records'].append(record);accept(record,False)
                self.refinement_history.append(dict(seed=state['seed'],kind='same-cost-mutation',actors=copy.deepcopy(candidate['ability_actor_names']),evidence=copy.deepcopy(evidence)))
            state['refine_steps']+=1
        used=self.refinement_used-before;pending=len(self._pending(state))
        allocation=dict(seed=state['seed'],requested=alns_budget,granted=budget,used=used,reason=reason,
            screen_limit=self.screen_limit,screen_attempts=state['screen_attempts'],tested_combinations=len(state['tried']),deferred_pool_candidates=pending,refinement_budget_total=self.alns_total_budget,
            reused_candidates=sum(r['reused'] for r in attempts),refinement_used=self.refinement_used,
            can_continue=bool(pending or used) and self.refinement_used<self.alns_total_budget and not exact())
        self.allocations.append(copy.deepcopy(allocation));self.record('alns_allocation',allocation)
        detail=dict(alns_allocation=allocation,remaining=pending,remaining_scope='deferred-seed-pool-candidates',deferred_pool_candidates=pending,screen_limit=self.screen_limit,
            screen_attempts=state['screen_attempts'],same_cost_alns=self.explorer.snapshot(),
            best_prefix=max((r['report'].get('native_accepted',0) for r in state['records']),default=0))
        try:result=self._result(attempts,valid)
        except EmptyPool as error:
            error.search_report.update(detail);error.search_report['explored_branches_exhausted']=not allocation['can_continue']
            error.args=('本种子已验证 '+str(len(state['tried']))+' 组，尚无完整、顺序及溢出合格的结果；仍有 '+str(pending)+' 组候选延后，未认定整个种子无解',)
            raise
        result[2].update(detail);return result
    def snapshot(self):
        progress=[dict(seed=s['seed'],preparation_fingerprint=s['fingerprint'],screen_attempts=s['screen_attempts'],screen_limit=self.screen_limit,
            tested=len(s['tried']),deferred_pool_candidates=len(self._pending(s)),
            qualified=sum(r.get('qualified') is True for r in s['records'])) for s in self.seed_states.values()]
        return dict(seed=self.seed,qualified=len(self.entries),entries=copy.deepcopy(self.entries),enumerations=copy.deepcopy(self.history),
            elite=copy.deepcopy(self.elite),same_cost_alns=self.explorer.snapshot(),alns_allocations=copy.deepcopy(self.allocations),
            alns_total_budget=self.alns_total_budget,alns_remaining_budget=max(0,self.alns_total_budget-self.refinement_used),
            refinement_budget_used=self.refinement_used,refinement_history=copy.deepcopy(self.refinement_history),
            screening_policy='best-origin-plus-distant-representative',screen_limit=self.screen_limit,seed_progress=progress)
