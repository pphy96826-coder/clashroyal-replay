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
import signal
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid

from device_session import ReadOnlySession, start_time, bind
from device_metadata import run as metadata
from device_runtime import scene_state
from device_build import run as compile_component
from scene_start_contract import require_idle_lobby
from timing_policy import apply_offset, GLOBAL_DELAY_TICKS
from align_native_deal import align,calibrate,deck_fingerprint
from finalize_replay import finalize
from proc_maps import MapsSnapshotError,diagnostics as maps_diagnostics


PREPARE_AHEAD_SECONDS=7200
# Alternate-seed search is an explicit, conservative project policy, not proof
# of which cards consume a shared battle RNG. Only decks containing Skeleton
# King or Hunter are eligible. All other decks keep the original seed even
# when HP differs; mismatch alone is not evidence of randomness.
SEED_ATTEMPTS=60
# Screening runs each seed ONCE with the chosen abilities. Measured on MuMu: a seed
# whose fixed combination dies (battle settles early / hero absent) is far from the
# page anyway, and re-walking its ability prefix from the root never completed
# within a few runs (16 abilities). Depth is spent only on the refined seeds.
SCREEN_RUNS=1
SCREEN_RUNS_UNFIXED=12  # no completed combination at the original seed to start from
REFINE_SEEDS=3   # closest screened seeds that get a deeper ability search
REFINE_RUNS=24
PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different','unknown')
# Phone VMs: the local debugger sometimes loses the game while interrupting it
# (reported as exited / interrupted by SIGSTOP / task never observed done).
# That says nothing about the replay. Such an attempt is released with the
# game process and the SAME preparation step reruns in a fresh client.
DEBUGGER_LOSS_MARKERS=('original task remains pending','native process state','Expression execution was interrupted',
                       'execution stopped with unexpected state','stop for observation failed','resume failed',
                       'resume after game signal failed')
# Restarts continue only while the search progresses: at least one native step
# completed since the previous restart. The total is still bounded.
DEBUGGER_LOSS_RESTARTS=64
PREFLIGHT_RETRIES=8   # code-30 rejections (game not an idle lobby) retried after waiting for it


def debugger_lost(receipt):
    errors=receipt.get('errors') or []
    return bool(errors) and all(any(marker in str(error) for marker in DEBUGGER_LOSS_MARKERS) for error in errors)


def candidate_scope(identity):
    """Read-only generation label; never migrate a resource/worker handle.

    Identical process metadata alone is insufficient: the public resource owners
    or worker can have been replaced inside the same process. Bind their exact
    fresh identities, including the worker thread's start time, and double read.
    """
    session=ReadOnlySession(identity);base=session.base
    def owners():
        root=session.raw_pointer(base+0x1d34ae0)
        if not root:raise ValueError('candidate resource owner absent')
        services=session.raw_pointer(root+0x20)
        worker=session.raw_pointer(base+0x1d88820)
        if not services or not worker:raise ValueError('candidate resources or worker absent')
        catalog=session.raw_pointer(services+0x38)
        if not catalog:raise ValueError('candidate catalog absent')
        tid=struct.unpack('<i',session.read(worker+0x10,4))[0]
        if not 0<tid<1<<22:raise ValueError('candidate worker absent')
        thread_start=start_time((Path('/proc')/str(identity['pid'])/'task'/str(tid)/'stat').read_text())
        return root,services,catalog,worker,tid,thread_start
    first=owners()
    if owners()!=first:raise ValueError('candidate resource generation changed during observation')
    session.verify()
    return dict(identity=copy.deepcopy(identity),resource_generation=hashlib.sha256(repr(first).encode()).hexdigest())


def seed_search_policy(source, tier):
    """Gate alternate seeds by BOTH source decks, independently of ability search."""
    import re
    eligible=set()
    for deck in source.get('decks',[]):
        for card in deck.get('cards',[]):
            key=card.get('base_card_key') or card.get('source_card_key') or ''
            key=re.sub(r'-(?:ev\d+|hero)$','',key)
            if key in ('skeleton-king','hunter'):eligible.add(key)
    allowed=bool(eligible)
    return dict(eligible_cards=sorted(eligible),allowed=allowed,
                search_needed=allowed and tier not in ('exact','unknown'),
                skip_reason='exact_match' if tier=='exact' else 'final_towers_unknown' if tier=='unknown' else None if allowed else 'no_seed_sensitive_card')


def time_note(context):
    seconds=context.get('page_time_difference_seconds')
    return '' if seconds is None else '，终局时间相差 '+('%.1f'%abs(seconds))+' 秒'


def elixir_note(context):
    return '，双方溢出圣水与网页一致' if context.get('page_elixir_matched') is True else ''


def cost_text(cost):
    """Progress label of a page cost; a leaked-elixir mismatch is named, not a huge number."""
    from ability_search import ELIXIR_MISMATCH_COST
    if type(cost) is not int:return ''
    if cost>=ELIXIR_MISMATCH_COST:return '（溢出圣水不一致，综合差距 '+str(cost-ELIXIR_MISMATCH_COST)+'）'
    return '（综合差距 '+str(cost)+'，含终局时间和溢出圣水）' if cost else ''


def elixir_gate(source, preparation, report):
    """Final check before publication: both players' leaked elixir must equal the
    page. Returns None when it passes (or the page has no value), else the reason."""
    from ability_search import elixir_rows
    rows=elixir_rows(source,report)
    if all(r['matched'] in (True,None) for r in rows):return None
    parts=[]
    for r in rows:
        if r['matched'] is False:
            if r.get('shortfall'):
                parts.append(('蓝方' if r['owner']==0 else '红方')+' 有出牌或技能在圣水不足时执行（实付不是整数圣水），实战中不可能');continue
            part=('蓝方' if r['owner']==0 else '红方')+' 网页 '+('%.2f'%r['page'])+'，模拟 '+('%.2f'%r['simulated'])
            if r.get('measured_at')=='battle_end':part+='（模拟在网页结算时间前已结束）'
            if r.get('implied_ability_and_final') is not None and r.get('measured_at')=='page_end':
                part+='（按网页反推：技能费用 + 终局剩余圣水应为 '+('%.2f'%r['implied_ability_and_final'])+'，本次技能实付 '+str(r.get('ability_spent'))+'）'
            parts.append(part)
    return '截至网页结算时间，溢出圣水与网页不一致：'+'；'.join(parts)


def seed_search_note(attempts, allowed):
    if attempts:return '已另试 '+str(attempts)+' 个种子'
    if not allowed:return '卡组无骷髅之王或猎人，保留原种子，未搜索其他种子'
    return '保留原种子，未搜索其他种子'


def page_towers(source, preparation, report):
    from ability_search import final_tower_rows
    return final_tower_rows(source,preparation,report)


def page_comparison(source, preparation, report):
    """Rank a fully executed run against the page: (tier, cost).

    cost = summed six-tower HP difference + TIME_WEIGHT_PER_TICK x end-time ticks
    beyond the tolerance, so the match end time weighs more than tower HP, plus
    ELIXIR_MISMATCH_COST + ELIXIR_WEIGHT x elixir when either player's leaked
    elixir differs from the page. Towers that all match with a different end
    time or leaked elixir is not 'exact' but 'same_towers'."""
    from ability_search import terminal_time,TIME_WEIGHT_PER_TICK,elixir_check,elixir_cost
    tier,difference=page_tower_comparison(source,preparation,report)
    if tier=='unknown':return tier,difference
    excess=terminal_time(source,report)['excess_ticks'] or 0
    elixir_matched,_=elixir_check(source,report)
    if tier=='exact' and (excess>0 or elixir_matched is False):tier='same_towers'
    return tier,difference+TIME_WEIGHT_PER_TICK*excess+elixir_cost(source,report)


def page_breakdown(source, preparation, report):
    """Display values: tower HP difference and end-time difference in seconds."""
    from ability_search import terminal_time,elixir_check,elixir_rows
    _,hp=page_tower_comparison(source,preparation,report)
    time=terminal_time(source,report)
    elixir_matched,elixir_difference=elixir_check(source,report)
    return dict(hp_difference=hp,time_difference_seconds=None if time['delta_ticks'] is None else round(time['delta_ticks']/20,2),
                elixir_matched=elixir_matched,elixir_leaked_difference=elixir_difference,elixir=elixir_rows(source,report),
                page_seconds=None if time['page_ticks'] is None else time['page_ticks']/20,
                simulated_seconds=None if time['simulated_tick'] is None else round(time['simulated_tick']/20,2))


def page_tower_comparison(source, preparation, report):
    """Compare a fully executed run with the page's six final towers.

    Uses the same per-tower rule as the ability check (final_tower_rows).
    Returns (tier, hp_difference): exact; same destroyed towers (so same crowns
    and winner); same winner only; different; or unknown when any tower lacks
    page data or simulated evidence. Unknown is never reported as a mismatch.
    """
    from ability_search import final_tower_rows
    rows=final_tower_rows(source,preparation,report)
    if not rows or any(r['page'] is None or r['simulated'] is None for r in rows):return 'unknown',None
    difference=sum(abs(r['simulated']-r['page']) for r in rows)
    if all(r['simulated']==r['page'] for r in rows):return 'exact',0
    if all((r['simulated']==0)==(r['page']==0) for r in rows):return 'same_towers',difference
    def winner(field):
        crowns={0:0,1:0}
        for r in rows:
            if r[field]==0:crowns[1-r['owner']]+=3 if r['tower']=='king' else 1
        a,b=min(crowns[0],3),min(crowns[1],3);return 0 if a>b else 1 if b>a else None
    if winner('simulated')==winner('page'):return 'same_winner',difference
    return 'different',difference


def replay_key(source):
    """Identity of the MATCH, not of the saved HTML bytes: re-saving the same
    replay page changes the file hash but not the tag, decks or any play."""
    decks=sorted((d['source_side'],d['proposed_native_owner'],d.get('tower'),
                  [(c.get('base_card_key'),c.get('form'),c.get('source_level')) for c in d['cards']]) for d in source['decks'])
    actions=[(a['kind'],a['source_tick_20hz'],a['source_side'],a.get('base_card_key'),a.get('source_position')) for a in source['actions']]
    return hashlib.sha256(json.dumps([source['replay_tag'],decks,actions],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def seed_plan(match_key, original, count=SEED_ATTEMPTS, remembered=None):
    """Deterministic int32 seeds derived from the match identity (see replay_key).
    A seed remembered from an earlier run of the same match is tried first."""
    seeds=[remembered] if type(remembered) is int and remembered!=original else []
    target=count+len(seeds)
    for n in range(count*4):
        value=int.from_bytes(hashlib.sha256((match_key+':seed:'+str(n)).encode()).digest()[:4],'big')
        value=value-2**32 if value>=2**31 else value
        if value!=original and value not in seeds:seeds.append(value)
        if len(seeds)>=target:break
    return seeds


def read(path):return json.loads(path.read_text())


def write_new(path, value):
    with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


# Linux SIGSTOP, SIGTSTP, SIGTTIN, SIGTTOU (bit n-1 of /proc pending masks).
STOP_SIGNAL_MASK=sum(1<<(n-1) for n in (19,20,21,22))


def release_stray_stop(pid):
    """Our debugger interrupts the game with SIGSTOP. When that races a task
    finishing, one SIGSTOP can stay queued past detach and later freeze the
    game (state T, no tracer) or interrupt the next native call. Only when NO
    tracer is attached, SIGCONT clears every queued stop signal and resumes a
    stopped game; it does nothing to a running one. Returns what was found."""
    found=[]
    try:tasks=sorted((Path('/proc')/str(pid)/'task').iterdir())
    except OSError:return None  # gone: nothing to resume
    for task in tasks:
        try:
            stat=(task/'stat').read_text();status=(task/'status').read_text()
        except OSError:continue
        fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
        if fields.get('TracerPid','0').strip()!='0':return None  # a debugger owns it: never touch
        state=stat[stat.rindex(')')+2]
        pending=(int(fields.get('SigPnd','0').strip(),16)|int(fields.get('ShdPnd','0').strip(),16))&STOP_SIGNAL_MASK
        if state=='T' or pending:found.append(dict(tid=int(task.name),state=state,pending_stop=hex(pending)))
    if found:os.kill(pid,signal.SIGCONT)
    return found


def game_foreground():
    """A boolean only; never retain other applications' activity contents."""
    result=subprocess.run(['/system/bin/dumpsys','activity','activities'],capture_output=True,timeout=5)
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
        state=scene_state(identity)
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
    elif not receipt.get('source_bootstrap_verified') or not receipt.get('component_unloaded'):
        raise RuntimeError('initialization or cleanup did not complete')
    if execute and not scene and not receipt.get('private_source_execution_complete'):
        raise RuntimeError('incomplete source execution; no scene publication')


class EventDebugger:
    """Embedded LLDB has no CLI event thread to advance its PUBLIC state.

    Removing listener events commits running/stopped transitions. Never ignore
    a signal or auto-resume a crash; only deliver already emitted events (the
    gates alone hand a game-runtime signal back, see signal_policy).
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
        sys.path.insert(0,str(prefix/'lib/python3.14/site-packages'))
        if '_lldb' not in sys.modules:
            spec=importlib.util.spec_from_file_location('_lldb',str(prefix/'lib/liblldb.so'))
            native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
            sys.modules['_lldb']=native;sys.modules['lldb._lldb']=native
        import lldb
        self.lldb=lldb
        os.environ['LLDB_DEBUGSERVER_PATH']=str(prefix/'bin/lldb-server')
        lldb.SBDebugger.Initialize()
        self.debugger=EventDebugger(lldb.SBDebugger.Create(),lldb);self.debugger.SetAsync(False)

    def close(self):
        self.debugger.SetAsync(False)
        self.lldb.SBDebugger.Destroy(self.debugger.core)
        self.lldb.SBDebugger.Terminate()

    def run(self,directory,attempt,*,scene=False,action='start',receipt=None,observe_original=False):
        lldb=self.lldb;binding=read(directory/(attempt+'-binding.json'))
        identity=binding['identity'];session=ReadOnlySession(identity)
        session.verify()
        status=(session.proc/'status').read_text()
        if 'TracerPid:\t0' not in status.splitlines():raise RuntimeError('another debugger owns game')
        stray=release_stray_stop(identity['pid'])
        if stray:write_new(directory/((receipt or attempt)+'-stray-stop-before.json'),stray)
        # Fresh verification before attaching the exact pinned generation.
        for pin in binding['pins']:
            if hashlib.sha256(session.read(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:
                raise RuntimeError('code changed before attach')
        target=self.debugger.CreateTarget('/system/bin/app_process64')
        if not target.IsValid():raise RuntimeError('Android target creation failed')
        self.debugger.SetSelectedTarget(target)
        process=None
        try:
            error=lldb.SBError()
            process=target.AttachToProcessWithID(self.debugger.GetListener(),identity['pid'],error)
            if not error.Success() or not process.IsValid():raise RuntimeError('local game attach failed: '+str(error))
            session.verify()
            register_allocator(lldb,target,directory,attempt,receipt or attempt,session)
            if scene:
                import run_scene_gate as gate
                gate.ROOT=directory
                name=receipt or attempt
                gate.run(self.debugger,attempt,action,name)
            else:
                import phone_bootstrap_gate as gate
                name=receipt or attempt
                gate.run(self.debugger,directory,attempt,observe_original=observe_original,receipt=receipt)
            return read(directory/(name+'-result.json'))
        finally:
            self.debugger.SetAsync(False)
            if process and process.IsValid() and process.GetState() not in (lldb.eStateExited,lldb.eStateDetached):
                if process.GetState()==lldb.eStateRunning:process.Stop()
                if not process.Detach().Success():raise RuntimeError('detach failed; preserve native owner')
            self.debugger.DeleteTarget(target)
            # A tracer that has gone (detached, or lldb-server lost the process)
            # must not leave a queued SIGSTOP behind to freeze the game.
            for _ in range(20):
                stray=release_stray_stop(identity['pid'])
                if stray is not None:break
                time.sleep(.1)
            if stray:
                with contextlib.suppress(FileExistsError):write_new(directory/((receipt or attempt)+'-stray-stop-after.json'),stray)


def lldb_mmap_addresses(lldb,target):
    found=target.FindFunctions('mmap',lldb.eFunctionNameTypeFull);addresses=set()
    for index in range(min(found.GetSize(),8)):
        context=found.GetContextAtIndex(index)
        start=context.GetFunction().GetStartAddress() if context.GetFunction().IsValid() else context.GetSymbol().GetStartAddress()
        loaded=start.GetLoadAddress(target)
        if loaded!=lldb.LLDB_INVALID_ADDRESS:addresses.add(loaded)
    return addresses


def register_allocator(lldb,target,directory,attempt,name,session):
    """Give LLDB the verified libc module when its own module scan missed it.

    Debugger metadata only: nothing runs and no game memory is written. The
    file is re-hashed, the live mmap/munmap bytes re-checked, and LLDB's own
    symbol address must equal the verified one, else the module is removed.
    """
    evidence=dict(needed=False,registered=False,native_calls=False,game_memory_written=False)
    path=directory/(name+'-allocator-binding.json')
    try:
        if lldb_mmap_addresses(lldb,target):return evidence
        evidence['needed']=True
        loader=read(directory/(attempt+'-loader-binding.json'));allocator=loader.get('allocator')
        if not allocator:raise RuntimeError('LLDB cannot locate mmap and libc allocator was not verified')
        evidence.update(library=allocator['library'],base=allocator['base'])
        if hashlib.sha256(Path(allocator['library']).read_bytes()).hexdigest()!=allocator['library_sha256']:
            raise RuntimeError('libc file changed after verification')
        for pin in allocator['exports'].values():
            if hashlib.sha256(session.read(int(pin['address'],0),pin['size'])).hexdigest()!=pin['sha256']:
                raise RuntimeError('live libc allocator bytes changed')
        module=target.AddModule(allocator['library'],None,None)
        if not module.IsValid():raise RuntimeError('LLDB could not add the verified libc')
        if not target.SetModuleLoadAddress(module,int(allocator['base'],0)).Success():
            target.RemoveModule(module);raise RuntimeError('LLDB could not place libc at the verified base')
        expected=int(allocator['exports']['mmap']['address'],0);seen=lldb_mmap_addresses(lldb,target)
        evidence['lldb_mmap']=sorted(hex(value) for value in seen)
        if seen!={expected}:
            target.RemoveModule(module);raise RuntimeError('LLDB mmap differs from the verified address')
        evidence['registered']=True
        return evidence
    except Exception as exc:
        evidence['error']=str(exc)[:400];raise
    finally:
        if evidence['needed']:
            try:path.write_text(json.dumps(evidence,indent=2))
            except OSError:pass


def publish_inputs(directory,build,observation,attempt):
    """Only own fresh staging directory, readable by this pinned game's group."""
    binding=read(build/'binding.json');session=ReadOnlySession(binding['identity'])
    maps=session.verify()
    if any(token in maps for token in ('libphone_replay_','libcr_web_','libcr_private_','libcr_direct_')):
        raise RuntimeError('previous native component still owns game; never overwrite')
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
    except FileNotFoundError:
        # Do not interpret permission errors or malformed /proc data as exit.
        return True


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
    rows=[line.split() for line in session.verify().splitlines() if line.split()[-1]==component]
    if not rows or not any('x' in row[1] for row in rows):raise RuntimeError('owned replay component is absent')
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
        if not all(any(int(row[0].split('-')[0],16)<=(cloned[n]&0x00ffffffffffffff)<int(row[0].split('-')[1],16)
                       and 'x' in row[1] for row in rows) for n in slots):raise RuntimeError('foreign replay callbacks')
        if struct.unpack('<i',session.read(controller+0x58,4))[0]!=1 or struct.unpack('<i',session.read(current['domain']+0x20,4))[0]!=4:
            raise RuntimeError('not the local replay domain')
    session.verify()
    package='com.tencent.tmgp.supercell.clashroyale'
    subprocess.run(['/system/bin/sh','/system/bin/am','force-stop',package],check=True,timeout=15,capture_output=True)
    if reopen:
        subprocess.run(['/system/bin/sh','/system/bin/am','start','-n',package+'/com.supercell.titan.tencent.GameAppTencent'],check=True,timeout=20,capture_output=True)
    for _ in range(50):
        if generation_released(identity):return
        time.sleep(.1)
    raise RuntimeError('old game generation still present after stop')


def recover_failed_attempt(directory,attempt,identity):
    """User-authorized failure recovery; exact detached owner, no blanket kill."""
    binding=read(directory/(attempt+'-binding.json'))
    result=read(directory/(attempt+'-result.json'))
    # lldb may lose a SIGSTOP-interrupted game (reported as exited) without a
    # Detach receipt; the kernel has then released it. Only an attached tracer blocks recovery.
    detached=result.get('detached');tracer_gone=False
    if binding['identity']==identity and not detached and not generation_released(identity):
        tracer_gone='TracerPid:\t0' in (Path('/proc')/str(identity['pid'])/'status').read_text().splitlines()
    if binding['identity']!=identity or not (detached or tracer_gone):
        raise RuntimeError('失败现场代际不一致或调试器未退出；未自动关闭游戏')
    if tracer_gone:release_stray_stop(identity['pid'])
    if generation_released(identity):return 'already_released'
    if result.get('component_unloaded'):return 'already_clean'
    component=read(directory/(attempt+'-component.json'))['device_path']
    session=ReadOnlySession(identity)
    maps=session.verify()
    rows=[row.split() for row in maps.splitlines() if len(row.split())>=6 and row.split()[-1]==component]
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
    if not rows or not any('x' in row[1] for row in rows):raise RuntimeError('无法确认失败组件归属')
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
        subprocess.run(['/system/bin/sh','/system/bin/am','force-stop',package],check=True,timeout=15,capture_output=True)
        # The kernel needs a moment to reap the process (seen on phone VMs).
        for _ in range(50):
            if generation_released(identity):break
            time.sleep(.1)
        else:raise RuntimeError('未确认旧进程已释放')
        subprocess.run(['/system/bin/sh','/system/bin/am','start','-n',package+'/com.supercell.titan.tencent.GameAppTencent'],check=True,timeout=20,capture_output=True)
    return 'restarted'


def finish_completed(binding_path,destination,prefix):
    """Explicit local Replay/Exit only: release a proven terminal scene.

    No new battle publication, no input from a webpage and no callback unload.
    If the user already killed that generation, do not touch its replacement.
    """
    directory=binding_path.parent
    if binding_path.name!='scene-v1-binding.json' or directory.name!='phone-playback' or not same_path(destination.parent.parent,directory):
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
                stop_owned(identity,terminal,read(directory/'scene-v1-component.json')['device_path'],reopen=False)
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


def same_path(left,right):
    """Same existing directory under either app-data spelling.

    The launcher passes the task canonicalized (/data/data/...) but the new
    action path as given (/data/user/0/...); on VMs where one is a symlink the
    strings differ although both name the same private directory.
    """
    try:return left.samefile(right)
    except OSError:return False


def release_preparation(directory,destination,prefix):
    """Release only a proven pre-native failure; never touch a game process.

    Legacy migration is limited to the exact metadata validation failure observed
    before the first native probe. Missing PID alone is NOT release evidence.
    """
    # The native launcher exits without finalizing Python, so a buffered
    # traceback would be lost; flush the refusal reason for the console.
    try:
        files=next(p for p in directory.parents if p.name=='files')
        if (directory.name!='phone-playback' or directory.parent.name!='result'
                or not directory.parent.parent.parent.samefile(files/'local-imports')):
            raise ValueError('not a local replay task')
        if not same_path(destination.parent.parent,directory) or destination.name!='preparation-release' or str(uuid.UUID(destination.parent.name))!=destination.parent.name:
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
    except BaseException as exc:
        reason='release refused: '+type(exc).__name__+': '+str(exc)[:300]+'\n'
        # Some VM su builds give the launcher no usable stdout/stderr; keep the
        # reason as an exported file in the task directory as well.
        try:
            note=directory/'preparation-release-error.txt'
            note.write_text(time.strftime('%Y-%m-%d %H:%M:%S ')+reason+traceback.format_exc()[-3000:])
            owner=directory.stat();os.chown(note,owner.st_uid,owner.st_gid)
        except Exception:pass
        for stream in (sys.stdout,sys.stderr):
            try:stream.write(reason);stream.flush()
            except Exception:pass
        raise


def run(request_path,destination,prefix):
    destination.mkdir(mode=0o700,exist_ok=False)
    owner=request_path.parent.stat();os.chown(destination,owner.st_uid,owner.st_gid)
    files=next(p for p in destination.parents if p.name=='files')
    context=dict(monitor_active=True,runner_pid=os.getpid(),native_entry_started=False)
    def status(state,message,**details):
        value=dict(schema='royale-replay.phone-playback.v1',state=state,message=message,
                   processing_location='android',desktop_backend_used=False,network_settings_changed=False,
                   game_apk_changed=False,updated_at=time.time())
        value.update(context);value.update(details)
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
        # Phone VMs can take several minutes to cold-start the game to its lobby.
        lobby_deadline=time.monotonic()+240
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
        shifted=apply_offset(read(preparation/'preparation.json'),GLOBAL_DELAY_TICKS)
        prep=preparation/'preparation-delayed.json';write_new(prep,shifted)
        debugger=Debugger(prefix)
        def cancellation():
            if (destination/'stop-request.json').exists():raise Cancelled('cancelled before next native task')
        restarts=[];progress=[1]  # native steps completed since the last client restart
        preflight_retries=[0]
        first_preparation=preparation
        def restart_client(name):
            """Release a debugger-lost attempt with its game process, then bind a
            fresh client and fresh runtime; the replay preparation must not change."""
            nonlocal identity,preparation,prep
            recovered=recover_failed_attempt(destination,name,identity)
            if not generation_released(identity):raise RuntimeError('debugger lost the game but its process was not released')
            number=len(restarts)+1
            status('simulating','本机调试器第 '+str(number)+' 次失去游戏进程（虚拟机偶发，与回放内容无关）；已重启游戏，回到大厅后从当前步骤继续，已完成的预演保留。')
            deadline=time.monotonic()+300
            while True:
                cancellation()
                try:
                    fresh=bind(Path(request['apk']));require_idle_lobby(scene_state(fresh));break
                except MapsSnapshotError:raise
                except (FileNotFoundError,subprocess.CalledProcessError,ValueError):
                    if time.monotonic()>=deadline:raise Cancelled('restarted client did not reach its idle lobby')
                    time.sleep(2)
            fresh_preparation=destination/('native-preparation-r'+str(number))
            metadata(source,fresh_preparation,Path(request['apk']))
            observation=read(fresh_preparation/'runtime/runtime-observation.json')
            require_idle_lobby(observation['scene_state'])
            stable=lambda value:{k:v for k,v in value.items() if not k.endswith('_evidence_sha256')}
            if stable(read(fresh_preparation/'preparation.json'))!=stable(read(first_preparation/'preparation.json')):
                raise RuntimeError('restarted client prepared this replay differently; not continuing')
            restarts.append(dict(attempt=name,recovered=recovered,old_pid=identity['pid'],new_pid=observation['identity']['pid'],at=time.time()))
            write_new(destination/('client-restart-'+str(number)+'.json'),restarts[-1])
            identity=observation['identity'];preparation=fresh_preparation
            context.update(game_pid=identity['pid'],game_start_time=identity['process_start_time'],client_restarts=len(restarts))
            current_prep()
        def current_prep():
            """Inputs compile against the CURRENT client's runtime: a preparation
            made before a client restart is copied unchanged next to it."""
            nonlocal prep
            if prep.parent==preparation:return
            moved=preparation/prep.name
            if not moved.exists():write_new(moved,read(prep))
            elif read(moved)!=read(prep):raise RuntimeError('preparation name collision after client restart')
            prep=moved
        def probe(name,*,execute=False,native=None,scene=False,candidate=False):
            nonlocal last_attempt
            # Prepare/bind immediately before every component; never migrate old
            # input owners if the client has restarted in the meantime.
            cancellation();ReadOnlySession(identity).verify()
            current_prep()
            build=destination/(name+'-build')
            compile_component(prep,build,prefix,run_source=execute,native_replay=native,scene=scene,speed=speed)
            publish_inputs(destination,build,preparation/'runtime',name)
            if not context['native_entry_started']:
                write_new(destination/'native-entry.json',dict(native_entry_started=True,created_at=time.time()))
                context['native_entry_started']=True
            result=debugger.run(destination,name,scene=scene)
            last_attempt=name
            if not scene and debugger_lost(result) and len(restarts)<DEBUGGER_LOSS_RESTARTS and progress[0]:
                progress[0]=0
                restart_client(name)
                return probe(name+'-r'+str(len(restarts)),execute=execute,native=native,candidate=candidate)
            # The game was briefly not an idle lobby; nothing ran and the component was
            # released, so waiting for the lobby and running the same step again is safe.
            if (not scene and (result.get('resource_preflight_rejected') or result.get('publication_refused'))
                    and result.get('component_unloaded') and preflight_retries[0]<PREFLIGHT_RETRIES):
                preflight_retries[0]+=1
                status('simulating','游戏短暂不在空闲大厅，本步未执行任何原生操作；等待大厅稳定后重试这一步（第 '+str(preflight_retries[0])+' 次）。')
                wait_idle_lobby(identity,progress=status,cancellation=cancellation,timeout=180)
                return probe(name+'-p'+str(preflight_retries[0]),execute=execute,native=native,candidate=candidate)
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
                if not result.get('detached') or not result.get('source_bootstrap_verified') or not result.get('component_unloaded'):
                    checked_receipt(result,execute=True)
            else:checked_receipt(result,execute=execute,scene=scene)
            progress[0]+=1
            return result
        status('calibrating','手机本机：核验原生初始发牌和安全释放。')
        delayed=copy.deepcopy(shifted)
        seen=[];deal_seeds=None
        for calibration in range(24):
            seen.append(deck_fingerprint(shifted))
            deal=probe('bootstrap-v2' if calibration==0 else 'deal-check-'+str(calibration))
            try:aligned=calibrate(shifted,deal,seen)
            except ValueError as error:
                from align_native_deal import DEAL_SEED_INFEASIBLE
                if DEAL_SEED_INFEASIBLE not in str(error):raise
                # Collector/Mirror land where the seed's draws put them, whatever the
                # deck order: this seed can never deal the page's order. Try another.
                if deal_seeds is None:
                    context['deal_seed_original']=shifted['initialization_only']['rndSeed']
                    deal_seeds=iter(seed_plan(replay_key(read(source)),shifted['initialization_only']['rndSeed']))
                seed=next(deal_seeds)
                for doc in (shifted,delayed):doc['initialization_only']['rndSeed']=seed
                context.update(deal_seed=seed,deal_seed_changed=True);seen.clear()
                status('calibrating','开局牌序：采集器/镜像的位置只由随机种子决定，当前种子排不出网页的出牌顺序；换随机种子 '+str(seed)+' 重新发牌。')
                prep=preparation/('preparation-deal-seed-'+str(calibration)+'.json');write_new(prep,shifted)
                continue
            prep=preparation/('preparation-calibrated-'+str(calibration)+'.json');write_new(prep,aligned)
            if aligned['native_deal_ready']:break
            shifted=aligned
        else:raise RuntimeError('原生牌序有界校准未通过；没有执行源指令')
        status('simulating','手机原生引擎：完整执行全部下牌和技能。')
        from ability_search import search,terminal_hp_matches,damage_lower_bound,CandidateMemo
        def hp_bound(candidate,result):return damage_lower_bound(read(source),candidate,result)
        selected_candidate={}
        attempt_prefix=''
        # The user may end either search at any time and play the closest
        # complete result so far; checked between native attempts only.
        def seed_stop():return (destination/'seed-stop-request.json').exists()
        snapshots={}
        candidate_memo=CandidateMemo()
        from ability_search import ELIXIR_MISMATCH_COST
        def rank(tier,difference):
            # Only runs that leak the page's elixir can be published: they come first.
            return (type(difference) is int and difference>=ELIXIR_MISMATCH_COST,PAGE_MATCH_TIERS.index(tier),difference if difference is not None else 1<<30)
        def restore(search_result):
            chosen=search_result['attempts'][search_result['chosen_attempt']]['evidence']['attempt']
            selected_candidate.clear();selected_candidate.update(snapshots[chosen])
        # Hunter/Skeleton King decks: a wrong ability target changes the battle far
        # more than the shared random seed. Among fully executed ability
        # combinations (original seed) keep the one with the smallest page cost
        # (six-tower HP difference plus the weighted end-time difference), then search seeds with
        # that combination fixed. Other decks keep the strict exact-HP rule.
        closest_abilities=seed_search_policy(read(source),'different')['allowed']
        closest_best={}
        def hp_key(candidate,result):
            tier,difference=page_comparison(read(source),candidate,result)
            key=(difference if difference is not None else 1<<40,PAGE_MATCH_TIERS.index(tier))
            if not attempt_prefix and (not closest_best or key<closest_best['key']):closest_best.update(key=key,tier=tier,difference=difference)
            return key
        # The page's leaked elixir pins what each hero ability cost: a branch whose
        # leak has already passed the page's can never end at it. Keep the deepest
        # ability combination (original seed) still within it, even when that run
        # ended early, so the seed search can fix the elixir-consistent heroes.
        elixir_consistent={}
        def track_elixir(candidate,result):
            from ability_search import elixir_rows,ELIXIR_TOLERANCE
            rows=[r for r in elixir_rows(read(source),result) if r['page'] is not None and r['simulated'] is not None]
            if not rows or any(r['simulated']>=r['page']+ELIXIR_TOLERANCE-1e-6 for r in rows):return
            choices=dict(candidate.get('ability_target_choices') or {})
            key=(len(choices),result.get('tick') if type(result.get('tick')) is int else 0)
            if choices and (not elixir_consistent or key>elixir_consistent['key']):elixir_consistent.update(key=key,choices=choices)
        def execute_candidate(candidate,number):
            nonlocal prep
            prep=preparation/(attempt_prefix+'ability-candidate-'+str(number)+'.json');write_new(prep,candidate)
            name=(attempt_prefix+'candidate-'+str(number)) if attempt_prefix else ('bootstrap-v3' if number==0 else 'ability-candidate-'+str(number))
            if not attempt_prefix and closest_abilities:
                found=('当前最接近的完整组合'+cost_text(closest_best['difference'])+'（塔血差 + 终局时间差 + 溢出圣水，圣水必须一致）。可随时点「停止匹配，用当前最接近的开播」。') if closest_best.get('difference') is not None else \
                      ('已有完整组合（终局无法完整比对）。可随时停止匹配并开播。' if closest_best else '尚无完整执行的组合；有完整组合后才能停止匹配开播。')
                status('simulating','技能目标匹配：完整预演候选 '+str(number+1)+'。卡组含猎人/骷髅之王，先选六塔血差最小的技能组合，再匹配随机种子。'+found,
                       seed_search_active=bool(closest_best),ability_search_active=True)
            elif not attempt_prefix:status('simulating','完整预演技能目标候选 '+str(number+1)+'；优先选终局塔血与网页一致的候选。'+
                '技能目标必须与网页完全一致。')
            candidate_receipt=probe(name,execute=True,candidate=True)
            name=last_attempt  # a client restart reruns the step under a suffixed name
            selected_candidate.update(receipt=candidate_receipt,preparation=prep)
            snapshots[name]=dict(receipt=candidate_receipt,preparation=prep)
            result=read(destination/(name+'-source-execution.json'))
            if not attempt_prefix:track_elixir(candidate,result)
            return result,dict(attempt=name,preparation=str(prep))
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
            # Ability targets must match exactly: an ambiguous branch is accepted only
            # when the whole battle ends at the page's tower HP. Exception: Hunter/
            # Skeleton King decks keep the closest complete combination (above), and
            # each alternate seed reruns that combination first.
            ability_error=None;elixir_rejection=None
            original_seed=aligned['initialization_only']['rndSeed']
            try:
                aligned,execution,search_result=search(aligned,execute_candidate,
                    lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                    cancelled=lambda:(destination/'stop-request.json').exists(),bound=hp_bound,
                    closest=hp_key if closest_abilities else None,stop_early=seed_stop if closest_abilities else lambda:False,
                    patience=24 if closest_abilities else None)
                restore(search_result)
                context.update(ability_closest_selected=bool(search_result.get('closest_selected')))
            except Exception as error:
                if hasattr(error,'search_report'):write_new(destination/'ability-search.json',error.search_report)
                if not getattr(error,'search_report',{}).get('explored_branches_exhausted'):raise
                ability_error=error
            if ability_error is None:
                write_new(destination/'ability-search.json',search_result)
                # Always compare the simulated end with the page (the search only does so for ambiguous abilities).
                tier,difference=page_comparison(read(source),aligned,execution)
                best=(rank(tier,difference),original_seed,tier,difference,(aligned,execution,search_result,dict(selected_candidate)))
                if type(difference) is int and difference>=ELIXIR_MISMATCH_COST:
                    # Leaked elixir differs: the heroes are wrong, so this run is discarded, not kept as a fallback.
                    elixir_rejection=elixir_gate(read(source),aligned,execution)
                    tier,difference='different',None
                    best=((True,len(PAGE_MATCH_TIERS),0),original_seed,'different',None,None)
            else:
                tier,difference='different',None
                best=((len(PAGE_MATCH_TIERS),0),original_seed,'different',None,None)
            seed_policy=seed_search_policy(read(source),tier)
            context.update(seed_search_allowed=seed_policy['allowed'],seed_search_cards=seed_policy['eligible_cards'],
                           seed_search_skip_reason=seed_policy['skip_reason'])
            seed_report=dict(original_seed=original_seed,original_tier=tier,original_difference=difference,attempts=[],selected_seed=original_seed,
                             original_ability_branches_matched=ability_error is None,policy=seed_policy)
            # The user may end the search at any time and play the closest result so far.
            tier_names=dict(exact='完全一致',same_towers='终局近似',same_winner='仅胜负相同',different='不符',unknown='无法完整比对')
            match_key=replay_key(read(source));memory_path=files/'seed-memory.json'
            try:seed_memory=read(memory_path) if memory_path.is_file() else {}
            except (OSError,ValueError):seed_memory={}
            remembered=seed_memory.get(match_key) if isinstance(seed_memory.get(match_key),dict) else {}
            remembered_seed=remembered.get('seed') if remembered.get('tier') in PAGE_MATCH_TIERS[:3] else None
            seed_report.update(match_key=match_key,remembered_seed=remembered_seed)
            # A discarded original run never seeds the search; the elixir-consistent heroes do.
            fixed_choices=dict(aligned.get('ability_target_choices') or {}) if best[4] is not None else {}
            elixir_inferred=bool(closest_abilities and elixir_consistent and best[4] is None)
            if elixir_inferred:fixed_choices=dict(elixir_consistent['choices'])
            seed_report['fixed_ability_choices']=fixed_choices if closest_abilities else None
            seed_report['ability_choices_from_elixir']=elixir_inferred
            if seed_policy['search_needed']:
                card_names='、'.join('骷髅之王' if card=='skeleton-king' else '猎人' for card in seed_policy['eligible_cards'])
                if ability_error is not None:status('simulating','原种子下技能目标没有与网页完全一致的分支；卡组含'+card_names+'，按策略尝试其他种子（技能目标仍要求完全一致，不代表已确认差异来自随机性）。')
                if elixir_inferred:status('simulating','按网页溢出圣水限定英雄技能：先试与溢出圣水相符的 '+str(len(fixed_choices))+' 次技能英雄，每个种子仍继续枚举其余技能分支。')
                # Successive halving. Screening: every seed gets ONE deal probe and one
                # full run (the calibrated deal is predicted from that probe; the run
                # itself verifies it and a mismatch falls back to normal calibration).
                # Refinement: only the closest few seeds get a deeper ability search.
                screened=[]
                def nonlocal_prep_write(path,value):
                    nonlocal prep
                    write_new(path,value);prep=path
                def calibrated(number,seed,optimistic):
                    trial=copy.deepcopy(delayed);trial['initialization_only']['rndSeed']=seed;trial_seen=[]
                    for calibration in range(12):
                        if seed_stop():raise Cancelled('seed search stopped by user')
                        trial_seen.append(deck_fingerprint(trial))
                        name='seed-'+str(number)+('-deal-' if optimistic else '-recal-')+str(calibration)
                        nonlocal_prep_write(preparation/(name+'.json'),trial)
                        trial=calibrate(trial,probe(name),trial_seen)
                        if trial['native_deal_ready'] or optimistic:return trial
                    raise RuntimeError('seed deal calibration did not converge')
                def run_seed(number,seed,trial,prefix,**options):
                    nonlocal attempt_prefix
                    attempt_prefix=prefix
                    def released(report,evidence):
                        receipt=snapshots.get(evidence.get('attempt'),{}).get('receipt') or {}
                        return (receipt.get('detached') is True and receipt.get('source_bootstrap_verified') is True
                                and receipt.get('component_unloaded') is True)
                    def reusable(candidate,index):
                        # Scope is captured afresh, never reuse evidence across a recovered client.
                        before=candidate_scope(identity)
                        def still_released(report,evidence):
                            return released(report,evidence) and candidate_scope(identity)==before
                        def verify_reuse():
                            if candidate_scope(identity)!=before:raise ValueError('candidate scope changed before reuse')
                        return candidate_memo.run(candidate,index,execute_candidate,scope=before,
                            verify=verify_reuse,cacheable=still_released)
                    try:
                        result=search(trial,reusable,
                            lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                            cancelled=lambda:(destination/'stop-request.json').exists() or seed_stop(),bound=hp_bound,**options)
                        result[2]['candidate_reuse']=candidate_memo.stats()
                        return result
                    finally:
                        attempt_prefix=''
                        seed_report['candidate_reuse']=candidate_memo.stats()
                def consider(number,seed,result,row):
                    nonlocal best
                    trial,trial_execution,trial_search=result
                    restore(trial_search)
                    trial_tier,trial_difference=page_comparison(read(source),trial,trial_execution)
                    if type(trial_difference) is int and trial_difference>=ELIXIR_MISMATCH_COST:
                        raise RuntimeError(elixir_gate(read(source),trial,trial_execution)+'；已丢弃')
                    row.update(executed=True,tier=trial_tier,difference=trial_difference,
                               towers=(trial_execution.get('battle_state') or {}).get('towers'))
                    entry=(rank(trial_tier,trial_difference),seed,trial_tier,trial_difference,
                           (trial,trial_execution,trial_search,dict(selected_candidate)))
                    if entry[0]<best[0]:best=entry
                    return entry
                def incumbent():return best[3] if type(best[3]) is int else None
                def closest_text():
                    # Only runs that passed the elixir check are kept; say so instead of a placeholder tier.
                    return '尚无溢出圣水与网页一致的完整组合' if best[4] is None else tier_names[best[2]]+cost_text(best[3])
                for number,seed in enumerate(seed_plan(match_key,original_seed,remembered=remembered_seed)):
                    if (destination/'stop-request.json').exists():raise Cancelled('cancelled during seed search')
                    if seed_stop():seed_report['stopped_by_user']=True;break
                    status('simulating','终局未完全匹配；卡组含'+card_names+'，筛选随机种子 '+str(number+1)+'/'+str(SEED_ATTEMPTS)+'（之后精修最接近的 '+str(REFINE_SEEDS)+' 个），当前最接近：'+closest_text()+
                           ''+'。可随时点「停止匹配，用当前最接近的开播」。',
                           seed_search_active=True,seed_attempt=number+1,seed_total=SEED_ATTEMPTS,seed_best_tier=best[2],seed_best_difference=best[3])
                    row=dict(seed=seed,phase='screen')
                    try:
                        trial=calibrated(number,seed,True)
                        # Without a combination that completed at the original seed, one run
                        # always stops at the first ambiguous ability: search that seed itself.
                        # Elixir-inferred heroes only constrain: they are tried first, and the
                        # seed still enumerates its own branches (pruned by leaked elixir).
                        complete_fixed=bool(fixed_choices) and not elixir_inferred
                        options=(dict(initial=fixed_choices,closest=hp_key,max_attempts=SCREEN_RUNS if complete_fixed else SCREEN_RUNS_UNFIXED,
                                      patience=None if complete_fixed else 6,incumbent=incumbent()) if closest_abilities else {})
                        try:result=run_seed(number,seed,trial,'seed-'+str(number)+'-',**options)
                        except RuntimeError as error:
                            if 'native deal mismatch' not in str(error):raise
                            row['deal_recalibrated']=True
                            trial=calibrated(number,seed,False)
                            result=run_seed(number,seed,trial,'seed-'+str(number)+'-v-',**options)
                        entry=consider(number,seed,result,row)
                        screened.append((entry[0],number,seed,trial,dict(entry[4][0].get('ability_target_choices') or {})))
                    except Cancelled:
                        if not seed_stop():raise
                        row.update(executed=False,error='stopped by user before this seed ran')
                        seed_report['attempts'].append(row);seed_report['stopped_by_user']=True;break
                    except Exception as error:
                        row.update(executed=False,error=str(error)[:300])
                        # A retained native attempt still owns the game: every later seed
                        # would be refused, so stop here and let failure recovery release it.
                        if 'native attempt retained' in str(error) or 'still owns game' in str(error):
                            seed_report['attempts'].append(row);write_new(destination/'seed-search.json',seed_report);raise
                    seed_report['attempts'].append(row)
                    if seed_stop():seed_report['stopped_by_user']=True;break
                    if best[2]=='exact':break
                if closest_abilities and best[2]!='exact' and not seed_stop():
                    for step,(_,number,seed,trial,choices) in enumerate(sorted(screened,key=lambda item:item[0])[:REFINE_SEEDS]):
                        if (destination/'stop-request.json').exists():raise Cancelled('cancelled during seed refinement')
                        if seed_stop():seed_report['stopped_by_user']=True;break
                        status('simulating','精修最接近的种子 '+str(step+1)+'/'+str(REFINE_SEEDS)+'：在该种子下搜索技能组合，当前最接近：'+closest_text()+
                               ''+'。可随时点「停止匹配，用当前最接近的开播」。',
                               seed_search_active=True,seed_attempt=len(seed_report['attempts'])+1,seed_total=SEED_ATTEMPTS,seed_best_tier=best[2],seed_best_difference=best[3])
                        row=dict(seed=seed,phase='refine')
                        try:
                            result=run_seed(number,seed,trial,'seed-'+str(number)+'-r-',initial=choices,closest=hp_key,
                                            max_attempts=REFINE_RUNS,patience=8,incumbent=incumbent())
                            consider(number,seed,result,row)
                        except Cancelled:
                            if not seed_stop():raise
                            seed_report['stopped_by_user']=True;break
                        except Exception as error:row.update(executed=False,error=str(error)[:300])
                        seed_report['attempts'].append(row)
                        if best[2]=='exact':break
            if best[4] is None:
                write_new(destination/'seed-search.json',seed_report)
                reason=str(ability_error) if ability_error is not None else (elixir_rejection or '没有溢出圣水与网页一致的完整分支')
                raise RuntimeError(reason+' '+seed_search_note(len(seed_report['attempts']),seed_policy['allowed'])+'；没有溢出圣水和技能目标都与网页一致的分支，未发布回放。')
            _,selected_seed,tier,difference,(aligned,execution,search_result,chosen)=best
            selected_candidate.clear();selected_candidate.update(chosen)
            seed_report.update(selected_seed=selected_seed,selected_tier=tier,selected_difference=difference)
            # Remember the closest seed of this MATCH so a re-saved page reproduces it.
            previous=seed_memory.get(match_key) if isinstance(seed_memory.get(match_key),dict) else {}
            if rank(tier,difference)<rank(previous.get('tier','unknown'),previous.get('difference')) and tier in PAGE_MATCH_TIERS[:3]:
                seed_memory[match_key]=dict(seed=selected_seed,tier=tier,difference=difference,replay_tag=read(source).get('replay_tag'),updated_at=time.time())
                temp=files/'seed-memory.tmp'
                with temp.open('w') as stream:json.dump(seed_memory,stream,ensure_ascii=False,indent=1)
                os.chown(temp,owner.st_uid,owner.st_gid);temp.replace(memory_path)
            hp_matched=tier=='exact'
            write_new(destination/'seed-search.json',seed_report)
            receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']
            context['ability_target_inferred']=search_result['inferred']
            # final_hp_matched: the whole simulated battle ends exactly at the page's tower HP.
            # random_seed_inferred: matched only with a substituted seed; not proof of the original process.
            # Per-tower record of the run actually selected, for side-by-side checks.
            breakdown=page_breakdown(read(source),aligned,execution)
            write_new(destination/'page-comparison.json',dict(tier=tier,difference=difference,match_cost=difference,**breakdown,
                                                              towers=page_towers(read(source),aligned,execution)))
            context.update(final_hp_matched=hp_matched,page_match=tier,page_hp_difference=breakdown['hp_difference'],page_match_cost=difference,
                           page_time_difference_seconds=breakdown['time_difference_seconds'],random_seed=seed_report['selected_seed'],
                           random_seed_inferred=seed_report['selected_seed']!=original_seed or bool(context.get('deal_seed_changed')),seed_attempts=len(seed_report['attempts']),
                           page_elixir_matched=breakdown['elixir_matched'])
            # Final gate: both players must leak exactly the page's elixir, which pins
            # what was paid for abilities. Anything else is never published.
            elixir_refusal=elixir_gate(read(source),aligned,execution)
            if elixir_refusal is not None:
                raise RuntimeError(elixir_refusal+'（'+seed_search_note(len(seed_report['attempts']),seed_policy['allowed'])+'）；未放行，未发布回放。')
            full=finalize(aligned,execution,receipt)
            native=preparation/'complete-native.json';write_new(native,full)
            status('validating','手机本机：核对完整录像的原生 JSON 往返。')
            probe('bootstrap-v4',execute=True,native=native)
            roundtrip=read(destination/(last_attempt+'-source-execution.json'))
            if not roundtrip.get('loaded_from_json') or roundtrip['commands']!=full['native_replay']['cmd']:
                raise RuntimeError('native JSON round-trip changed source commands')
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
        seed_note=seed_search_note(context.get('seed_attempts',0),context.get('seed_search_allowed',False))
        while True:
            cancellation();ReadOnlySession(identity).verify()
            if diagnostic is not None:ready_message='诊断前缀证据已核验；等待打开游戏，未通过整局校验。'
            elif context.get('page_match')=='unknown':ready_message='全部指令已执行；终局有塔缺少网页数据或模拟记录，无法完整比对（未当作不一致，'+seed_note+'）；可以播放。'
            elif context.get('page_match')=='same_towers':ready_message='胜负和被摧毁的塔与网页一致，塔血合计相差 '+str(context.get('page_hp_difference'))+time_note(context)+elixir_note(context)+'（'+seed_note+'）；等待打开游戏，此时尚未开播。'
            elif context.get('page_match')=='same_winner':ready_message='胜负与网页一致，但被摧毁的塔不同（'+seed_note+'）；仍可播放，过程与原局不同。'
            elif not context.get('final_hp_matched'):ready_message='全部指令已执行，但终局与网页不符（'+seed_note+'）；仍可播放，过程可能与原局不同。'
            elif context.get('random_seed_inferred'):ready_message='整局核验通过：换用随机种子后终局塔血与网页完全一致'+elixir_note(context)+'（原种子未知，过程为推断）；等待打开游戏，此时尚未开播。'
            else:ready_message='整局计算、全部指令和终局塔血均与网页一致'+elixir_note(context)+'；等待悬浮进度卡就绪并打开游戏，此时尚未开播。'
            if context.get('ability_closest_selected'):ready_message='技能目标取六塔血差最小的完整组合（推断，未与网页完全一致）。'+ready_message
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
                stop_owned(identity,scene,comp['device_path'])
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
                stop_owned(identity,terminal,read(destination/'scene-v1-component.json')['device_path'],reopen=True)
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
        # Keep the cause even when the game is already gone.
        with (destination/'error.txt').open('x') as stream:stream.write(traceback.format_exc())
        if released and not completed:
            status('released','游戏进程已结束，控制台已就绪；原回放记录保留。',monitor_active=False,generation_released=True)
            return
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
        for path in sorted(destination.rglob('*'),reverse=True):
            if path.is_symlink():raise ValueError('unexpected link in private replay job')
            os.chown(path,owner.st_uid,owner.st_gid)
        os.chown(destination,owner.st_uid,owner.st_gid)
