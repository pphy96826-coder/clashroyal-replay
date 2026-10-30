"""Read-only paired CPU benchmark on completed records of a selected live task.

No APK install, debugger, game calls, cleanup, retry or network change. Never
claims that replaying recorded results measures end-to-end native simulation.
Personal records remain in memory; stdout contains aggregate timings only.
"""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
import types
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'official-web-replay'))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--serial',required=True);p.add_argument('--task',required=True)
    p.add_argument('--seed-samples',type=int,default=10);p.add_argument('--repeats',type=int,default=20)
    a=p.parse_args()
    if not re.fullmatch(r'127\.0\.0\.1:\d{4,5}',a.serial) or not re.fullmatch(r'[a-f0-9-]{36}',a.task):raise ValueError('explicit local task required')
    if not 1<=a.seed_samples<=20 or not 1<=a.repeats<=100:raise ValueError('unbounded benchmark')
    adb=['adb','-s',a.serial]
    parent='/data/user/0/local.royale.replay.android/files/local-imports/'+a.task+'/result/'
    task=parent+'phone-playback/'
    def raw(path):
        data=subprocess.check_output(adb+['exec-out','cat',path],timeout=15)
        if len(data)>1024*1024:raise ValueError('oversized record')
        return data
    active=json.loads(raw('/data/user/0/local.royale.replay.android/files/phone-active.json'))
    if active['directory'].rstrip('/')!=task.rstrip('/'):raise ValueError('not selected active task')
    source=json.loads(raw(parent+'source.json'))
    prep=json.loads(raw(task+'native-preparation/preparation-delayed.json'))
    names=subprocess.check_output(adb+['shell','ls',task],text=True,timeout=15).splitlines()
    samples=[]
    for name in names:
        match=re.fullmatch(r'seed-(\d+)-candidate-(\d+)-source-execution.json',name)
        if match and int(match[1])<a.seed_samples:samples.append((int(match[1]),int(match[2]),name))
    samples.sort();records=[json.loads(raw(task+name)) for _,_,name in samples]
    if not records:raise ValueError('no completed screening records')
    old_apk=ROOT/'releases/android-search-reuse-20261022-hotfix67/Android-Replay-20261022-hotfix67.apk'
    with zipfile.ZipFile(old_apk) as apk:
        with zipfile.ZipFile(io.BytesIO(apk.read('assets/python-runtime.zip'))) as runtime:
            previous=runtime.read('app/ability_search.py')
            previous_runner=runtime.read('app/device_playback.py')
    old=types.ModuleType('_before_screening');exec(compile(previous,'hotfix67-ability','exec'),old.__dict__)
    import ability_search as new
    def comparison(code):
        nodes=[n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name in ('page_comparison','page_tower_comparison')]
        scope={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'comparison','exec'),scope)
        return scope['page_comparison']
    before_compare=comparison(previous_runner)
    after_compare=comparison((ROOT/'android-adaptation/device/device_playback.py').read_text())
    def evaluate(module,compare):
        sys.modules['ability_search']=module
        for report in records:
            compare(source,prep,report)
            module.terminal_hp_matches(source,prep,report)
            module.damage_lower_bound(source,prep,report)
    timings={key:[] for key in ('before','after')}
    for round_index in range(7):
        for key in (('before','after') if round_index%2==0 else ('after','before')):
            module,compare=(old,before_compare) if key=='before' else (new,after_compare)
            start=time.perf_counter()
            for _ in range(a.repeats):evaluate(module,compare)
            timings[key].append((time.perf_counter()-start)/a.repeats)
    sys.modules['ability_search']=new
    status=json.loads(raw(task+'status.json'))
    # Completed deal receipts' timestamp intervals include native simulation,
    # compilation, release, per-seed ability search and the next deal probe.
    maximum=min(34,(status.get('seed_attempt') or 1)-2)
    paths=[task+'seed-'+str(i)+'-deal-0-result.json' for i in range(maximum+1)]
    stat=subprocess.check_output(adb+['shell','stat','-c','%n:%Y',*paths],text=True,timeout=15)
    stamps=[int(line.rsplit(':',1)[1]) for line in stat.splitlines()]
    intervals=[b-a for a,b in zip(stamps,stamps[1:])]
    before=statistics.median(timings['before']);after=statistics.median(timings['after'])
    print(json.dumps(dict(
        scope='host CPU on identical real captured reports, not native end-to-end A/B',
        replay_events=len(prep['events']),seed_samples=len({i for i,_,_ in samples}),records=len(records),
        finished_reports=sum(r.get('finished')==1 for r in records),paired_rounds=7,repeats=a.repeats,
        before_batch_ms=round(before*1000,3),after_batch_ms=round(after*1000,3),
        cpu_speedup=round(before/after,3),cpu_reduction_percent=round(100*(1-after/before),2),
        before_us_per_record=round(before/len(records)*1e6,2),after_us_per_record=round(after/len(records)*1e6,2),
        comparison_gates='both versions check actual elixir; CPU math only, not search strategy or quality',
        observed_seed_intervals=len(intervals),observed_baseline_seconds=sum(intervals),
        observed_baseline_mean_seconds_per_seed=round(statistics.mean(intervals),3) if intervals else None,
        observed_baseline_median_seconds_per_seed=statistics.median(intervals) if intervals else None,
        current_seed_attempt=status.get('seed_attempt'),
        artifacts_sha256=dict(before_ability=hashlib.sha256(previous).hexdigest(),
                              after_ability=hashlib.sha256((ROOT/'official-web-replay/ability_search.py').read_bytes()).hexdigest())
    ),indent=2))


if __name__=='__main__':main()
