"""Local USB/loopback-ADB file handoff to the existing desktop backend.

Explicitly NOT a standalone phone runtime. No socket listener or HTTP calls.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='local.royale.replay.android'
ID=re.compile('[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}')


GAME='com.tencent.tmgp.supercell.clashroyale'


def game_generation(adb):
    boot=subprocess.check_output(adb+['shell','cat','/proc/sys/kernel/random/boot_id'],text=True,timeout=10).strip()
    result=subprocess.run(adb+['shell','pidof',GAME],capture_output=True,text=True,timeout=10)
    pid=result.stdout.strip()
    if not pid.isdigit():return ''
    stat=subprocess.check_output(adb+['shell','cat','/proc/'+pid+'/stat'],text=True,timeout=10)
    started=stat[stat.rfind(')')+2:].split()[19]
    return hashlib.sha256((boot+':'+pid+':'+started).encode()).hexdigest()


def game_foreground(adb):
    result=subprocess.check_output(adb+['shell','dumpsys','activity','activities'],text=True,timeout=10)
    return any(('topResumedActivity=' in line or 'mResumedActivity:' in line) and GAME+'/' in line for line in result.splitlines())


def checked_job(doc,identifier,token,now):
    if not ID.fullmatch(identifier) or doc.get('id')!=identifier or doc.get('schema')!='royale-replay.android-job.v1':raise ValueError('invalid job identity')
    if not secrets.compare_digest(str(doc.get('token','')),token):raise ValueError('different pairing session; not executed')
    if doc.get('command') not in ('play','stop'):raise ValueError('unsupported command')
    created=doc.get('created_at')
    if type(created) not in (int,float) or not now-900<=created<=now+60:raise ValueError('expired or future job; needs review')
    speed=doc.get('speed')
    if type(speed) not in (int,float) or speed not in (.25,.5,1,2,4):raise ValueError('invalid speed')
    if doc['command']=='play' and not re.fullmatch('[a-f0-9]{64}',str(doc.get('source_sha256',''))):raise ValueError('source hash missing')
    return doc


class Transport:
    def __init__(self,binding_loader):
        self.binding_loader=binding_loader;self.binding=binding_loader();self.adb=['adb','-s',self.binding['serial']];self.helper=None
        available=subprocess.run(self.adb+['shell','run-as',PACKAGE,'id','-u'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)
        if available.returncode==0 and available.stdout.strip().isdigit() and available.stdout.strip()!='0':return
        if subprocess.check_output(self.adb+['shell','id','-u'],text=True,timeout=10).strip()!='0':raise RuntimeError('run-as unavailable and no existing authorized adb root; no access bypass attempted')
        self.uid=int(subprocess.check_output(self.adb+['shell','stat','-c','%u','/data/user/0/'+PACKAGE+'/files'],text=True,timeout=10).strip())
        if not 10000<=self.uid<=199999:raise ValueError('invalid own app uid')
        ndk=Path(os.environ.get('ROYALE_NDK_BIN',str(Path.home()/'Library/Android/sdk/ndk/30.0.16248370/toolchains/llvm/prebuilt/darwin-x86_64/bin')))
        source=ROOT/'native/app_files.cpp';directory=ROOT/'build';directory.mkdir(exist_ok=True)
        binary=directory/('app-files-'+hashlib.sha256(source.read_bytes()).hexdigest()[:16])
        if not binary.exists():subprocess.run([str(ndk/'clang++'),'--target=aarch64-linux-android24','-std=c++17','-O2','-Wall','-Wextra','-Werror','-static-libstdc++',str(source),'-o',str(binary)],check=True,timeout=45)
        digest=hashlib.sha256(binary.read_bytes()).hexdigest();self.helper='/data/local/tmp/royale_own_app_files_'+digest[:16]
        existing=subprocess.run(self.adb+['shell','sha256sum',self.helper],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)
        if existing.returncode:
            subprocess.run(self.adb+['push',str(binary),self.helper],check=True,stdout=subprocess.PIPE,timeout=15)
            subprocess.run(self.adb+['shell','chmod','755',self.helper],check=True,timeout=10)
        observed=subprocess.check_output(self.adb+['shell','sha256sum',self.helper],text=True,timeout=10).split()[0]
        if observed!=digest:raise ValueError('own-app helper changed; not overwritten')
    def verify(self):
        if self.binding_loader()!=self.binding:raise RuntimeError('selected instance endpoint changed; old session not migrated')
    def read(self,relative,limit):
        self.verify()
        if not re.fullmatch(r'files/(?:jobs/[a-f0-9-]{36}\.(?:json|html)|[a-z0-9-]+\.json)',relative):raise ValueError('invalid private relative path')
        command=self.adb+['exec-out',self.helper,str(self.uid),'read',relative.removeprefix('files/')] if self.helper else self.adb+['exec-out','run-as',PACKAGE,'cat',relative]
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        if result.returncode:raise FileNotFoundError(relative)
        if len(result.stdout)>limit:raise ValueError('private payload exceeds limit')
        self.verify();return result.stdout
    def write(self,name,doc):
        self.verify()
        if not re.fullmatch(r'(?:pairing|status-[a-f0-9-]{36})\.json',name):raise ValueError('invalid status name')
        # Only validated fixed basenames enter the Android shell, never HTML.
        command=self.adb+['shell','-T',self.helper,str(self.uid),'write',name] if self.helper else self.adb+['shell','-T',"run-as "+PACKAGE+" sh -c 'umask 077; cat > files/"+name+".tmp && mv files/"+name+".tmp files/"+name+"'"]
        subprocess.run(command,input=json.dumps(doc,ensure_ascii=False).encode(),check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        self.verify()
    def jobs(self):
        self.verify();command=self.adb+['exec-out',self.helper,str(self.uid),'list'] if self.helper else self.adb+['exec-out','run-as',PACKAGE,'ls','files/jobs']
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        if result.returncode:return []
        names=result.stdout.decode('utf-8').splitlines()
        if len(names)>1000:raise ValueError('too many retained jobs; inspect instead of auto-cleanup')
        return sorted(name[:-5] for name in names if name.endswith('.json') and ID.fullmatch(name[:-5]))
    def clock(self):return int(subprocess.check_output(self.adb+['shell','date','+%s'],text=True,timeout=10).strip())
    def status(self,identifier,state,message,**extra):
        if not ID.fullmatch(identifier):raise ValueError('invalid status identity')
        self.write('status-'+identifier+'.json',dict(id=identifier,state=state,message=str(message)[:4000],**extra))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',type=Path,required=True)
    parser.add_argument('--enable-native',action='store_true');parser.add_argument('--seconds',type=int,default=1800);args=parser.parse_args()
    if not 10<=args.seconds<=7200:raise ValueError('bounded session duration required')
    backend=args.backend.resolve()
    if not (backend/'desktop_worker.py').is_file():raise FileNotFoundError('existing desktop backend required')
    os.umask(0o077);sys.path.insert(0,str(backend))
    private=ROOT/'private';private.mkdir(exist_ok=True,mode=0o700)
    session_lock=(private/'companion.lock').open('a+')
    try:fcntl.flock(session_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Android companion already running; pairing not replaced')
    from client_session import ensure_current_device_binding,current_device_binding
    ensure_current_device_binding()
    transport=Transport(current_device_binding)
    if subprocess.check_output(transport.adb+['shell','getprop','ro.product.cpu.abi'],text=True,timeout=10).strip()!='arm64-v8a':raise RuntimeError('only existing ARM64 test instance allowed')
    token=secrets.token_hex(32);start=time.monotonic();start_device=transport.clock();last_pair=0
    ledger=ROOT/'private/jobs';ledger.mkdir(parents=True,exist_ok=True,mode=0o700)
    from desktop_worker import Worker
    class PhoneWorker(Worker):
        def __init__(self):self.phone_job=None;self.last_position=0;self.generation='';super().__init__()
        def play_visible(self,html,speed):
            self.emit('status','等待官服客户端回到前台；不会在后台重复提交原生场景。')
            deadline=time.monotonic()+30
            while not game_foreground(transport.adb):
                self.player.checkpoint()
                if time.monotonic()>deadline:raise RuntimeError('请打开官服客户端并保持在前台，当前任务尚未提交原生场景')
                self.closed.wait(1)
            if game_generation(transport.adb)!=self.generation:raise RuntimeError('游戏进程已变化；保留任务，不迁移到新进程')
            self.player.play(html,speed)
        def emit(self,kind,value):
            super().emit(kind,value)
            identifier=self.phone_job
            if not identifier:return
            if kind=='status':transport.status(identifier,'preparing',value)
            elif kind in ('playing','resumed'):transport.status(identifier,'playing','原生场景已就绪；请在官服客户端观看。',attempt=value.get('attempt'))
            elif kind=='position':
                transport.status(identifier,'playing',f"原生进度 {value.get('tick',0)/20:.1f} 秒",tick=value.get('tick'),duration=value.get('duration'))
            elif kind in ('error','cancelled','stopped','complete'):
                state={'error':'failed','cancelled':'cancelled','stopped':'cancelled','complete':'complete'}[kind]
                if kind=='error' and self.player.active:state='needs_review'
                transport.status(identifier,state,str(value) if kind!='complete' else '原生回放已到终局。',generation=self.generation)
    worker=PhoneWorker();seen=set()
    threading.Thread(target=worker.monitor,daemon=True).start()
    print(json.dumps(dict(companion_ready=True,requires_computer=True,native_enabled=args.enable_native,serial=transport.binding['serial']),ensure_ascii=False),flush=True)
    try:
        while time.monotonic()-start<args.seconds:
            now=start_device+(time.monotonic()-start)
            if time.monotonic()-last_pair>8:
                transport.write('pairing.json',dict(schema='royale-replay.android-pair.v1',token=token,heartbeat_at=int(now),
                    expires_at=start_device+args.seconds,native_enabled=args.enable_native,requires_computer=True,generation=game_generation(transport.adb)));last_pair=time.monotonic()
            for identifier in transport.jobs():
                if identifier in seen:continue
                seen.add(identifier);record=ledger/(identifier+'.json')
                if record.exists():
                    try:previous=json.loads(transport.read('files/status-'+identifier+'.json',32768))
                    except (OSError,ValueError):previous={}
                    if previous.get('state') not in ('complete','failed','cancelled','needs_review'):
                        transport.status(identifier,'needs_review','已有持久化处理记录，不自动重复提交。')
                    continue
                try:
                    doc=checked_job(json.loads(transport.read('files/jobs/'+identifier+'.json',8192)),identifier,token,now)
                    if not args.enable_native:raise ValueError('native execution not enabled in this session')
                    if doc['command']=='play':
                        if worker.busy or worker.playback or worker.player.active:raise ValueError('已有原生任务或未释放现场，拒绝覆盖或重复提交')
                        raw=transport.read('files/jobs/'+identifier+'.html',25*1024*1024)
                        if hashlib.sha256(raw).hexdigest()!=doc['source_sha256']:raise ValueError('HTML hash differs from Android selection')
                        folder=ledger/identifier;folder.mkdir(mode=0o700)
                        html=folder/'source.html';html.write_bytes(raw)
                        with record.open('x',encoding='utf-8') as stream:json.dump(dict(state='claimed',source_sha256=doc['source_sha256'],requires_computer=True),stream)
                        worker.phone_job=identifier;worker.generation=game_generation(transport.adb)
                        transport.status(identifier,'preparing','电脑后端已接收原始 HTML，开始完整校验。')
                        worker.player.cancel.clear()
                        worker.launch(lambda html=html,speed=doc['speed']:worker.play_visible(str(html),speed))
                    else:
                        if doc.get('target_job')!=worker.phone_job or not worker.phone_job:raise ValueError('Stop does not match this session owned replay')
                        with record.open('x',encoding='utf-8') as stream:json.dump(dict(state='claimed-stop',target_job=worker.phone_job),stream)
                        worker.command(dict(command='stop'));transport.status(identifier,'complete','已请求安全取消；未强杀原生任务。')
                except Exception as error:transport.status(identifier,'failed',str(error))
            time.sleep(1)
    finally:
        worker.closed.set();worker.player.cancel.set()
        try:transport.write('pairing.json',dict(native_enabled=False,heartbeat_at=0,expires_at=0,requires_computer=True))
        except (OSError,RuntimeError,subprocess.SubprocessError):
            # A dead emulator cannot receive cleanup. Preserve the first error;
            # the bounded heartbeat makes its old pairing unusable on recovery.
            print(json.dumps(dict(companion_cleanup='device unavailable; no restart attempted',requires_computer=True)),file=sys.stderr,flush=True)
        # No process kill, implicit game restart or automatic task resubmission.


if __name__=='__main__':main()
