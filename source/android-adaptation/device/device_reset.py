"""Explicit, audited reset of this app's workers and owned native generation.

Never kills by process name. A native game is released before any debugger or
worker is terminated. A foreign/unproven battle leaves the reset refused.
"""
import fcntl,hashlib,json,os,re,signal,struct,subprocess,time
from pathlib import Path

COMMANDS={'play','import-source','prepare','build-component','check-tools','check-native-tools','recover','finish','release-preparation'}
TOKENS=('libphone_replay_','libcr_web_','libcr_private_','libcr_direct_')

def read(path):return json.loads(path.read_text())
def beneath(path,root):
    try:return path.resolve().is_relative_to(root.resolve()) and path.resolve()!=root.resolve()
    except (OSError,ValueError):return False

def process(pid,proc=Path('/proc')):
    folder=proc/str(pid)
    try:
        text=(folder/'stat').read_text();parts=text[text.rindex(')')+2:].split()
        if parts[0]=='Z':return None
        argv=[v.decode(errors='strict') for v in (folder/'cmdline').read_bytes().split(b'\0') if v]
        return dict(pid=pid,start=parts[19],parent=int(parts[1]),argv=argv)
    except (FileNotFoundError,ProcessLookupError):return None

def owned_command(argv,files):
    if len(argv)!=6 or argv[1] not in COMMANDS:return False
    home,source,output,prefix=map(Path,argv[2:])
    paths=(home,source,output) if argv[1]=='import-source' and argv[5]=='-' else (home,source,output,prefix)
    if not all(beneath(p,files) for p in paths):return False
    executable=Path(argv[0])
    if not beneath(executable,home) or executable.name!='phone_runtime':return False
    try:
        member=executable.resolve().relative_to(home.resolve()).as_posix()
        expected=read(home/'runtime-files.json').get(member)
        return bool(expected) and hashlib.sha256(executable.read_bytes()).hexdigest()==expected
    except (OSError,ValueError,KeyError):return False

def worker_snapshot(files,proc=Path('/proc')):
    rows={}
    for entry in proc.iterdir():
        if not entry.name.isdigit():continue
        try:row=process(int(entry.name),proc)
        except (OSError,ValueError,UnicodeError,IndexError):continue
        if row:rows[row['pid']]=row
    owned={pid for pid,row in rows.items() if pid!=os.getpid() and owned_command(row['argv'],files)}
    # Children must still execute this app's private helper/compiler binaries.
    for _ in range(16):
        added={pid for pid,row in rows.items() if row['parent'] in owned and pid not in owned
               and row['argv'] and beneath(Path(row['argv'][0]),files)}
        if not added:break
        owned.update(added)
    return [rows[pid] for pid in sorted(owned)]

def terminate(row,signum,proc=Path('/proc'),kill=os.kill):
    current=process(row['pid'],proc)
    if current is None:return False
    if current['start']!=row['start'] or current['argv']!=row['argv']:
        raise RuntimeError('worker PID reused; reset refused')
    kill(row['pid'],signum);return True

def jobs_for(files):
    jobs=list((files/'local-imports').glob('*/result/phone-playback'))
    if len(jobs)>2048:raise ValueError('too many reset job records')
    for job in jobs:
        if job.is_symlink() or not beneath(job,files/'local-imports'):raise ValueError('unowned replay job')
    return jobs

def game_release_plan(jobs,workers):
    """Read-only plan. All live components must belong to recorded jobs."""
    from device_session import ReadOnlySession,start_time
    from device_playback import live_scene
    from scene_start_contract import require_idle_lobby
    from device_runtime import scene_state
    from mumu_runtime import component_code_ranges
    from mumu_platform import system_env
    package='com.tencent.tmgp.supercell.clashroyale'
    value=subprocess.run(['/system/bin/pidof',package],capture_output=True,text=True,env=system_env(),timeout=5)
    if value.returncode==1 and not value.stdout.strip():return None
    if value.returncode or not re.fullmatch(r'[1-9][0-9]*',value.stdout.strip()):raise ValueError('ambiguous game process')
    pid=int(value.stdout.strip());generation=start_time((Path('/proc')/str(pid)/'stat').read_text())
    records=[]
    for job in jobs:
        for binding_path in job.glob('*-binding.json'):
            if binding_path.name.endswith('-loader-binding.json'):continue
            binding=read(binding_path);identity=binding.get('identity') or {}
            if identity.get('pid')!=pid or identity.get('process_start_time')!=generation:continue
            component_path=job/(binding_path.name.removesuffix('-binding.json')+'-component.json')
            if component_path.is_file():records.append((binding,read(component_path)))
    maps=(Path('/proc')/str(pid)/'maps').read_text()
    mapped={line.split()[-1] for line in maps.splitlines() if any(t in line for t in TOKENS)}
    known={c['device_path']:c for _,c in records}
    if not mapped<=known.keys():raise RuntimeError('unowned native component; game reset refused')
    tracer=int(next(line.split()[1] for line in (Path('/proc')/str(pid)/'status').read_text().splitlines() if line.startswith('TracerPid:')))
    if tracer and tracer not in {r['pid'] for r in workers}:raise RuntimeError('foreign debugger; game reset refused')
    if not mapped and not tracer:return None
    if not records:raise RuntimeError('no bound game identity; reset refused')
    identity=records[-1][0]['identity'];session=ReadOnlySession(identity)
    session.verify()
    for path in mapped:
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=known[path]['sha256']:raise ValueError('owned component changed')
    current=live_scene(identity)
    try:require_idle_lobby(scene_state(identity))
    except ValueError:
        # An active scene must have this tool's exact cloned replay callbacks.
        scene_components=[c for b,c in records if b.get('scene') is True and c['device_path'] in mapped]
        if not current['controller'] or not current['domain'] or not scene_components:raise RuntimeError('foreign battle; game reset refused')
        ranges=[]
        for component in scene_components:ranges+=component_code_ranges(session,component)
        original=struct.unpack('<128Q',session.read(session.base+0x1bebd08,1024))
        cloned=struct.unpack('<128Q',session.read(session.pointer(current['controller']),1024));slots=(0x68//8,0x78//8)
        if any(cloned[n]!=original[n] for n in range(128) if n not in slots):raise RuntimeError('foreign controller; reset refused')
        if not all(any(low<=cloned[n]&0x00ffffffffffffff<high for low,high in ranges) for n in slots):raise RuntimeError('foreign replay callbacks')
        if struct.unpack('<i',session.read(current['domain']+0x20,4))[0]!=4:raise RuntimeError('not a local replay domain')
    session.verify()
    return identity

def run(request,output,prefix):
    files=request.parents[2]
    with (files/'reset-operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return perform(request,output,prefix)

def perform(request,output,prefix):
    files=request.parents[2];owner=files.stat();payload=read(request)
    marker=files/'reset-in-progress.json'
    if (request.name!='request.json' or request.parent.parent!=files/'process-resets'
        or payload.get('schema')!='royale-replay.reset.v1' or payload.get('user_authorized') is not True
        or not re.fullmatch(r'[a-f0-9-]{36}',payload.get('id','')) or request.parent.name!=payload['id']
        or read(marker)!=payload):raise ValueError('explicit private reset request required')
    output.mkdir(mode=0o700);os.chown(output,owner.st_uid,owner.st_gid)
    proof=dict(schema='royale-replay.reset-result.v1',id=payload['id'],reset_completed=False,workers=[],game_restarted=False)
    def save():
        path=output/'result.json';path.write_text(json.dumps(proof,ensure_ascii=False,indent=2));os.chown(path,owner.st_uid,owner.st_gid)
    try:
        jobs=jobs_for(files)
        for job in jobs:
            stop=job/'stop-request.json'
            if not stop.exists():stop.write_text(json.dumps(dict(user_requested_reset=True,id=payload['id'])))
        # Cooperative cancellation first, without interrupting a published call.
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            workers=worker_snapshot(files)
            if not workers:break
            time.sleep(.25)
        workers=worker_snapshot(files)
        identity=game_release_plan(jobs,workers)
        if identity:
            from device_session import ReadOnlySession
            from device_playback import generation_released
            from mumu_platform import system_env
            # End the proven game generation BEFORE killing its debugger/worker.
            ReadOnlySession(identity).verify()
            subprocess.run(['/system/bin/am','force-stop','com.tencent.tmgp.supercell.clashroyale'],check=True,capture_output=True,timeout=15,env=system_env())
            proof['game_identity']=identity
        for sig in (signal.SIGTERM,signal.SIGKILL):
            for row in reversed(workers):
                if terminate(row,sig):proof['workers'].append(dict(pid=row['pid'],start=row['start'],signal=int(sig)))
            time.sleep(.5)
        if identity:
            if not generation_released(identity):raise RuntimeError('game generation still alive; reset not complete')
            subprocess.run(['/system/bin/am','start','-n','com.tencent.tmgp.supercell.clashroyale/com.supercell.titan.tencent.GameAppTencent'],check=True,capture_output=True,timeout=20,env=system_env())
            proof['game_restarted']=True
        if worker_snapshot(files):raise RuntimeError('owned worker still running; reset not complete')
        with (files/'phone-operation.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            from device_playback import publish_private_receipts
            for job in jobs:
                path=job/'status.json'
                if not path.is_file():continue
                state=read(path)
                # The reset receipt records release; retain original simulation
                # status and all native diagnostics as historical evidence.
                if state.get('monitor_active') or state.get('state') not in ('complete','stopped','released','failed_recovered','failed_before_native'):
                    backup=job/('status-before-reset-'+payload['id']+'.json');backup.write_bytes(path.read_bytes());os.chown(backup,owner.st_uid,owner.st_gid)
                    state.update(state='stopped',monitor_active=False,reset_id=payload['id'],updated_at=time.time(),message='已重置本控制台回放进程；原始回放、队列和诊断记录保留。')
                    temp=job/'reset-status.tmp';temp.write_text(json.dumps(state,ensure_ascii=False));os.chown(temp,owner.st_uid,owner.st_gid);temp.replace(path)
                publish_private_receipts(job,owner)
            proof.update(reset_completed=True,operation_lock_released=True,completed_at=time.time());save()
    except Exception as error:
        proof['error']=str(error);save();raise
