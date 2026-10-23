"""Bounded adaptive destroy/repair of observed, same-cost skill identities."""
import copy,itertools,math,random,time


def domains(report,costs):
    result={}
    # Older evidence has costs in diagnostics; current observers also attach
    # them to the unfiltered available-actor observations (including failures).
    legacy={str(d.get('index')):{a.get('id'):a.get('cost') for a in d.get('eligible',[])} for d in report.get('diagnostics',[])}
    for row in report.get('ability_observations',[]):
        key=str(row.get('event_index'))
        if row.get('phase')!='available' or key not in costs:continue
        actors=row.get('actors',[]);names=[]
        for actor in actors:
            name=actor.get('name');cost=actor.get('cost',legacy.get(key,{}).get(actor.get('definition_id')))
            if isinstance(name,str) and name and type(cost) is int and cost==costs[key] and sum(a.get('name')==name for a in actors)==1:names.append(name)
        if names:result[key]=sorted(set(names))
    return result


class Explorer:
    operators=('single','pair','window')
    small_space_limit=8
    coverage_trials=4
    def __init__(self):
        self.weights={k:1.0 for k in self.operators};self.history=[];self.visited={};self.states={}
    @staticmethod
    def signature(plan):return tuple(sorted(plan.items()))
    @staticmethod
    def distance(a,b):return sum(a.get(i)!=b.get(i) for i in set(a)|set(b))
    def _merge(self,state,report,costs):
        for i,names in domains(report,costs).items():state['domains'].setdefault(i,set()).update(names)
    def _space(self,state):
        plan=state['current'][0]['ability_actor_names'];keys=sorted(plan,key=int)
        choices=[sorted(state['domains'].get(i,{plan[i]})) for i in keys]
        return keys,choices,math.prod(map(len,choices))
    def _pick(self,state,seen,seed):
        candidate=state['current'][0];base=candidate['ability_actor_names'];keys,choices,size=self._space(state)
        rng=random.Random(seed ^ 0x414c4e53 ^ len(seen)*7919)
        if size<=self.small_space_limit:
            for values in itertools.product(*choices):
                plan=dict(zip(keys,values));signature=self.signature(plan)
                if signature not in seen:return ('enumerate',keys,plan,signature,'small-enumeration')
            return None
        if state['coverage_evaluations']<self.coverage_trials:
            # Farthest-point coverage over a bounded sample; objective values
            # never imply that nearby or distant discrete plans are unpromising.
            samples={}
            for j in range(128):
                values=[names[(j+k)%len(names)] if j<8 else rng.choice(names) for k,names in enumerate(choices)]
                plan=dict(zip(keys,values));signature=self.signature(plan)
                if signature not in seen:samples[signature]=plan
            if not samples:return None
            previous=[dict(s) for s in seen]
            def coverage(plan):
                return (min((self.distance(plan,p) for p in previous),default=len(plan)),
                        sum(all(p.get(i)!=name for p in previous) for i,name in plan.items()),self.distance(plan,base))
            signature,plan=max(samples.items(),key=lambda row:coverage(row[1]))
            return ('coverage',[i for i in keys if plan[i]!=base.get(i)],plan,signature,'diverse-coverage')
        alternatives={i:[name for name in names if name!=base.get(i)] for i,names in zip(keys,choices)}
        alternatives={i:names for i,names in alternatives.items() if names}
        if not alternatives:return None
        for draw in range(128):
            operator=rng.choices(self.operators,weights=[self.weights[k] for k in self.operators])[0]
            positions=sorted(alternatives,key=int);k=min(len(positions),{'single':1,'pair':2,'window':3}[operator])
            if operator=='window':
                start=rng.randrange(len(positions));removed=positions[start:start+k]
            else:removed=rng.sample(positions,k)
            plan=dict(base)
            for i in removed:plan[i]=rng.choice(alternatives[i])
            signature=self.signature(plan)
            if signature not in seen:return (operator,removed,plan,signature,'adaptive-local')
        return None
    def warm_plans(self,seed):
        return [(copy.deepcopy(state['current'][0]['ability_actor_names']),copy.deepcopy(state['current'][3]),copy.deepcopy(state['current'][0].get('same_cost_alns')))
                for (number,_),state in self.states.items() if number==seed and state['best_score'][0]==0]
    def run(self,preparation,bases,execute,qualifies,plan_reader,compare,source,*,offset=0,budget=3,cancelled=lambda:False,stop_early=lambda:False):
        if not bases:return []
        seed=preparation['initialization_only']['rndSeed'];seen=self.visited.setdefault(seed,set());groups=[]
        def fully_valid(candidate,report,costs):
            if not qualifies(candidate,report):return False
            try:actual,paid=plan_reader(candidate,report)
            except ValueError:return False
            return actual==candidate['ability_actor_names'] and paid==costs
        def score(base):
            candidate,report,evidence,costs=base
            if fully_valid(candidate,report,costs):
                _,cost=compare(source,candidate,report);return (0,cost if cost is not None else 1<<40)
            return (1,-report.get('native_accepted',0))
        for base in bases:
            candidate,report,evidence,costs=base;key=(seed,self.signature(costs));seen.add(self.signature(candidate['ability_actor_names']))
            if key not in groups:groups.append(key)
            state=self.states.get(key)
            if state is None:
                state=dict(current=copy.deepcopy(base),best_score=score(base),domains={},evaluations=0,coverage_evaluations=0,base_plans=set());self.states[key]=state
            elif score(base)<state['best_score']:state.update(current=copy.deepcopy(base),best_score=score(base))
            self._merge(state,report,costs)
            signature=self.signature(candidate['ability_actor_names'])
            if not candidate.get('same_cost_alns') and signature not in state['base_plans']:
                if state['base_plans']:state['coverage_evaluations']+=1
                state['base_plans'].add(signature)
            if fully_valid(candidate,report,costs):
                for i,name in candidate['ability_actor_names'].items():state['domains'].setdefault(i,set()).add(name)
        runs=[]
        for _ in range(budget):
            if cancelled():raise RuntimeError('同费用技能寻优已取消；没有提交下一次模拟')
            if any(self.states[k]['best_score'][0]==0 for k in groups) and stop_early():break
            if any(self.states[k]['best_score']==(0,0) for k in groups):break
            picked=None
            for key in sorted(groups,key=lambda k:(self.states[k]['evaluations'],self.states[k]['best_score'])):
                state=self.states[key];proposal=self._pick(state,seen,seed)
                if proposal is not None:picked=(state,proposal);break
            if picked is None:break
            state,(operator,removed,plan,signature,phase)=picked;seen.add(signature)
            costs=state['current'][3];trial=copy.deepcopy(preparation)
            trial.update(ability_target_choices={},ability_actor_names=plan,same_cost_alns=dict(operator=operator,phase=phase,changed_indices=[i for i in removed if plan[i]!=state['current'][0]['ability_actor_names'].get(i)],expected_costs=copy.deepcopy(costs)))
            began=time.monotonic();result,evidence=execute(trial,offset+len(runs));elapsed=time.monotonic()-began
            accepted=False;reason='完整性、顺序或溢出圣水不合格'
            if qualifies(trial,result):
                try:actual,paid=plan_reader(trial,result)
                except ValueError as error:reason=str(error)
                else:accepted=actual==plan and paid==costs;reason='实际技能身份或费用序列改变' if not accepted else '完整、顺序和溢出校验通过'
            new_score=score((trial,result,evidence,costs)) if accepted else (1,-result.get('native_accepted',0))
            improved=accepted and new_score<state['best_score'];reward=8 if improved else (2 if accepted else .1)
            if new_score<state['best_score']:state.update(current=copy.deepcopy((trial,result,evidence,costs)),best_score=new_score)
            self._merge(state,result,costs);state['evaluations']+=1
            if phase=='diverse-coverage':state['coverage_evaluations']+=1
            if operator in self.weights:self.weights[operator]=max(.1,.8*self.weights[operator]+.2*reward)
            _,_,space=self._space(state)
            decision=dict(seed=seed,operator=operator,phase=phase,changed_indices=trial['same_cost_alns']['changed_indices'],actors=plan,expected_costs=copy.deepcopy(costs),
                qualified=accepted,improved=improved,reason=reason,seconds=round(elapsed,3),weights=dict(self.weights),
                observed_space_size=space,evaluation_only=True,exhaustive=False)
            self.history.append(decision);runs.append((trial,result,evidence,costs,decision))
        return runs
    def snapshot(self):
        spaces=[]
        for (seed,costs),state in self.states.items():
            keys,choices,size=self._space(state);small=size<=self.small_space_limit
            remaining=sum(self.signature(dict(zip(keys,v))) not in self.visited.get(seed,set()) for v in itertools.product(*choices)) if small else None
            spaces.append(dict(seed=seed,costs=dict(costs),observed_space_size=size,remaining=remaining,evaluations=state['evaluations'],coverage_evaluations=state['coverage_evaluations'],
                observed_domains_complete=small and remaining==0,mode='small-enumeration' if small else 'coverage-then-local',best_cost=state['best_score'][1] if state['best_score'][0]==0 else None))
        return dict(policy='same-cost-discrete-search-v2',small_space_limit=self.small_space_limit,coverage_trials=self.coverage_trials,
            weights=dict(self.weights),attempts=copy.deepcopy(self.history),seed_spaces=spaces,exhaustive=False,
            scope='已观察的同费用技能身份；未宣称覆盖未到达的引擎分支',stop_on_stagnation=False)


def refinement_schedule(screened,*,limit=3,rounds=24):
    """Rank once, then interleave retained seeds; never infer exhaustion from score."""
    selected=sorted(screened,key=lambda item:(item[0][-1],item[0][1]))[:limit]
    for round_number in range(rounds):
        for row in selected:yield round_number,row
