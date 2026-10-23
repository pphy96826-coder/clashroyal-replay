"""Read-only search narration. No search choices, game reads or task submissions."""
import copy,json,time
from pathlib import Path
from source_completion import source_completed,source_failure
from ability_search import elixir_check,elixir_rows,ELIXIR_MISMATCH_COST,elixir_margin

class Progress:
    def __init__(self,directory,source,compare,breakdown):
        self.directory=Path(directory);self.source=source;self.compare=compare;self.breakdown=breakdown
        self.value=dict(schema='royale-replay.prediction-progress.v1',candidate=0,phase='准备预测',event_count=len(source.get('actions',[])),
                        best=None,last=None,history=[])
        self.started=time.monotonic();self.phase_started=self.started
    def snapshot(self):
        value=copy.deepcopy(self.value);value['phase_seconds']=round(time.monotonic()-self.phase_started,1)
        value['phase_started_at']=time.time()-(time.monotonic()-self.phase_started);return value
    def observe(self,method,*args):
        # Narration must never change candidate selection or fail a native task.
        try:getattr(self,method)(*args)
        except Exception as error:self.value['narration_error']=str(error)[:160]
    def event(self,kind,detail):
        entry=dict(type=kind,at=time.time(),**detail)
        with (self.directory/'prediction-process.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(entry,ensure_ascii=False)+'\n')
    def begin(self,candidate,attempt):
        self.value.update(candidate=self.value['candidate']+1,seed=candidate['initialization_only']['rndSeed'],
            choice_count=len(candidate.get('ability_actor_names') or candidate.get('ability_target_choices') or {}),attempt=attempt,phase='编译本轮组件')
        self.value['same_cost_alns']=copy.deepcopy(candidate.get('same_cost_alns'))
        self.phase_started=time.monotonic()
        self.event('candidate_started',dict(candidate=self.value['candidate'],attempt=attempt,seed=self.value['seed'],choices=candidate.get('ability_target_choices') or {},fixed_actors=candidate.get('ability_actor_names') or {}))
    def reused(self,evidence):
        self.stage('复用同一任务内已安全释放的相同候选')
        self.event('candidate_reused',dict(attempt=evidence.get('attempt')))
    def stage(self,phase):
        self.value['phase']=phase;self.phase_started=time.monotonic()
    def finish(self,candidate,report):
        count=len(candidate['events']);complete=source_completed(report,count)
        row=dict(candidate=self.value['candidate'],attempt=self.value.get('attempt'),seed=self.value.get('seed'),
                 tick=report.get('tick'),accepted=report.get('native_accepted',0),event_count=count,complete=complete,
                 choices=copy.deepcopy(candidate.get('ability_target_choices') or {}),fixed_actors=copy.deepcopy(candidate.get('ability_actor_names') or {}),skills=[])
        names={r['event_index']:r['actors'][r['selected_ordinal']].get('name','') for r in report.get('ability_observations',[])
               if r.get('phase')=='selected' and type(r.get('selected_ordinal')) is int and 0<=r['selected_ordinal']<len(r.get('actors',[]))}
        for d in report.get('diagnostics') or []:
            if isinstance(d.get('actor'),dict):row['skills'].append(dict(index=d.get('index'),tick=d.get('tick'),owner=d.get('owner'),
                actor=names.get(d.get('index')) or str(d['actor'].get('id','')),cost=d['actor'].get('cost')))
        row['elixir']=elixir_rows(self.source,report);matched,_=elixir_check(self.source,report)
        if complete:
            tier,cost=self.compare(self.source,candidate,report);row.update(tier=tier,match_cost=cost,**self.breakdown(self.source,candidate,report))
            row['qualified']=matched is True and len(row['elixir'])==2 and all(r.get('matched') is True for r in row['elixir']) and type(cost) is int and cost<ELIXIR_MISMATCH_COST
            row['reason']='完整执行；溢出圣水与网页一致' if matched is True else '完整执行；网页或模拟未提供完整溢出数据' if matched is None else '丢弃：溢出圣水与网页不一致'
            if row['qualified'] and any(r.get('strict_matched') is False for r in row['elixir']):row['reason']='完整执行；溢出圣水在额外 0.05 容差内（近似）'
            if row['qualified'] and (self.value['best'] is None or cost<self.value['best']['match_cost']):self.value['best']=copy.deepcopy(row)
        elif report.get('error')==112 and report.get('native_code',0)>1:
            row['reason']='第 '+str(report.get('event_index',-1)+1)+' 条技能有 '+str(report['native_code'])+' 个合法目标，继续展开分支'
            row['next_actors']=[a.get('name','') for r in report.get('ability_observations',[]) if r.get('event_index')==report.get('event_index') and r.get('phase')=='eligible' for a in r.get('actors',[])]
        else:row['reason']='本分支未完成：'+source_failure(report)
        if not complete and any(r.get('shortfall') or (r.get('page') is not None and r.get('simulated') is not None and r['simulated']>=r['page']+.01+elixir_margin(self.source)-1e-6) for r in row['elixir']):
            row['reason']='剪枝：溢出已超出网页范围，或有出牌／技能圣水不足'
        if not complete and row['reason'].startswith('本分支未完成：'):
            from failure_recovery import explanation
            row['failure_explanation']=explanation(source_failure(report))
        self.value.update(last=row,phase='比较本轮结果')
        self.value['history']=(self.value['history']+[dict(candidate=row['candidate'],tick=row['tick'],reason=row['reason'])])[-5:]
        self.event('candidate_finished',row)
        self.phase_started=time.monotonic()
    def message(self):
        return self.value['phase']+'：第 '+str(self.value['candidate'])+' 次预演，随机种子 '+str(self.value.get('seed',''))+'。'+(
            '已有溢出校验合格的完整结果（含已标注的容差内近似）。' if self.value.get('best') else '尚无溢出圣水与网页一致的完整组合。')
