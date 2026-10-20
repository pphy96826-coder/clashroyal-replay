"""Read-only UI/status evidence; no host replay backend or native calls."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
FILES='/data/user/0/local.royale.replay.android/files/'
JOB=re.compile(re.escape(FILES)+r'local-imports/[a-f0-9-]{36}/result/phone-playback')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--seconds',type=int,default=240)
    parser.add_argument('--name',required=True)
    parser.add_argument('--current',action='store_true',help='Observe the explicitly active job, without starting/retrying it')
    args=parser.parse_args()
    if not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}',args.serial) or not 10<=args.seconds<=600:
        raise ValueError('selected loopback instance and bounded duration required')
    if not re.fullmatch(r'[a-z0-9-]{1,64}',args.name):raise ValueError('invalid evidence name')
    output=ROOT/'private'/args.name;output.mkdir(mode=0o700)
    adb=['adb','-s',args.serial]
    def command(*parts):
        return subprocess.run(adb+list(parts),capture_output=True,timeout=10)
    def read(path):
        result=command('exec-out','cat',path)
        if result.returncode or len(result.stdout)>128*1024:return {}
        try:return json.loads(result.stdout)
        except (ValueError,UnicodeError):return {}
    original=read(FILES+'phone-active.json').get('directory','')
    if args.current and not JOB.fullmatch(original):raise ValueError('no valid active phone job')
    start=time.monotonic();last=None;last_notice=0;count=0;seen_new=args.current
    with (output/'timeline.jsonl').open('x') as log:
        while time.monotonic()-start<args.seconds:
            active=read(FILES+'phone-active.json');directory=active.get('directory','')
            service=read(FILES+'phone-service-state.json')
            state=read(directory+'/status.json') if JOB.fullmatch(directory) else {}
            if directory and directory!=original:seen_new=True
            request=service.get('request_id','')
            marker=read(FILES+'phone-handoffs/'+request+'.json') if re.fullmatch(r'[a-f0-9-]{36}',request) else {}
            activities=command('shell','dumpsys','activity','activities').stdout.decode(errors='replace')
            line=next((line for line in activities.splitlines() if 'topResumedActivity=' in line),'')
            foreground='game' if 'com.tencent.tmgp.supercell.clashroyale/' in line else 'console' if 'local.royale.replay.android/.MainActivity' in line else 'browser' if 'local.royale.replay.android/.BrowserActivity' in line else 'other'
            row=dict(elapsed=round(time.monotonic()-start,2),new_job=seen_new,foreground=foreground,
                     state=state.get('state'),tick=state.get('tick'),scene_initial_tick=state.get('scene_initial_tick'),
                     playback_started=state.get('playback_started'),scene_frames=state.get('scene_frames'),
                     native_roundtrip_verified=state.get('native_roundtrip_verified'),
                     service_state=service.get('state'),handoff=marker or None,directory=directory)
            log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
            key=(row['state'],foreground,service.get('state'),bool(marker),seen_new)
            if key!=last:
                if foreground in ('game','console','browser'):
                    picture=command('exec-out','screencap','-p')
                    if picture.returncode==0 and picture.stdout.startswith(b'\x89PNG'):
                        (output/('%02d-%s-%s.png'%(count,str(row['state']),foreground))).write_bytes(picture.stdout)
                count+=1
            if key!=last or time.monotonic()-last_notice>25:
                print(json.dumps(row,ensure_ascii=False),flush=True);last_notice=time.monotonic()
            last=key
            if seen_new and row['state'] in ('complete','needs_review','cancelled','stopped','monitor_expired'):
                for name in ('status.json','error.txt','scene-v1-result.json','scene-v1-terminal-result.json'):
                    result=command('exec-out','cat',directory+'/'+name)
                    if result.returncode==0:(output/name).write_bytes(result.stdout)
                break
            time.sleep(2)
    print(json.dumps(dict(evidence=str(output),observed_new_job=seen_new)),flush=True)


if __name__=='__main__':main()
