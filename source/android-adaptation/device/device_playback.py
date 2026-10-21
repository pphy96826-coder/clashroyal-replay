"""Phone-only orchestration of the audited replay pipeline.

No ADB, host service, sockets, APK patch or shared client patch. Each native
publication has an immutable attempt; a pending/failed task is never repeated.
"""
import contextlib
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid

from device_session import ReadOnlySession, start_time, bind
from device_metadata import run as metadata
from device_runtime import scene_state,SceneSnapshotChanged
from device_build import run as compile_component
from scene_start_contract import require_idle_lobby
from timing_policy import apply_offset, GLOBAL_DELAY_TICKS
from align_native_deal import align,calibrate,deck_fingerprint
from finalize_replay import finalize
from proc_maps import MapsSnapshotError,diagnostics as maps_diagnostics
from mumu_platform import enabled as mumu_enabled,system_env,host_binary
from seed_search_control import BestRequested,requested as best_requested,choose_trials,search_reasons


PREPARE_AHEAD_SECONDS=7200
# The page carries no battle random seed. Some abilities (e.g. Skeleton King's
# summon) consume the engine RNG, so a fixed seed can end differently from the
# page. Only an actual Hunter play or identifiable Skeleton King ability
# enables retries when final tower HP differs. Every candidate must fully run.
SEED_ATTEMPTS=60
PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different')


def page_comparison(source, preparation, report):
    """Compare a fully executed run with the page's final towers.

    Compare each king and source-ordered surviving princess HP, never totals.
    A compacted one-element HP list cannot establish which tower was destroyed.
    """
    from tower_profiles import oracle_tower_pairs
    state=report.get('battle_state') or {}
    crowns={};page_crowns={};difference=0;same_towers=True;exact=True
    for deck in source['decks']:
        owner=deck['proposed_native_owner'];pairs=oracle_tower_pairs(deck,preparation,state)
        if pairs is None:return 'different',None
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


def seed_plan(source_sha256, original, count=SEED_ATTEMPTS):
    """Deterministic, reproducible int32 seeds derived from the source hash."""
    seeds=[]
    for n in range(count*4):
        value=int.from_bytes(hashlib.sha256((source_sha256+':seed:'+str(n)).encode()).digest()[:4],'big')
        value=value-2**32 if value>=2**31 else value
        if value!=original and value not in seeds:seeds.append(value)
        if len(seeds)==count:break
    return seeds


def retry_seed_plan(source_sha256,original,initial):
    """An advisory seed must not hide the original or consume duplicate trials."""
    seeds=([original] if initial!=original else [])+[seed for seed in seed_plan(source_sha256,original) if seed!=initial]
    return seeds[:SEED_ATTEMPTS]


def read(path):return json.loads(path.read_text())


def write_new(path, value):
    with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def publish_private_receipts(directory,owner):
    """Transfer owned receipts before announcing a terminal state to the app.

    Debugger subprocesses create root-only files. Announcing completion first
    races the service's terminal verification and can turn a played match into
    request_failed. Keep files private; only restore their owning application.
    """
    paths=sorted(directory.rglob('*'),reverse=True)
    if directory.is_symlink() or any(path.is_symlink() for path in paths):
        raise ValueError('unexpected link in private replay job')
    for path in paths:os.chown(path,owner.st_uid,owner.st_gid)
    os.chown(directory,owner.st_uid,owner.st_gid)


def game_foreground():
    """A boolean only; never retain other applications' activity contents."""
    result=subprocess.run(['/system/bin/dumpsys','activity','activities'],capture_output=True,timeout=5,env=system_env())
    if result.returncode or len(result.stdout)>1024*1024:return False
    return any(('topResumedActivity=' in line or 'mResumedActivity:' in line)
               and 'com.tencent.tmgp.supercell.clashroyale/' in line
               for line in result.stdout.decode(errors='replace').splitlines())


def wait_idle_lobby(identity, *, progress, cancellation, timeout=120):
    """Wait before the FIRST scene attempt, never retry a native publication.

    Activity resume can precede the loading screen, then the ordinary lobby.
    Two seconds of foreground + strict idle observations are required; the
    native gate still independently checks immediately before component load.
    """
    deadline=time.monotonic()+timeout;stable_since=None
    while time.monotonic()<deadline:
        cancellation()
        # Generation/read errors are not idle states and must fail closed.
        try:state=scene_state(identity)
        except SceneSnapshotChanged:
            # No pointer/result is accepted. Observe the same generation again
            # before first publication; ordinary read/identity errors propagate.
            stable_since=None
            progress('waiting_lobby','正在切换游戏大厅；等待当前界面稳定，尚未提交回放。')
            time.sleep(.25)
            continue
        idle=False
        try:require_idle_lobby(state);idle=True
        except ValueError:pass
        if game_foreground() and idle:
            if stable_since is None:stable_since=time.monotonic()
            if time.monotonic()-stable_since>=2:return
        else:stable_since=None
        progress('waiting_lobby','已打开游戏；等待启动加载结束、大厅稳定就绪。尚未提交回放，不会覆盖其他对局。')
        time.sleep(1)
    raise Cancelled('idle foreground lobby not ready; scene was not published')


def checked_receipt(receipt, *, scene=False, execute=False):
    if receipt.get('errors') or not receipt.get('detached'):
        raise RuntimeError('native attempt retained, no retry: '+str(receipt.get('errors')))
    if scene:
        if not receipt.get('native_replay_scene_present') or receipt.get('local_driver',{}).get('error'):
            raise RuntimeError('scene still loading; only observe original owner')
    else:
        from mumu_ownership import released_resources
        if not receipt.get('source_bootstrap_verified') or not (receipt.get('component_unloaded') or released_resources(receipt)):
            raise RuntimeError('initialization or cleanup did not complete')
    if execute and not scene and not receipt.get('private_source_execution_complete'):
        raise RuntimeError('incomplete source execution; no scene publication')


class EventDebugger:
    """Embedded LLDB has no CLI event thread to advance its PUBLIC state.

    Removing listener events commits running/stopped transitions. Never ignore
    a signal or auto-resume a crash; only deliver already emitted events.
    """
    def __init__(self,debugger,lldb):
        self.core=debugger;self.lldb=lldb;self.thread=None;self.stop=threading.Event();self.error=None
    def __getattr__(self,name):return getattr(self.core,name)
    def drain(self):
        event=self.lldb.SBEvent()
        while self.core.GetListener().GetNextEvent(event):pass
    def SetAsync(self,enabled):
        if self.thread:
            self.stop.set();self.thread.join(timeout=2)
            if self.thread.is_alive():raise RuntimeError('local debugger event loop did not stop')
            self.thread=None
        self.drain();self.core.SetAsync(enabled)
        if enabled:
            self.stop.clear()
            def pump():
                try:
                    while not self.stop.is_set():self.drain();self.stop.wait(.01)
                except BaseException as error:self.error=error
            self.thread=threading.Thread(target=pump,daemon=True);self.thread.start()
        if self.error:raise RuntimeError('local debugger event delivery failed: '+str(self.error))


class Debugger:
    def __init__(self,prefix):
        from mumu_platform import native_debugger_runtime
        runtime=native_debugger_runtime() if mumu_enabled() else None
        library=runtime/'lib/liblldb.so' if runtime else prefix/'lib/liblldb.so'
        sys.path.insert(0,str((runtime or prefix)/'lib/python3.14/site-packages'))
        if '_lldb' not in sys.modules:
            spec=importlib.util.spec_from_file_location('_lldb',str(library))
            native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
            sys.modules['_lldb']=native;sys.modules['lldb._lldb']=native
        import lldb
        self.lldb=lldb
        self.translated=mumu_enabled()
        os.environ['LLDB_DEBUGSERVER_PATH']=str(host_binary('lldb-server') if self.translated else prefix/'bin/lldb-server')
        lldb.SBDebugger.Initialize()
        self.debugger=EventDebugger(lldb.SBDebugger.Create(),lldb);self.debugger.SetAsync(False)
        if self.translated:
            # Pinned address/byte checks do not depend on remote symbol tables.
            # Keep module sections and function bounds for reliable unwind;
            # avoid eagerly fetching entire translated module symbol tables.
            for command in ('settings set target.memory-module-load-level partial','settings set target.preload-symbols false'):
                result=lldb.SBCommandReturnObject()
                self.debugger.GetCommandInterpreter().HandleCommand(command,result)
                if not result.Succeeded():raise RuntimeError('MuMu debugger configuration failed: '+str(result.GetError()))

    def close(self):
        self.debugger.SetAsync(False)
        self.lldb.SBDebugger.Destroy(self.debugger.core)
        self.lldb.SBDebugger.Terminate()

    def run(self,directory,attempt,*,scene=False,action='start',receipt=None,observe_original=False):
        began=time.monotonic();measure={}
        lldb=self.lldb;binding=read(directory/(attempt+'-binding.json'))
        identity=binding['identity'];session=ReadOnlySession(identity)
        session.verify()
        status=(session.proc/'status').read_text()
        if 'TracerPid:\t0' not in status.splitlines():raise RuntimeError('another debugger owns game')
        # Fresh verification before attaching the exact pinned generation.
        pin_values=session.read_many([(int(pin['address'],0),pin['size']) for pin in binding['pins']])
        for pin,raw in zip(binding['pins'],pin_values):
            if hashlib.sha256(raw).hexdigest()!=pin['sha256']:
                raise RuntimeError('code changed before attach')
        target=self.debugger.CreateTarget('/system/bin/app_process64')
        measure['verify_and_target_seconds']=time.monotonic()-began
        if not target.IsValid():raise RuntimeError('Android target creation failed')
        self.debugger.SetSelectedTarget(target)
        process=None;attachment=None
        try:
            error=lldb.SBError()
            if self.translated:
                from mumu_debugger import Attachment
                with (directory/(attempt+'-server.log')).open('a') as log:
                    attachment=Attachment(lldb,target,self.debugger.GetListener(),identity['pid'],log)
                process=attachment.process
            else:process=target.AttachToProcessWithID(self.debugger.GetListener(),identity['pid'],error)
            if not error.Success() or not process.IsValid():raise RuntimeError('local game attach failed: '+str(error))
            session.verify()
            attached=time.monotonic();measure['attach_seconds']=attached-began-measure['verify_and_target_seconds']
            if scene:
                import run_scene_gate as gate
                gate.ROOT=directory
                name=receipt or attempt
                gate.run(self.debugger,attempt,action,name)
            else:
                import phone_bootstrap_gate as gate
                name=receipt or attempt
                gate.run(self.debugger,directory,attempt,observe_original=observe_original,receipt=receipt)
            measure['native_gate_seconds']=time.monotonic()-attached
            return read(directory/(name+'-result.json'))
        finally:
            self.debugger.SetAsync(False)
            if process and process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):
                if process.GetState()==lldb.eStateRunning:process.Stop()
                if not process.Detach().Success():raise RuntimeError('detach failed; preserve native owner')
            self.debugger.DeleteTarget(target)
            if attachment:attachment.close()
            measure['total_seconds']=time.monotonic()-began
            measure['detach_seconds']=measure['total_seconds']-sum(measure.get(key,0) for key in ('verify_and_target_seconds','attach_seconds','native_gate_seconds'))
            write_new(directory/((receipt or attempt)+'-debug-timing.json'),measure)


def publish_inputs(directory,build,observation,attempt):
    """Only own fresh staging directory, readable by this pinned game's group."""
    binding=read(build/'binding.json');session=ReadOnlySession(binding['identity'])
    maps=session.verify()
    from mumu_ownership import retained_paths,assert_component_ownership
    owned=retained_paths(directory,binding['identity'],session) if binding['identity'].get('native_transport')=='mumu-nativebridge-v1' else set()
    assert_component_ownership(maps,owned)
    state=(session.proc/'status').read_text().splitlines()
    gid=int(next(line for line in state if line.startswith('Gid:')).split()[1])
    if not 10000<=gid<200000:raise RuntimeError('unexpected game group')
    staged=Path('/data/local/tmp')/('royale-phone-'+uuid.uuid4().hex)
    staged.mkdir(mode=0o700)
    binary=Path(binding['binary_path']);raw=binary.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=binding['binary_sha256']:raise RuntimeError('component changed after compile')
    target=staged/binary.name
    with target.open('xb') as stream:stream.write(raw)
    os.chown(target,0,gid);os.chmod(target,0o640)
    os.chown(staged,0,gid);os.chmod(staged,0o750)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=binding['binary_sha256']:raise RuntimeError('staged component differs')
    write_new(directory/(attempt+'-binding.json'),binding)
    loader=read(observation/'loader-profile.json')
    if loader['identity']!=binding['identity']:raise RuntimeError('loader belongs to another generation')
    write_new(directory/(attempt+'-loader-binding.json'),loader)
    write_new(directory/(attempt+'-component.json'),dict(local_path=str(binary),device_path=str(target),
              sha256=binding['binary_sha256'],exports=binding['exports'],native_calls=False))


def live_scene(identity):
    session=ReadOnlySession(identity);base=session.base
    manager=session.raw_pointer(base+0x1d46bd0);controller=session.raw_pointer(manager+0x28)
    domain=session.raw_pointer(controller+0x90) if controller else 0
    return dict(controller=controller,state=struct.unpack('<i',session.read(controller+0x30,4))[0] if controller else None,
                scene=session.raw_pointer(controller+0x50) if controller else 0,
                auxiliary=session.raw_pointer(manager+0x20),domain=domain,
                tick=struct.unpack('<i',session.read(domain+0x60,4))[0] if domain else None)


class Cancelled(Exception):pass


def generation_released(identity):
    """A missing/reused exact PID is release, not a debugger/read failure."""
    pid=identity['pid'];expected=identity['process_start_time']
    if type(pid) is not int or not 0<pid<1<<22 or not str(expected).isdigit():
        raise ValueError('invalid release identity')
    try:
        return start_time((Path('/proc')/str(pid)/'stat').read_text())!=expected
    except (FileNotFoundError,ProcessLookupError):
        # Do not interpret permission errors or malformed /proc data as exit.
        return True


def wait_generation_released(identity,timeout=10):
    deadline=time.monotonic()+timeout
    while True:
        if generation_released(identity):return True
        if time.monotonic()>=deadline:return False
        time.sleep(.1)


def diagnostic_bundle(request, files):
    """Only an explicitly queued, hash-bound local diagnostic can select a prefix."""
    if not request.get('diagnostic_prefix'):return None
    path=Path(request['diagnostic_prefix']).resolve()
    # Android's /data/data and /data/user/0 may be bind-mount aliases rather
    # than symlinks. Compare the actual directory inode, not only spelling.
    if not path.parent.samefile(files/'replay-queue') or not path.name.endswith('.diagnostic.json'):
        raise ValueError('diagnostic evidence is outside the private queue')
    raw=path.read_bytes()
    if not 0<len(raw)<=4*1024*1024 or hashlib.sha256(raw).hexdigest()!=request.get('diagnostic_sha256'):
        raise ValueError('diagnostic evidence changed')
    value=json.loads(raw)
    if value.get('user_authorized') is not True or value.get('source_sha256')!=request['source_sha256']:
        raise ValueError('diagnostic source or authorization differs')
    if value['preparation']['source_sha256']!=request['source_sha256']:
        raise ValueError('diagnostic preparation is not this HTML')
    return value


def checked_source_manifest(request_path,value):
    """Bind to this job's actual file, including Android bind-mount aliases."""
    supplied=Path(value)
    expected=request_path.parent/'source.json'
    if supplied.name!='source.json' or not supplied.is_file() or not expected.is_file() or not supplied.samefile(expected):
        raise ValueError('invalid source manifest: 文件不属于当前导入任务；未执行原生操作')
    # Use our private sibling, not an arbitrary caller-provided path spelling.
    return expected


def record_pre_native_release(directory,files,source_sha256):
    """Called while holding the operation lock, before any native publication."""
    active=read(files/'phone-active.json')
    active_path=Path(active['directory'])
    state=read(directory/'status.json')
    if (not active_path.is_dir() or not active_path.samefile(directory)
            or active.get('source_sha256')!=source_sha256 or state.get('source_sha256')!=source_sha256
            or state.get('native_entry_started') is not False
            or state.get('state') not in ('failed_before_native','cancelled')
            or (directory/'native-entry.json').exists()):
        raise ValueError('pre-native release ownership is unproven')
    write_new(directory/'preparation-release.json',dict(native_not_entered=True,
        source_sha256=source_sha256,status_sha256=hashlib.sha256((directory/'status.json').read_bytes()).hexdigest(),
        updated_at=time.time(),reason=state.get('message',''),operation_lock_held=True))


def stop_owned(identity,scene,component,*,reopen=True):
    """Only after the user explicitly clicks 'restart game to stop replay'."""
    session=ReadOnlySession(identity);base=session.base
    current=live_scene(identity);controller=current['controller']
    status=(session.proc/'status').read_text()
    if 'TracerPid:\t0' not in status.splitlines():raise RuntimeError('debugger still owns game; stop refused')
    rows=[line.split() for line in session.verify().splitlines() if line.split()[-1]==component['device_path']]
    if identity.get('native_transport')=='mumu-nativebridge-v1':
        from mumu_runtime import component_code_ranges
        code_ranges=component_code_ranges(session,component)
    else:
        code_ranges=[tuple(int(v,16) for v in row[0].split('-')) for row in rows if 'x' in row[1]]
    if not code_ranges:raise RuntimeError('owned replay component is absent')
    if controller!=scene['fields'][27]:
        # Native UI may already have returned to its ordinary idle lobby after
        # the completed replay. This is NOT an active/foreign battle. Require
        # the full strict lobby contract plus a valid terminal receipt; no
        # blanket exemption for a changed controller or a reused pointer.
        checked_receipt(scene,scene=True)
        if not scene.get('battle_terminal'):raise RuntimeError('not our active replay; stop refused')
        require_idle_lobby(scene_state(identity))
        if live_scene(identity)['controller']!=controller:raise RuntimeError('lobby changed during stop check')
    else:
        if not current['domain']:raise RuntimeError('replay domain absent; stop refused')
        original=struct.unpack('<128Q',session.read(base+0x1bebd08,1024))
        table=session.pointer(controller)
        cloned=struct.unpack('<128Q',session.read(table,1024))
        slots=(0x68//8,0x78//8)
        if not all(cloned[n]==original[n] for n in range(128) if n not in slots):raise RuntimeError('foreign controller table')
        if not all(any(low<=(cloned[n]&0x00ffffffffffffff)<high for low,high in code_ranges) for n in slots):raise RuntimeError('foreign replay callbacks')
        if struct.unpack('<i',session.read(controller+0x58,4))[0]!=1 or struct.unpack('<i',session.read(current['domain']+0x20,4))[0]!=4:
            raise RuntimeError('not the local replay domain')
    session.verify()
    package='com.tencent.tmgp.supercell.clashroyale'
    subprocess.run(['/system/bin/am','force-stop',package],check=True,timeout=15,capture_output=True,env=system_env())
    if reopen:
        subprocess.run(['/system/bin/am','start','-n',package+'/com.supercell.titan.tencent.GameAppTencent'],check=True,timeout=20,capture_output=True,env=system_env())
    for _ in range(50):
        if generation_released(identity):return
        time.sleep(.1)
    raise RuntimeError('old game generation still present after stop')


def recover_failed_attempt(directory,attempt,identity):
    """User-authorized failure recovery; exact detached owner, no blanket kill."""
    binding=read(directory/(attempt+'-binding.json'))
    result=read(directory/(attempt+'-result.json'))
    if binding['identity']!=identity or not result.get('detached'):
        raise RuntimeError('失败现场代际不一致或调试器未退出；未自动关闭游戏')
    if generation_released(identity):return 'already_released'
    if result.get('component_unloaded'):return 'already_clean'
    component=read(directory/(attempt+'-component.json'))
    session=ReadOnlySession(identity)
    maps=session.verify()
    rows=[row.split() for row in maps.splitlines() if len(row.split())>=6 and row.split()[-1]==component['device_path']]
    if not rows:
        from device_expression import rejected_before_load
        if rejected_before_load(result):
            if any(token in maps for token in ('libphone_replay_','libcr_web_','libcr_private_','libcr_direct_')):
                raise RuntimeError('another native component remains; release refused')
            require_idle_lobby(scene_state(identity))
            if 'TracerPid:\t0' not in (session.proc/'status').read_text().splitlines():
                raise RuntimeError('debugger still attached; release refused')
            session.verify()
            return 'already_clean'
    if identity.get('native_transport')=='mumu-nativebridge-v1':
        from mumu_runtime import component_code_ranges
        component_code_ranges(session,component)
    elif not rows or not any('x' in row[1] for row in rows):raise RuntimeError('无法确认失败组件归属')
    manager=session.raw_pointer(session.base+0x1d46bd0)
    if binding.get('scene') and manager:
        stop_owned(identity,result,component)
    else:
        # Bootstrap owns a private battle; the visible scene must still be the
        # ordinary idle lobby. Never kill a newly entered/foreign battle.
        if manager:require_idle_lobby(scene_state(identity))
        elif not binding.get('scene') or result.get('fields',[0]*48)[5]!=1:
            raise RuntimeError('没有已发布的本地场景归属证据')
        if 'TracerPid:\t0' not in (session.proc/'status').read_text().splitlines():
            raise RuntimeError('仍有调试器占用，未关闭客户端')
        session.verify()
        package='com.tencent.tmgp.supercell.clashroyale'
        subprocess.run(['/system/bin/am','force-stop',package],check=True,timeout=15,capture_output=True,env=system_env())
        if not wait_generation_released(identity):raise RuntimeError('未确认旧进程已释放')
        subprocess.run(['/system/bin/am','start','-n',package+'/com.supercell.titan.tencent.GameAppTencent'],check=True,timeout=20,capture_output=True,env=system_env())
    return 'restarted'


def finish_completed(binding_path,destination,prefix):
    """Explicit local Replay/Exit only: release a proven terminal scene.

    No new battle publication, no input from a webpage and no callback unload.
    If the user already killed that generation, do not touch its replacement.
    """
    directory=binding_path.parent
    if binding_path.name!='scene-v1-binding.json' or directory.name!='phone-playback' or destination.parent.parent!=directory:
        raise ValueError('not an owned terminal replay')
    if str(uuid.UUID(destination.parent.name))!=destination.parent.name:raise ValueError('not a fresh explicit cleanup action')
    files=next(p for p in directory.parents if p.name=='files')
    active=read(files/'phone-active.json')
    active_path=Path(active['directory'])
    if not active_path.is_dir() or not active_path.samefile(directory):raise ValueError('not the current replay')
    destination.mkdir(mode=0o700,exist_ok=False);owner=directory.stat()
    try:
        with (files/'phone-operation.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            terminal=read(directory/'scene-v1-terminal-result.json')
            checked_receipt(terminal,scene=True)
            if not terminal.get('battle_terminal') or terminal['scene_state']['tick']<=0 or terminal['scene_state']['tick']!=terminal['local_driver']['terminal_tick']:
                raise RuntimeError('no verified terminal result')
            identity=read(binding_path)['identity']
            if not generation_released(identity):
                # The first submission may still refer to a loading/lobby controller.
                # Bind cleanup to the verified TERMINAL observation, never to
                # that provisional publication receipt or a guessed controller.
                stop_owned(identity,terminal,read(directory/'scene-v1-component.json'),reopen=False)
            result=dict(game_pid=identity['pid'],game_start_time=identity['process_start_time'],
                        generation_released=True,monitor_active=False,source_sha256=active['source_sha256'])
            write_new(destination/'result.json',result)
    except BaseException:
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        raise
    finally:
        for path in sorted(destination.rglob('*'),reverse=True):
            if path.is_symlink():raise ValueError('unexpected cleanup link')
            os.chown(path,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)


def release_preparation(directory,destination,prefix):
    """Release only a proven pre-native failure; never touch a game process.

    Legacy migration is limited to the exact metadata validation failure observed
    before the first native probe. Missing PID alone is NOT release evidence.
    """
    files=next(p for p in directory.parents if p.name=='files')
    if (directory.name!='phone-playback' or directory.parent.name!='result'
            or not directory.parent.parent.parent.samefile(files/'local-imports')):
        raise ValueError('not a local replay task')
    if destination.parent.parent!=directory or destination.name!='preparation-release' or str(uuid.UUID(destination.parent.name))!=destination.parent.name:
        raise ValueError('not a fresh preparation release')
    with (files/'phone-operation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        active=read(files/'phone-active.json')
        active_path=Path(active['directory'])
        if not active_path.is_dir() or not active_path.samefile(directory):raise ValueError('active task changed')
        state=read(directory/'status.json')
        if state.get('state') not in ('needs_review','failed_before_native','cancelled'):raise ValueError('not a failed preparation')
        # Binding/build artifacts or the durable entry marker require the normal
        # native ownership/restart path, even if status writing was interrupted.
        if (directory/'native-entry.json').exists() or state.get('native_entry_started') is True:
            raise RuntimeError('native entry may have happened; release refused')
        modern=state.get('native_entry_started') is False
        if not modern and (any(directory.glob('*-binding.json')) or any(directory.glob('*-build'))):
            raise RuntimeError('legacy native entry is unknown; release refused')
        legacy=False
        if (directory/'error.txt').is_file():
            error=(directory/'error.txt').read_text()
            legacy=('metadata(source,preparation,Path(request[\'apk\']))' in error
                    and 'prepare_native_replay.py' in error
                    and error.rstrip().endswith('ValueError: 当前已验证天梯配置需要明确的16级塔楼；不会猜测国王塔等级'))
        if not modern and not legacy:raise RuntimeError('no proof of pre-native failure')
        # The operation lock above is held by the runner through all native work
        # and cleanup. We never infer release from a missing/stale PID alone.
        result=dict(native_not_entered=True,source_sha256=active['source_sha256'],
                    status_sha256=hashlib.sha256((directory/'status.json').read_bytes()).hexdigest(),
                    updated_at=time.time(),legacy_metadata_failure=legacy,
                    reason=(directory/'error.txt').read_text().strip().splitlines()[-1] if (directory/'error.txt').is_file() else state.get('message',''))
        destination.mkdir(mode=0o700,exist_ok=False)
        write_new(destination/'result.json',result)
        write_new(directory/'preparation-release.json',result)
        owner=directory.stat()
        for path in (destination/'result.json',destination,directory/'preparation-release.json'):
            os.chown(path,owner.st_uid,owner.st_gid)


def run(request_path,destination,prefix):
    destination.mkdir(mode=0o700,exist_ok=False)
    owner=request_path.parent.stat();os.chown(destination,owner.st_uid,owner.st_gid)
    files=next(p for p in destination.parents if p.name=='files')
    context=dict(monitor_active=True,runner_pid=os.getpid(),native_entry_started=False)
    started=time.monotonic();phase_started=started;phase_name=None;phase_totals={}
    def status(state,message,**details):
        nonlocal phase_started,phase_name
        now=time.monotonic()
        if state!=phase_name:
            if phase_name is not None:phase_totals[phase_name]=phase_totals.get(phase_name,0)+now-phase_started
            phase_name=state;phase_started=now
        value=dict(schema='royale-replay.phone-playback.v1',state=state,message=message,
                   processing_location='android',desktop_backend_used=False,network_settings_changed=False,
                   game_apk_changed=False,updated_at=time.time())
        value['elapsed_seconds']=now-started
        value['preparation_started_at']=time.time()-(now-started)
        value['phase_started_at']=time.time()-(now-phase_started)
        value['phase_seconds']=dict(phase_totals,**{state:phase_totals.get(state,0)+now-phase_started})
        value.update(context);value.update(details)
        if value.get('monitor_active') is False:
            publish_private_receipts(destination,owner)
            value['private_receipts_published']=True
        temp=destination/'status.tmp'
        with temp.open('w') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        os.chown(temp,owner.st_uid,owner.st_gid);temp.replace(destination/'status.json')
    lock=(files/'phone-operation.lock').open('a+')
    debugger=None
    completed=False
    last_attempt=None
    lock_acquired=False
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        lock_acquired=True
        request=read(request_path)
        diagnostic=diagnostic_bundle(request,files)
        context['source_sha256']=request['source_sha256']
        source=checked_source_manifest(request_path,request['source_manifest'])
        if request['source_sha256']!=read(source)['source_sha256']:raise ValueError('source request differs')
        speed=request['speed']
        if type(speed) not in (int,float) or speed not in (.25,.5,1,2,4):raise ValueError('invalid playback speed')
        temporary=destination/'tmp';temporary.mkdir(mode=0o700)
        os.environ['TMPDIR']=str(temporary);os.environ['HOME']=str(destination)
        status('preparing','手机本机：读取卡牌、塔楼和地图资源。')
        # A user-requested replay may have just reopened the game. Wait using
        # read-only observations; no native call is allowed in a loading scene.
        lobby_deadline=time.monotonic()+120
        while True:
            if (destination/'stop-request.json').exists():raise Cancelled('cancelled before preparation')
            try:
                initial=bind(Path(request['apk']))
                require_idle_lobby(scene_state(initial))
                break
            except MapsSnapshotError:raise
            except (FileNotFoundError,subprocess.CalledProcessError,ValueError):
                if time.monotonic()>=lobby_deadline:raise Cancelled('initial idle lobby not ready; no native task published')
                status('preparing','等待游戏启动并进入空闲大厅；尚未执行原生任务。')
                time.sleep(2)
        preparation=destination/'native-preparation'
        metadata(source,preparation,Path(request['apk']))
        observation=read(preparation/'runtime/runtime-observation.json')
        require_idle_lobby(observation['scene_state'])
        identity=observation['identity']
        context['game_pid']=identity['pid'];context['game_start_time']=identity['process_start_time']
        hint_initial=apply_offset(read(preparation/'preparation.json'),GLOBAL_DELAY_TICKS)
        from preparation_hint import load as load_hint,save as save_hint
        shifted,hint_detail=load_hint(files,hint_initial)
        source_seed=hint_initial['initialization_only']['rndSeed']
        context['preparation_hint_used']=hint_detail['used']
        write_new(destination/'preparation-hint.json',hint_detail)
        prep=preparation/'preparation-delayed.json';write_new(prep,shifted)
        debugger=Debugger(prefix)
        def cancellation():
            if (destination/'stop-request.json').exists():raise Cancelled('cancelled before next native task')
        def probe(name,*,execute=False,native=None,scene=False,candidate=False):
            nonlocal last_attempt
            # Prepare/bind immediately before every component; never migrate old
            # input owners if the client has restarted in the meantime.
            cancellation();ReadOnlySession(identity).verify()
            if context.get('seed_search_active'):
                if best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity):raise BestRequested()
                status('simulating','匹配随机种子 '+str(context.get('seed_trial_number',0))+'/'+str(SEED_ATTEMPTS)+'；'+('完整预演候选对局' if execute else '核验初始牌序')+'。可停止匹配并播放已完整执行的最优结果。')
            if not game_foreground():
                # Android can evict lobby resources when a full-screen browser
                # covers the client. Pure HTML workers may keep running; native
                # publication waits for the same client's stable foreground.
                status('waiting_preparation_lobby','后台 HTML 解析继续；原生准备已暂停，等待游戏回到前台大厅。')
                wait_idle_lobby(identity,progress=lambda _phase,message:status('waiting_preparation_lobby',message),cancellation=cancellation)
            if context.get('seed_search_active') and best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity):raise BestRequested()
            compile_started=time.monotonic()
            build=destination/(name+'-build')
            compile_component(prep,build,prefix,run_source=execute,native_replay=native,scene=scene,speed=speed)
            compiled_at=time.monotonic()
            if not game_foreground():
                status('waiting_preparation_lobby','组件已编译；等待游戏回到前台大厅，再执行本场原生校验。')
                wait_idle_lobby(identity,progress=lambda _phase,message:status('waiting_preparation_lobby',message),cancellation=cancellation)
            if context.get('seed_search_active') and best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity):raise BestRequested()
            publish_inputs(destination,build,preparation/'runtime',name)
            published_at=time.monotonic()
            if not context['native_entry_started']:
                write_new(destination/'native-entry.json',dict(native_entry_started=True,created_at=time.time()))
                context['native_entry_started']=True
            result=debugger.run(destination,name,scene=scene)
            write_new(destination/(name+'-timing.json'),dict(compile_and_bind_seconds=compiled_at-compile_started,
                publish_and_ownership_seconds=published_at-compiled_at,debugger_and_native_seconds=time.monotonic()-published_at))
            last_attempt=name
            if scene and not result.get('errors') and result.get('detached') and not result.get('native_replay_scene_present'):
                if result.get('fields',[0]*48)[5]!=1:raise RuntimeError('scene was not submitted')
                status('waiting_foreground','原生场景已提交，但后台尚未生成可播放画面；可点“返回游戏观看”完成加载。未自动跳转，也不重复提交。')
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    current=live_scene(identity)
                    if current['state']==9 and current['scene'] and not current['auxiliary'] and current['tick'] is not None and current['tick']>0:
                        result=debugger.run(destination,name,scene=True,action='observe',receipt=name+'-observe-v1')
                        break
                    time.sleep(1)
            if candidate:
                from mumu_ownership import released_resources
                if not (result.get('detached') and result.get('source_bootstrap_verified') and
                        (result.get('component_unloaded') or released_resources(result))):
                    checked_receipt(result,execute=True)
            else:checked_receipt(result,execute=execute,scene=scene)
            return result
        status('calibrating','手机本机：核验原生初始发牌和安全释放。')
        delayed=copy.deepcopy(hint_initial)
        seen=[]
        for calibration in range(12):
            seen.append(deck_fingerprint(shifted))
            deal=probe('bootstrap-v2' if calibration==0 else 'deal-check-'+str(calibration))
            aligned=calibrate(shifted,deal,seen)
            prep=preparation/('preparation-calibrated-'+str(calibration)+'.json');write_new(prep,aligned)
            if aligned['native_deal_ready']:break
            shifted=aligned
        else:raise RuntimeError('原生牌序有界校准未通过；没有执行源指令')
        status('simulating','手机原生引擎：完整执行全部下牌和技能。')
        from ability_search import search,terminal_hp_matches
        selected_candidate={}
        attempt_prefix=''
        def execute_candidate(candidate,number):
            nonlocal prep
            prep=preparation/(attempt_prefix+'ability-candidate-'+str(number)+'.json');write_new(prep,candidate)
            name=(attempt_prefix+'candidate-'+str(number)) if attempt_prefix else ('bootstrap-v3' if number==0 else 'ability-candidate-'+str(number))
            if not attempt_prefix:status('simulating','完整预演技能目标候选 '+str(number+1)+'；只接受整局指令成功且终局塔血匹配的歧义候选。')
            candidate_receipt=probe(name,execute=True,candidate=True)
            selected_candidate.update(receipt=candidate_receipt,preparation=prep)
            return read(destination/(name+'-source-execution.json')),dict(attempt=name,preparation=str(prep))
        if diagnostic is not None:
            from diagnostic_prefix import preview_inputs
            original=diagnostic['preparation']
            for key in ('events','initialization_only','native_initial_tower_hp'):
                if original.get(key)!=aligned.get(key):raise ValueError('当前初始化与原诊断分支不同：'+key+'；未发布预览')
            aligned,full=preview_inputs(original,diagnostic['report'],diagnostic['receipt'],authorized=True)
            prep=preparation/'diagnostic-preparation.json';write_new(prep,aligned)
            full['native_terminal_tick']=aligned['diagnostic_preview']['stop_tick']
            native=preparation/'diagnostic-native.json';write_new(native,full)
            context.update(diagnostic_only=True,diagnostic_prefix_verified=True,complete_replay_verified=False,
                           original_source_event_count=len(original['events']))
            status('validating','诊断预览：仅播放已成功执行的前缀，在原生分歧点暂停；不是完整回放。')
        else:
            try:
                aligned,execution,search_result=search(aligned,execute_candidate,
                    lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                    cancelled=lambda:(destination/'stop-request.json').exists())
            except Exception as error:
                if hasattr(error,'search_report'):write_new(destination/'ability-search.json',error.search_report)
                raise
            write_new(destination/'ability-search.json',search_result)
            # Always compare the simulated end with the page (the search only does so for ambiguous abilities).
            tier,difference=page_comparison(read(source),aligned,execution)
            initial_seed=aligned['initialization_only']['rndSeed'];original_seed=source_seed
            reasons=search_reasons(aligned,read(source))
            side_known=all(all(d['oracle_final_hp'][key]>0 for key in ('princess0','princess1')) for d in read(source)['decks'])
            context.update(seed_search_eligible=bool(reasons),seed_search_reasons=reasons,
                tower_comparison_basis='per-owner-native-spawn-order-and-survivors-v2',destroyed_princess_side_verified=side_known)
            seed_report=dict(search_policy='hunter-play-or-skeleton-king-ability-v1',eligible=bool(reasons),trigger_reasons=reasons,
                original_seed=original_seed,original_tier=tier if initial_seed==original_seed else None,
                original_difference=difference if initial_seed==original_seed else None,initial_seed=initial_seed,
                preparation_hint_used=hint_detail['used'],attempts=[],selected_seed=initial_seed)
            def rank(tier,difference):return (PAGE_MATCH_TIERS.index(tier),difference if difference is not None else 1<<30)
            best=(rank(tier,difference),initial_seed,tier,difference,(aligned,execution,search_result,dict(selected_candidate)))
            if tier!='exact' and reasons:
                context.update(seed_search_active=True,best_source_execution_verified=True,best_page_match=tier,best_page_hp_difference=difference)
                def progress(number,seed,current_best):
                    if (destination/'stop-request.json').exists():raise Cancelled('cancelled during seed search')
                    context.update(seed_trial_number=number+1,seed_attempts=number,best_page_match=current_best[2],best_page_hp_difference=current_best[3])
                    label={'exact':'战报塔血一致','same_towers':'各方毁塔数量一致','same_winner':'胜负一致','different':'终局仍不一致'}[current_best[2]]
                    status('simulating','尝试随机种子 '+str(number+1)+'/'+str(SEED_ATTEMPTS)+'，当前最优：'+label+'。可停止匹配并播放当前最优对局。')
                def evaluate_seed(seed,number):
                    nonlocal prep,attempt_prefix
                    try:
                        trial=copy.deepcopy(delayed);trial['initialization_only']['rndSeed']=seed
                        trial_seen=[]
                        for calibration in range(12):
                            trial_seen.append(deck_fingerprint(trial))
                            prep=preparation/('seed-'+str(number)+'-deal-'+str(calibration)+'.json');write_new(prep,trial)
                            deal=probe('seed-'+str(number)+'-deal-'+str(calibration))
                            trial=calibrate(trial,deal,trial_seen)
                            if trial['native_deal_ready']:break
                        else:raise RuntimeError('seed deal calibration did not converge')
                        attempt_prefix='seed-'+str(number)+'-'
                        trial,trial_execution,trial_search=search(trial,execute_candidate,
                            lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                            cancelled=lambda:(destination/'stop-request.json').exists())
                        trial_tier,trial_difference=page_comparison(read(source),trial,trial_execution)
                        return (rank(trial_tier,trial_difference),seed,trial_tier,trial_difference,
                            (trial,trial_execution,trial_search,dict(selected_candidate)))
                    finally:attempt_prefix=''
                best,attempts,stopped=choose_trials(best,retry_seed_plan(request['source_sha256'],original_seed,initial_seed),evaluate_seed,
                    lambda:best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity),progress,Cancelled)
                seed_report.update(attempts=attempts,stopped_by_user=stopped)
                context['seed_search_stopped_by_user']=stopped
            context['seed_search_active']=False
            if tier=='exact':seed_report['skipped_reason']='initial_result_exact'
            elif not reasons:seed_report['skipped_reason']='no_hunter_play_or_identified_skeleton_king_ability'
            _,selected_seed,tier,difference,(aligned,execution,search_result,chosen)=best
            selected_candidate.clear();selected_candidate.update(chosen)
            seed_report.update(selected_seed=selected_seed,selected_tier=tier,selected_difference=difference)
            hp_matched=tier=='exact'
            write_new(destination/'seed-search.json',seed_report)
            receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']
            context['ability_target_inferred']=search_result['inferred']
            # final_hp_matched: the whole simulated battle ends exactly at the page's tower HP.
            # random_seed_inferred: matched only with a substituted seed; not proof of the original process.
            context.update(final_hp_matched=hp_matched,page_match=tier,page_hp_difference=difference,random_seed=seed_report['selected_seed'],
                           random_seed_inferred=seed_report['selected_seed']!=original_seed,seed_attempts=len(seed_report['attempts']))
            full=finalize(aligned,execution,receipt)
            native=preparation/'complete-native.json';write_new(native,full)
            status('validating','手机本机：核对完整录像的原生 JSON 往返。')
            probe('bootstrap-v4',execute=True,native=native)
            roundtrip=read(destination/'bootstrap-v4-source-execution.json')
            if not roundtrip.get('loaded_from_json') or roundtrip['commands']!=full['native_replay']['cmd']:
                raise RuntimeError('native JSON round-trip changed source commands')
            try:context['preparation_hint_saved']=save_hint(files,hint_initial,aligned,exact=hp_matched,roundtrip_verified=True)
            except (OSError,ValueError,KeyError,TypeError):context['preparation_hint_saved']=False
        # The Android scene cannot initialise reliably behind another Activity.
        # Wait BEFORE publication. The visible app attaches its user-approved
        # progress overlay, opens the game, and writes a source-bound signal.
        # No scene/task is republished to recover a background initialisation.
        context.update(source_sha256=request['source_sha256'],retained_events=len(aligned['events']),
                       source_execution_verified=diagnostic is None,native_roundtrip_verified=diagnostic is None,
                       global_delay_ticks=GLOBAL_DELAY_TICKS,native_terminal_tick=full['native_terminal_tick'])
        # A row prepared ahead from the queue waits for the user's play tap longer;
        # the same source-bound signal, lobby check and cancellation still apply.
        foreground_deadline=time.monotonic()+(PREPARE_AHEAD_SECONDS if request.get('prepare_ahead') is True else 600)
        while True:
            cancellation();ReadOnlySession(identity).verify()
            if diagnostic is not None:ready_message='诊断前缀证据已核验；等待打开游戏，未通过整局校验。'
            elif context.get('page_match')=='same_towers':ready_message='胜负和各方毁塔数量与网页一致，逐塔血差合计 '+str(context.get('page_hp_difference'))+'；已试 '+str(context.get('seed_attempts',0))+' 个随机种子。不符合搜索条件的对局直接跳过搜索。'
            elif context.get('page_match')=='same_winner':ready_message='胜负与网页一致，但各方毁塔数量不同（已试 '+str(context.get('seed_attempts',0))+' 个随机种子）；仍可播放，过程与原局不同。'
            elif not context.get('final_hp_matched'):ready_message='全部指令已执行，但终局与网页不符（已另试 '+str(context.get('seed_attempts',0))+' 个随机种子）；仍可播放，过程可能与原局不同。'
            elif context.get('random_seed_inferred'):ready_message='换用随机种子后战报塔血一致；原种子未知，毁塔侧未核定，过程为推断。等待打开游戏。'
            else:ready_message='全部指令及 JSON 核验通过，双方国王塔和剩余公主塔血量与战报一致；毁塔侧未核定。等待悬浮进度卡就绪并打开游戏。'
            status('ready_to_open',ready_message)
            signal=destination/'foreground-request.json'
            if signal.is_file():
                token=read(signal)
                if token.get('source_sha256')!=request['source_sha256'] or token.get('user_requested_game_foreground') is not True or token.get('overlay_attached') is not True:
                    raise RuntimeError('foreground signal differs from this source/approved overlay')
                if game_foreground():break
            if time.monotonic()>foreground_deadline:raise Cancelled('foreground was not requested; scene not published')
            time.sleep(1)
        wait_idle_lobby(identity,progress=status,cancellation=cancellation)
        status('loading','手机本机：大厅已稳定，提交已验证的原生战斗画面。')
        scene=probe('scene-v1',execute=True,native=native,scene=True)
        context.update(standalone_playback_ready=True,source_sha256=request['source_sha256'],
                       retained_events=len(aligned['events']),native_roundtrip_verified=diagnostic is None,
                       global_delay_ticks=GLOBAL_DELAY_TICKS,scene_frames=scene['local_driver']['frames'],
                       native_terminal_tick=full['native_terminal_tick'],scene_initial_tick=live_scene(identity)['tick'],playback_started=False)
        status('starting','原生画面已生成；继续观察实际 tick，确认开始后自动收起进度卡。',tick=context['scene_initial_tick'])
        # No host polling is needed for playback; callbacks and native renderer
        # run in the game. Read-only phone monitoring can survive UI background.
        deadline=time.monotonic()+1800
        while time.monotonic()<deadline:
            if generation_released(identity):
                status('released','游戏进程已结束，控制台已就绪；原回放记录保留。',monitor_active=False,generation_released=True);return
            if (destination/'stop-request.json').exists():
                comp=read(destination/'scene-v1-component.json')
                stop_owned(identity,scene,comp)
                status('stopped','已安全停止本机回放，仅重新打开游戏客户端。',monitor_active=False);return
            current=live_scene(identity)
            if current['controller']!=scene['fields'][27]:
                status('scene_left','已离开本工具的回放；保留场景记录，不操作其他界面。',monitor_active=False);return
            context['playback_started']=context['playback_started'] or current['tick']>context['scene_initial_tick']
            if current['tick']>=full['native_terminal_tick']:
                if diagnostic is not None:
                    status('diagnostic_ready','最长分支诊断预览已在分歧点暂停。只包含已执行成功的前缀，未通过整局校验；可人工检查或安全停止。',tick=current['tick'])
                    time.sleep(2)
                    continue
                terminal=debugger.run(destination,'scene-v1',scene=True,action='observe',receipt='scene-v1-terminal')
                checked_receipt(terminal,scene=True)
                if not terminal.get('battle_terminal'):raise RuntimeError('expected terminal tick but engine not finished')
                completed=True
                context.update(native_terminal_tick=terminal['scene_state']['tick'],
                               active_towers=terminal.get('active_towers',[]),terminal_receipt='scene-v1-terminal-result.json')
                # Direct manager request(3) was observed to crash in HomeScene
                # initialization (null Home state). Do not call that route.
                # Until its lifetime is repaired, use the previously authorized
                # exact-owned client restart AND reopen, never leave it closed.
                status('returning_lobby','终局已核验；正在释放本地现场并自动重新打开游戏。当前采用客户端重启兜底，不是免重启返回。')
                stop_owned(identity,terminal,read(destination/'scene-v1-component.json'),reopen=True)
                context['client_reopened']=True
                write_new(destination/'automatic-return.json',dict(source_sha256=request['source_sha256'],
                    old_game_pid=identity['pid'],old_game_start_time=identity['process_start_time'],
                    old_generation_released=generation_released(identity),client_reopened=True,seamless=False))
                # Normal launch may require a login prompt. Never label that as
                # a verified lobby or select credentials on the user's behalf.
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    try:
                        fresh=bind(Path(request['apk']));require_idle_lobby(scene_state(fresh))
                        context['lobby_returned']=True;break
                    except (ValueError,FileNotFoundError,subprocess.CalledProcessError):time.sleep(1)
                message='回放已完成，游戏已自动重新打开'+('并确认回到大厅。' if context.get('lobby_returned') else '；等待客户端加载或登录。')+'当前使用客户端重启兜底，未修改网络。'
                status('complete',message,tick=terminal['scene_state']['tick'],monitor_active=False)
                return
            if context['playback_started']:
                status('playing','已确认原生回放实际步进；可使用游戏内暂停和倍速。',tick=current['tick'])
            else:
                status('waiting_foreground','后台尚未观察到实际步进；可点“返回游戏观看”激活原生画面。不会把提交或加载当成开始。',tick=current['tick'])
            time.sleep(2)
        status('monitor_expired','本机观察等待已结束；未重复提交或终止原生场景。',monitor_active=False)
    except Cancelled:
        status('cancelled','已在安全边界取消本机准备；没有重复发布原生任务。',monitor_active=False)
    except BaseException:
        released=False
        try:
            if 'identity' in locals():released=generation_released(identity)
        except Exception:pass  # An unreadable /proc is unknown, never exit.
        if released and not completed:
            status('released','游戏进程已结束，控制台已就绪；原回放记录保留。',monitor_active=False,generation_released=True)
            return
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        if completed:
            status('complete','原生终局已验证；后续观察已结束，异常记录保留，不自动重试。',monitor_active=False,observation_error=True)
        else:
            if not context['native_entry_started']:
                status('failed_before_native','准备失败，尚未进入原生执行：'+str(sys.exception())+'。可选择其他 HTML；不会自动重试。',monitor_active=False)
                if lock_acquired and context.get('source_sha256'):
                    record_pre_native_release(destination,files,context['source_sha256'])
            else:
                from failure_recovery import explanation
                cause=explanation(sys.exception())
                try:
                    if last_attempt is None:raise RuntimeError('没有可核验的失败任务回执')
                    recovered=recover_failed_attempt(destination,last_attempt,identity)
                    write_new(destination/'failure-recovery.json',dict(game_pid=identity['pid'],
                        game_start_time=identity['process_start_time'],source_sha256=request['source_sha256'],result=recovered,reason=cause))
                    status('failed_recovered',cause+' 本次占用已释放；'+('已重新打开游戏，请等待大厅加载。' if recovered=='restarted' else '无需重启游戏。')+'可重新选择回放；没有自动重试。',
                           monitor_active=False,recovery_result=recovered,last_error=str(sys.exception()))
                except Exception as recovery_error:
                    status('needs_review',cause+' 自动恢复未通过归属检查：'+str(recovery_error)+'；现场记录保留。',monitor_active=False)
        raise
    finally:
        if debugger:debugger.close()
        lock.close()
        diagnostic=maps_diagnostics()
        if diagnostic and not (destination/'maps-diagnostic.json').exists():
            write_new(destination/'maps-diagnostic.json',diagnostic)
        publish_private_receipts(destination,owner)
