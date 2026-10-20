"""Explicit local administration: queue a released branch without starting it.

The console must be stopped so its queue writer cannot race this transaction.
No game restart, debugger attach, network request or native scene publication.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'official-web-replay'))
from client_session import ensure_current_device_binding
from diagnostic_prefix import preview_inputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',required=True)
    parser.add_argument('--authorized-preview',action='store_true',required=True)
    args=parser.parse_args()
    if not re.fullmatch('[a-f0-9-]{36}',args.job):raise ValueError('invalid private job ID')
    device=ensure_current_device_binding();adb=['adb','-s',device['serial']]
    files='/data/user/0/local.royale.replay.android/files'
    directory=files+'/local-imports/'+args.job
    def read(path):
        return subprocess.check_output(adb+['shell','cat',path],timeout=15)
    def json_read(path):return json.loads(read(path))
    def idle_writer():
        running=subprocess.run(adb+['shell','pidof','local.royale.replay.android'],capture_output=True,text=True,timeout=10)
        if running.stdout.strip():raise RuntimeError('请先关闭控制台界面；不会停止游戏或覆盖正在写入的队列')
    active=json_read(files+'/phone-active.json')
    state=json_read(active['directory']+'/status.json')
    if state.get('monitor_active',True):raise RuntimeError('当前回放仍在运行；未改队列')
    idle_writer()
    source=json_read(directory+'/result/source.json')
    source_html=read(directory+'/input.html')
    if hashlib.sha256(source_html).hexdigest()!=source['source_sha256']:raise ValueError('source HTML hash differs')
    attempts=json_read(directory+'/result/phone-playback/ability-search.json')['attempts']
    candidates=[];rejected_boundaries=[]
    for row in attempts:
        attempt=row['evidence']['attempt']
        if not re.fullmatch(r'(bootstrap-v[1-9][0-9]*|ability-candidate-[0-9]+)',attempt):raise ValueError('invalid attempt')
        base=directory+'/result/phone-playback/'
        report=json_read(base+attempt+'-source-execution.json')
        if report.get('error')!=114 or report.get('native_code')!=4:continue
        prep_path=row['evidence']['preparation']
        if not prep_path.startswith(base+'native-preparation/') or '..' in prep_path:raise ValueError('foreign preparation path')
        prep=json_read(prep_path);receipt=json_read(base+attempt+'-result.json')
        try:subset,native=preview_inputs(prep,report,receipt,authorized=args.authorized_preview)
        except ValueError as error:
            rejected_boundaries.append(dict(attempt=attempt,reason=str(error)))
            continue  # Cannot invent a boundary for an unproven prefix.
        candidates.append((subset['diagnostic_preview']['stop_tick'],attempt,prep,report,receipt,subset))
    if not candidates:raise RuntimeError('没有可安全预览的已执行分支')
    stop,attempt,prep,report,receipt,subset=max(candidates,key=lambda row:row[0])
    key=str(uuid.uuid4())
    evidence=dict(user_authorized=True,source_sha256=source['source_sha256'],
                  preparation=prep,report=report,receipt=receipt,selected_attempt=attempt)
    evidence_raw=json.dumps(evidence,ensure_ascii=False,separators=(',',':')).encode()
    queue=files+'/replay-queue';old=read(queue+'/index.json');rows=json.loads(old)
    if any(r.get('diagnostic_only') and r.get('sha256')==source['source_sha256'] and r.get('selected_attempt')==attempt for r in rows):
        print(json.dumps(dict(already_queued=True,tag=source['replay_tag'],selected_attempt=attempt)));return
    if len(rows)>=128 or sum(r['bytes'] for r in rows)+len(source_html)>256*1024*1024:raise RuntimeError('queue size limit')
    rows.append(dict(id=key,tag=source['replay_tag'],events=len(subset['events']),sha256=source['source_sha256'],bytes=len(source_html),
                     diagnostic_only=True,selected_attempt=attempt,preview_stop_tick=stop,
                     diagnostic_sha256=hashlib.sha256(evidence_raw).hexdigest()))
    output=ROOT/'output'/'queued-diagnostics'/key;output.mkdir(parents=True,exist_ok=False)
    local_html=output/(key+'.html');local_html.write_bytes(source_html)
    bundle=output/(key+'.diagnostic.json');bundle.write_bytes(evidence_raw)
    index=output/'index.json';index.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    info=subprocess.check_output(adb+['shell','stat','-c','%u:%g',queue],text=True,timeout=10).strip()
    if not re.fullmatch(r'[0-9]+:[0-9]+',info):raise RuntimeError('invalid queue owner')
    for local,name in ((local_html,key+'.html'),(bundle,key+'.diagnostic.json'),(index,'index-'+key+'.tmp')):
        target=queue+'/'+name
        subprocess.run(adb+['push',str(local),target],check=True,capture_output=True,timeout=15)
        subprocess.run(adb+['shell','chown',info,target],check=True,timeout=10)
        subprocess.run(adb+['shell','chmod','600',target],check=True,timeout=10)
    idle_writer()
    if read(queue+'/index.json')!=old:raise RuntimeError('queue changed; originals retained and not overwritten')
    subprocess.run(adb+['shell','mv',queue+'/index-'+key+'.tmp',queue+'/index.json'],check=True,timeout=10)
    if json_read(queue+'/index.json')!=rows:raise RuntimeError('queue write did not verify')
    print(json.dumps(dict(queued=True,started=False,tag=source['replay_tag'],selected_attempt=attempt,
                         preview_events=len(subset['events']),preview_stop_seconds=stop/20,queue_length=len(rows),
                         complete_replay_verified=False,excluded_unproven_boundaries=rejected_boundaries),ensure_ascii=False))


if __name__=='__main__':main()
