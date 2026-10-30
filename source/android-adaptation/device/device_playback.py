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
from seed_search_control import BestRequested,SearchBudgetExhausted,requested as best_requested,choose_trials,search_reasons,require_attempt_budget


PREPARE_AHEAD_SECONDS=7200
# The page carries no battle random seed. Some abilities (e.g. Skeleton King's
# summon) consume the engine RNG, so a fixed seed can end differently from the
# page. Only an actual Hunter play or identifiable Skeleton King ability
# enables retries when final tower HP differs. Every candidate must fully run.
SEED_ATTEMPTS=60
SCREEN_RUNS=12
SCREEN_RUNS_UNFIXED=12
REFINE_SEEDS=3
REFINE_RUNS=24
PAGE_MATCH_TIERS=('exact','same_towers','same_winner','different','unknown')


def page_tower_comparison(source, preparation, report):
    """Compare a fully executed run with the page's six final towers.

    Uses the same per-tower rule as the ability check (final_tower_rows).
    Returns (tier, hp_difference): exact HP values; same destroyed-tower counts
    (not physical sides); same winner only; different; or unknown when any tower lacks
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

def seed_search_policy(source,tier):
    from seed_search_control import search_reasons
    reasons=search_reasons(dict(events=source.get('actions',[])),source)
    cards=sorted({'hunter' if 'hunter' in str(r).lower() else 'skeleton-king' for r in reasons})
    allowed=bool(reasons)
    return dict(eligible_cards=cards,allowed=allowed,search_needed=allowed and tier not in ('exact','unknown'),
                skip_reason='exact_match' if tier=='exact' else 'final_towers_unknown' if tier=='unknown' else None if allowed else 'no_seed_sensitive_card')

def time_note(context):
    seconds=context.get('page_time_difference_seconds')
    return '' if seconds is None else '，终局时间相差 '+('%.1f'%abs(seconds))+' 秒'


def elixir_note(context):
    return ('，双方溢出圣水在额外 0.05 容差内（近似）' if context.get('page_elixir_strict_matched') is False else '，双方溢出圣水与网页一致') if context.get('page_elixir_matched') is True else ''


def cost_text(cost, breakdown=None):
    """Explain a single candidate's cost; never mix rows from different seeds."""
    from ability_search import ELIXIR_MISMATCH_COST
    if type(cost) is not int:return ''
    if breakdown is not None:
        hp=breakdown.get('hp_difference');delta=breakdown.get('time_difference_seconds')
        time_cost=breakdown.get('time_penalty');elixir_cost=breakdown.get('elixir_penalty')
        def value(v):return '未知' if v is None else str(v)
        timing='终局时间差未知' if delta is None else ('终局时间一致' if delta==0 else
            '终局'+('晚' if delta>0 else '早')+('%.2f'%abs(delta))+' 秒')
        parts=['综合差距 '+str(cost)+' = 塔血差 '+value(hp)+' + 时间罚分 '+value(time_cost)+' + 圣水罚分 '+value(elixir_cost),
               timing+'（允许 ±1 秒）']
        towers=breakdown.get('towers',[])
        for owner in sorted({r['owner'] for r in towers}):
            rows=[r for r in towers if r['owner']==owner]
            side=rows[0].get('source_side')
            label='蓝方' if side=='team' else '红方' if side=='opponent' else ('蓝方' if owner==0 else '红方')
            details=[]
            for r in rows:
                name='国王塔' if r['tower']=='king' else '公主塔'
                details.append(name+' '+value(r.get('page'))+'→'+value(r.get('simulated'))+'（差'+value(r.get('difference'))+'）')
            parts.append(label+'塔血（网页→模拟）：'+'、'.join(details))
        if any(r.get('page_pairing_inferred') for r in towers):
            parts.append('公主塔已在同一玩家内按最小血差自动配对')
        for owner in (0,1):
            row=next((r for r in breakdown.get('elixir',[]) if r.get('owner')==owner),{})
            page=row.get('page');simulated=row.get('simulated')
            side=row.get('source_side')
            label='蓝方' if side=='team' else '红方' if side=='opponent' else ('蓝方' if owner==0 else '红方')
            if page is None or simulated is None:
                parts.append(label+'溢出圣水：缺少比对数据');continue
            verdict=('通过额外 %.2f 容差（近似）'%row.get('tolerance_margin',0) if row.get('strict_matched') is False else '通过网页截断范围') if row.get('matched') is True else '不通过' if row.get('matched') is False else '未判定'
            parts.append(label+'溢出圣水：网页 %.2f / 模拟 %.4f，差 %+.4f（%s）'%(page,simulated,simulated-page,verdict))
        return '（'+'；'.join(parts)+'）'
    if cost>=ELIXIR_MISMATCH_COST:return '（溢出圣水不一致，综合差距 '+str(cost-ELIXIR_MISMATCH_COST)+'）'
    return '（综合差距 '+str(cost)+'；分项尚未核验）'


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
    from ability_search import terminal_time,TIME_WEIGHT_PER_TICK,elixir_check,elixir_cost,elixir_strict_check
    tier,difference=page_tower_comparison(source,preparation,report)
    if difference is None:return tier,difference
    excess=terminal_time(source,report)['excess_ticks'] or 0
    elixir_matched,_=elixir_check(source,report)
    if tier=='exact' and (excess>0 or elixir_matched is False or elixir_strict_check(source,report) is False):tier='same_towers'
    return tier,difference+TIME_WEIGHT_PER_TICK*excess+elixir_cost(source,report)


def page_breakdown(source, preparation, report):
    """Display values: tower HP difference and end-time difference in seconds."""
    from ability_search import terminal_time,elixir_check,elixir_rows,elixir_cost,TIME_WEIGHT_PER_TICK,final_tower_rows,elixir_strict_check,elixir_margin
    _,hp=page_tower_comparison(source,preparation,report)
    time=terminal_time(source,report)
    elixir_matched,elixir_difference=elixir_check(source,report)
    return dict(hp_difference=hp,towers=final_tower_rows(source,preparation,report),
                time_difference_seconds=None if time['delta_ticks'] is None else round(time['delta_ticks']/20,2),
                time_penalty=None if time['excess_ticks'] is None else TIME_WEIGHT_PER_TICK*time['excess_ticks'],
                elixir_penalty=elixir_cost(source,report),
                elixir_matched=elixir_matched,elixir_strict_matched=elixir_strict_check(source,report),elixir_tolerance_margin=elixir_margin(source),elixir_leaked_difference=elixir_difference,elixir=elixir_rows(source,report),
                page_seconds=None if time['page_ticks'] is None else time['page_ticks']/20,
                simulated_seconds=None if time['simulated_tick'] is None else round(time['simulated_tick']/20,2))


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


def retry_seed_plan(source_sha256,original,initial):
    """An advisory seed must not hide the original or consume duplicate trials."""
    seeds=([original] if initial!=original else [])+[seed for seed in seed_plan(source_sha256,original) if seed!=initial]
    return seeds[:SEED_ATTEMPTS]


def read(path):return json.loads(path.read_text())


def write_new(path, value):
    with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def write_search_snapshot(path,value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('w') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    os.replace(temporary,path)


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
    deadline=None if timeout is None else time.monotonic()+timeout;stable_since=None
    while deadline is None or time.monotonic()<deadline:
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
            if self.translated:
                from mumu_context import ready as context_ready
                samples=[];measure['mumu_pre_expression_context']=samples
                for sample in range(20):
                    ready,observation=context_ready(lldb,process,identity['pid'],session.verify())
                    samples.append(observation)
                    if ready:break
                    # No expression, allocation or component load has occurred.
                    # Detach resumes only original game code; reattach the same
                    # verified generation. Never use this after a failed call.
                    if sample==19:raise RuntimeError('MuMu host wait context unavailable before any expression; no component called')
                    if not process.Detach().Success():raise RuntimeError('MuMu context sample detach failed')
                    attachment.close();attachment=None;process=None
                    time.sleep(.03);session.verify()
                    with (directory/(attempt+'-server.log')).open('a') as log:
                        attachment=Attachment(lldb,target,self.debugger.GetListener(),identity['pid'],log)
                    process=attachment.process
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
    progress_observer=None
    prediction_flags={}
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
        if progress_observer is not None:value['prediction_progress']=progress_observer.snapshot()
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
        adaptive_test=request.get('skill_target_test',{}).get('schema')=='royale-replay.adaptive-search-test.v1'
        if adaptive_test and request['skill_target_test'].get('source_sha256')!=request['source_sha256']:
            raise ValueError('adaptive simulation test source differs')
        diagnostic=diagnostic_bundle(request,files)
        context['source_sha256']=request['source_sha256']
        source=checked_source_manifest(request_path,request['source_manifest'])
        if request['source_sha256']!=read(source)['source_sha256']:raise ValueError('source request differs')
        matching_document=read(source)
        context['elixir_tolerance_margin']=0.05
        matching_document['elixir_match_margin']=0.05  # User-authorized small tolerance; exact remains strict.
        matching_document['original_source_manifest_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        source=destination/'matching-source.json';write_new(source,matching_document)
        locked_contract=None
        if request.get('seed_locked_playback'):
            from locked_seed_playback import load as load_locked
            locked_contract=load_locked(files,request['source_sha256'],request['seed_locked_playback'])
            write_new(destination/'seed-locked-contract.json',locked_contract)
            context.update(seed_locked_playback=True,requested_random_seed=locked_contract['random_seed'],checkpoint_prefix_verified=False)
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
        if mumu_enabled():
            floors=[None,None]
            for deck in read(source)['decks']:floors[deck['proposed_native_owner']]=[deck['oracle_final_hp'][key] for key in ('king','princess0','princess1')]
            hint_initial.update(oracle_tower_hp=floors,prune_below_oracle=bool(request.get('skill_target_test') or locked_contract))
        from preparation_hint import load as load_hint,save as save_hint
        shifted,hint_detail=load_hint(files,hint_initial)
        if request.get('skill_target_test',{}).get('schema')=='royale-replay.free-skill-checkpoint.v1':
            shifted=copy.deepcopy(hint_initial);hint_detail={'used':False,'reason':'free skill checkpoint starts from source seed and no cached skill choices'}
            from skill_checkpoint_search import requested_seed
            original=hint_initial['initialization_only']['rndSeed']
            shifted['initialization_only']['rndSeed']=requested_seed(request['skill_target_test'],original,seed_plan(request['source_sha256'],original,16))
        elif locked_contract:
            shifted=copy.deepcopy(hint_initial);shifted['initialization_only']['rndSeed']=locked_contract['random_seed']
            hint_detail={'used':False,'reason':'user selected seed and native-verified checkpoint prefix'}
        if not request.get('skill_target_test') and not locked_contract:
            shifted['prune_below_oracle']=False
            shifted.pop('ability_actor_names',None)
            shifted.pop('ability_target_choices',None)
        source_seed=hint_initial['initialization_only']['rndSeed']
        context['preparation_hint_used']=hint_detail['used']
        write_new(destination/'preparation-hint.json',hint_detail)
        prep=preparation/'preparation-delayed.json';write_new(prep,shifted)
        debugger=Debugger(prefix)
        def cancellation():
            if (files/'reset-in-progress.json').exists():raise Cancelled('explicit replay reset; no next native task')
            if (destination/'stop-request.json').exists():raise Cancelled('cancelled before next native task')
        def prediction_stage(phase):
            if progress_observer is not None:
                progress_observer.observe('stage',phase)
                status('simulating',progress_observer.message(),**prediction_flags)
        def probe(name,*,execute=False,native=None,scene=False,candidate=False):
            nonlocal last_attempt
            # Prepare/bind immediately before every component; never migrate old
            # input owners if the client has restarted in the meantime.
            cancellation();ReadOnlySession(identity).verify()
            if mumu_enabled():require_attempt_budget(destination,name)
            if context.get('seed_search_active') and (request.get('skill_target_test') or locked_contract):
                if best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity):raise BestRequested()
                status('simulating',('技能组合匹配，当前最优逐塔血差 '+str(context.get('best_page_hp_difference')) if context.get('ability_search_active') else '匹配随机种子 '+str(context.get('seed_trial_number',0))+'/'+str(SEED_ATTEMPTS))+'；'+('完整预演候选对局' if execute else '核验初始牌序')+'。可停止匹配并播放已完整执行的最优结果。')
            if not game_foreground():
                # Android can evict lobby resources when a full-screen browser
                # covers the client. Pure HTML workers may keep running; native
                # publication waits for the same client's stable foreground.
                status('waiting_preparation_lobby','后台 HTML 解析继续；原生准备已暂停，等待游戏回到前台大厅。')
                wait_idle_lobby(identity,progress=lambda _phase,message:status('waiting_preparation_lobby',message),cancellation=cancellation,timeout=None)
            if context.get('seed_search_active') and (request.get('skill_target_test') or locked_contract) and best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity):raise BestRequested()
            if candidate:prediction_stage('编译本轮组件')
            compile_started=time.monotonic()
            build=destination/(name+'-build')
            compile_component(prep,build,prefix,run_source=execute,native_replay=native,scene=scene,speed=speed)
            compiled_at=time.monotonic()
            if not game_foreground():
                status('waiting_preparation_lobby','组件已编译；等待游戏回到前台大厅，再执行本场原生校验。')
                wait_idle_lobby(identity,progress=lambda _phase,message:status('waiting_preparation_lobby',message),cancellation=cancellation,timeout=None)
            if context.get('seed_search_active') and (request.get('skill_target_test') or locked_contract) and best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity):raise BestRequested()
            publish_inputs(destination,build,preparation/'runtime',name)
            published_at=time.monotonic()
            if not context['native_entry_started']:
                write_new(destination/'native-entry.json',dict(native_entry_started=True,created_at=time.time()))
                context['native_entry_started']=True
            if candidate:prediction_stage('原生模拟中，等待本分支结果')
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
        seen=[];deal_seeds=None
        for calibration in range(12):
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
        if not request.get('skill_target_test') and not locked_contract:
            from ability_search import search,terminal_hp_matches,damage_lower_bound,CandidateMemo
            def hp_bound(candidate,result):return damage_lower_bound(read(source),candidate,result)
            selected_candidate={}
            attempt_prefix=''
            # The user may end either search at any time and play the closest
            # complete result so far; checked between native attempts only.
            def seed_stop():
                exhausted=sum(1 for _ in destination.glob('*-result.json'))>=252
                if exhausted:context['seed_search_budget_exhausted']=True
                return exhausted or best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity)
            snapshots={}
            candidate_memo=CandidateMemo()
            from mumu_ownership import released_resources as mumu_clean_release
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
                if difference is not None and difference<ELIXIR_MISMATCH_COST and not attempt_prefix and (not closest_best or key<closest_best['key']):
                    closest_best.update(key=key,tier=tier,difference=difference,breakdown=page_breakdown(read(source),candidate,result))
                    context.update(best_source_execution_verified=True,best_page_match=tier,
                        best_page_hp_difference=page_breakdown(read(source),candidate,result)['hp_difference'])
                return key
            # The page's leaked elixir pins what each hero ability cost: a branch whose
            # leak has already passed the page's can never end at it. Keep the deepest
            # ability combination (original seed) still within it, even when that run
            # ended early, so the seed search can fix the elixir-consistent heroes.
            elixir_consistent={}
            from prediction_progress import Progress
            progress_observer=Progress(destination,read(source),page_comparison,page_breakdown)
            from skill_candidate_pool import Pool
            context['skill_pool_mode']=mumu_enabled()
            context['skill_pool_screen_limit']=Pool.screen_limit
            def pool_progress(phase,info):
                if phase=='alns_allocation':
                    context['alns_allocation']=info
                    progress_observer.observe('event','seed_pool_allocation',info)
                else:context.update(skill_pool_size=info['qualified'],skill_pool_seed=info['seed'])
            skill_pool=Pool(read(source),page_comparison,pool_progress)
            def save_skill_pool():
                path=destination/'skill-candidate-pool.json';temp=destination/'skill-candidate-pool.tmp'
                temp.write_text(json.dumps(skill_pool.snapshot(),ensure_ascii=False,indent=2));temp.replace(path)
                context.update(skill_pool_size=len(skill_pool.entries),skill_pool_seed=skill_pool.seed)
            def track_elixir(candidate,result):
                from ability_search import elixir_rows,ELIXIR_TOLERANCE,elixir_margin
                rows=[r for r in elixir_rows(read(source),result) if r['page'] is not None and r['simulated'] is not None]
                if not rows or any(r['simulated']>=r['page']+ELIXIR_TOLERANCE+elixir_margin(read(source))-1e-6 for r in rows):return
                choices=dict(candidate.get('ability_target_choices') or {})
                key=(len(choices),result.get('tick') if type(result.get('tick')) is int else 0)
                if choices and (not elixir_consistent or key>elixir_consistent['key']):elixir_consistent.update(key=key,choices=choices)
            def execute_candidate(candidate,number):
                nonlocal prep
                prep=preparation/(attempt_prefix+'ability-candidate-'+str(number)+'.json');write_new(prep,candidate)
                name=(attempt_prefix+'candidate-'+str(number)) if attempt_prefix else ('bootstrap-v3' if number==0 else 'ability-candidate-'+str(number))
                prediction_flags.update(ability_search_active=True,seed_search_active=bool(attempt_prefix or closest_best))
                progress_observer.observe('begin',candidate,name)
                if not attempt_prefix and closest_abilities:
                    found=('当前最接近的完整组合'+cost_text(closest_best['difference'],closest_best.get('breakdown'))+'（塔血差 + 终局时间差 + 溢出圣水，圣水必须一致）。可随时点「停止匹配，用当前最接近的开播」。') if closest_best.get('difference') is not None else \
                          ('已有完整组合（终局无法完整比对）。可随时停止匹配并开播。' if closest_best else '尚无溢出圣水与网页一致的完整组合；有合格完整组合后才能停止匹配开播。')
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
                if context.get('skill_pool_mode') and skill_pool.qualified(candidate,result):hp_key(candidate,result)
                progress_observer.observe('finish',candidate,result)
                status('simulating',progress_observer.message(),ability_search_active=True,seed_search_active=bool(attempt_prefix or closest_best))
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
                    if context.get('skill_pool_mode'):
                        try:aligned,execution,search_result=skill_pool.enumerate(aligned,execute_candidate,cancelled=lambda:(destination/'stop-request.json').exists(),stop_early=seed_stop,stop_on_exact=True)
                        finally:save_skill_pool()
                    else:
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
                    best=((True,len(PAGE_MATCH_TIERS),0),original_seed,'different',None,None)
                seed_policy=seed_search_policy(read(source),tier)
                if best[4] is not None:
                    context.update(best_source_execution_verified=True,best_page_match=tier,
                        best_page_hp_difference=page_breakdown(read(source),aligned,execution)['hp_difference'])
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
                seed_report.update(match_key=match_key,remembered_seed=remembered_seed,skill_pool_mode=bool(context.get('skill_pool_mode')),per_seed_branch_expansion=not context.get('skill_pool_mode',False))
                # A discarded original run never seeds the search; the elixir-consistent heroes do.
                fixed_choices=dict(aligned.get('ability_target_choices') or {}) if best[4] is not None else {}
                elixir_inferred=bool(closest_abilities and elixir_consistent and best[4] is None and not context.get('skill_pool_mode'))
                if elixir_inferred:fixed_choices=dict(elixir_consistent['choices'])
                seed_report['fixed_ability_choices']=fixed_choices if closest_abilities else None
                seed_report['ability_choices_from_elixir']=elixir_inferred
                if seed_policy['search_needed']:
                    card_names='、'.join('骷髅之王' if card=='skeleton-king' else '猎人' for card in seed_policy['eligible_cards'])
                    if ability_error is not None:status('simulating','原种子下技能目标没有与网页完全一致的分支；卡组含'+card_names+'，按策略尝试其他种子（技能目标仍要求完全一致，不代表已确认差异来自随机性）。')
                    if elixir_inferred:status('simulating','按网页溢出圣水限定英雄技能：先试与溢出圣水相符的 '+str(len(fixed_choices))+' 次技能英雄，每个种子仍继续枚举其余技能分支。')
                    # Successive halving. Screening: one deal probe, then up to twelve
                    # skill-branch runs (the calibrated deal is predicted from that probe; each run
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
                        pool_scope=candidate_scope(identity) if context.get('skill_pool_mode') else None
                        def released(report,evidence):
                            receipt=snapshots.get(evidence.get('attempt'),{}).get('receipt') or {}
                            return (receipt.get('detached') is True and receipt.get('source_bootstrap_verified') is True
                                    and (receipt.get('component_unloaded') is True or mumu_clean_release(receipt)))
                        def reusable(candidate,index):
                            # Scope is captured afresh, never reuse evidence across a recovered client.
                            before=candidate_scope(identity)
                            if pool_scope is not None and before!=pool_scope:raise RuntimeError('pool scope changed before next candidate; no task submitted')
                            def still_released(report,evidence):
                                return released(report,evidence) and candidate_scope(identity)==before
                            def verify_reuse():
                                if candidate_scope(identity)!=before:raise ValueError('candidate scope changed before reuse')
                            hits=candidate_memo.hits
                            result=candidate_memo.run(candidate,index,execute_candidate,scope=before,
                                verify=verify_reuse,cacheable=still_released)
                            context['candidate_reuse']=candidate_memo.stats()
                            if candidate_memo.hits>hits:
                                progress_observer.observe('reused',result[1])
                                status('simulating',progress_observer.message(),ability_search_active=True,seed_search_active=True)
                            return result
                        def verify_pool_cache(cached):
                            return candidate_scope(identity)==pool_scope and all(released(report,evidence) for report,evidence in cached)
                        try:
                            if context.get('skill_pool_mode'):
                                operation=skill_pool.evaluate if skill_pool.entries else skill_pool.enumerate
                                try:
                                    pool_options=dict(alns_budget=options.get('pool_alns_budget',0),scope=pool_scope,verify_reuse=verify_pool_cache) if skill_pool.entries else dict(stop_on_exact=True)
                                    result=operation(trial,reusable,cancelled=lambda:(destination/'stop-request.json').exists(),stop_early=seed_stop,**pool_options)
                                finally:save_skill_pool()
                            else:
                                result=search(trial,reusable,
                                    lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                                    cancelled=lambda:(destination/'stop-request.json').exists() or seed_stop(),bound=hp_bound,**options)
                            result[2]['candidate_reuse']=candidate_memo.stats()
                            return result
                        finally:
                            attempt_prefix=''
                            seed_report['candidate_reuse']=candidate_memo.stats()
                            if context.get('skill_pool_mode'):seed_report['skill_pool']=dict(size=len(skill_pool.entries),seed=skill_pool.seed,per_seed_branch_expansion=False,alns_policy='small-enumeration-diverse-coverage-local-interleaved',alns_total_budget=skill_pool.alns_total_budget,alns_used=len(skill_pool.explorer.history),refinement_used=skill_pool.refinement_used,screen_limit=skill_pool.screen_limit)
                    def consider(number,seed,result,row):
                        nonlocal best
                        trial,trial_execution,trial_search=result
                        restore(trial_search)
                        trial_tier,trial_difference=page_comparison(read(source),trial,trial_execution)
                        if type(trial_difference) is int and trial_difference>=ELIXIR_MISMATCH_COST:
                            raise RuntimeError(elixir_gate(read(source),trial,trial_execution)+'；已丢弃')
                        row.update(executed=True,tier=trial_tier,difference=trial_difference,
                                   breakdown=page_breakdown(read(source),trial,trial_execution),
                                   towers=(trial_execution.get('battle_state') or {}).get('towers'))
                        entry=(rank(trial_tier,trial_difference),seed,trial_tier,trial_difference,
                               (trial,trial_execution,trial_search,dict(selected_candidate)))
                        improves=((trial_difference if trial_difference is not None else 1<<40,PAGE_MATCH_TIERS.index(trial_tier)) < (best[3] if best[3] is not None else 1<<40,PAGE_MATCH_TIERS.index(best[2]))) if context.get('skill_pool_mode') else entry[0]<best[0]
                        if improves:
                            best=entry
                            context.update(best_source_execution_verified=True,best_page_match=trial_tier,
                                best_page_hp_difference=page_breakdown(read(source),trial,trial_execution)['hp_difference'])
                        if trial_tier=='exact':
                            status('validating','已找到全项匹配候选，停止搜索其余种子；正在核对录像。'+cost_text(trial_difference,row['breakdown']),seed_search_active=False,ability_search_active=False)
                        return entry
                    def incumbent():return best[3] if type(best[3]) is int else None
                    def closest_text():
                        # Only runs that passed the elixir check are kept; say so instead of a placeholder tier.
                        return '尚无溢出圣水与网页一致的完整组合' if best[4] is None else tier_names[best[2]]+cost_text(best[3],page_breakdown(read(source),best[4][0],best[4][1]))
                    planned_seeds=list(seed_plan(match_key,original_seed,remembered=remembered_seed))
                    for number,seed in enumerate(planned_seeds):
                        if (destination/'stop-request.json').exists():raise Cancelled('cancelled during seed search')
                        if seed_stop():seed_report['stopped_by_user']=True;break
                        status('simulating','终局未完全匹配；卡组含'+card_names+'，筛选随机种子 '+str(number+1)+'/'+str(len(planned_seeds))+(('（首轮最多 '+str(min(skill_pool.screen_limit,len(skill_pool.entries)))+'/'+str(len(skill_pool.entries))+' 组代表候选，其余延后）' if skill_pool.entries else '（寻找首个完整且圣水一致的建池种子）') if context.get('skill_pool_mode') else '（之后精修最接近的 '+str(REFINE_SEEDS)+' 个）')+'，当前最接近：'+closest_text()+
                               ''+'。可随时点「停止匹配，用当前最接近的开播」。',
                               seed_search_active=True,seed_attempt=number+1,seed_total=len(planned_seeds),seed_best_tier=best[2],seed_best_difference=best[3])
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
                            partial=getattr(error,'search_report',{})
                            if context.get('skill_pool_mode') and partial.get('deferred_pool_candidates',0)>0:
                                row.update(deferred_pool_candidates=partial['deferred_pool_candidates'],screen_attempts=partial.get('screen_attempts'))
                                screened.append(((True,len(PAGE_MATCH_TIERS)-1,(1<<40)-partial.get('best_prefix',0)),number,seed,trial,{}))
                            if 'pool scope changed' in str(error):
                                seed_report['attempts'].append(row);write_new(destination/'seed-search.json',seed_report);raise
                            # A retained native attempt still owns the game: every later seed
                            # would be refused, so stop here and let failure recovery release it.
                            if 'native attempt retained' in str(error) or 'still owns game' in str(error):
                                seed_report['attempts'].append(row);write_new(destination/'seed-search.json',seed_report);raise
                        seed_report['attempts'].append(row)
                        if seed_stop():seed_report['stopped_by_user']=True;break
                        if best[2]=='exact':break
                    if closest_abilities and best[2]!='exact' and not seed_stop():
                        from alns_skills import refinement_schedule
                        refining=(refinement_schedule(screened,limit=REFINE_SEEDS,rounds=skill_pool.alns_total_budget) if context.get('skill_pool_mode') else ((0,row) for row in sorted(screened,key=lambda item:item[0])[:REFINE_SEEDS]))
                        finished_seeds=set()
                        for step,(refine_round,(seed_rank,number,seed,trial,choices)) in enumerate(refining):
                            if (destination/'stop-request.json').exists():raise Cancelled('cancelled during seed refinement')
                            if seed_stop():seed_report['stopped_by_user']=True;break
                            if context.get('skill_pool_mode') and seed in finished_seeds:continue
                            status('simulating','精修候选种子 '+str(seed)+'（第 '+str(refine_round+1)+' 轮）'+('：小空间枚举／多样覆盖后局部调整，当前最接近：' if context.get('skill_pool_mode') else '：在该种子下搜索技能组合，当前最接近：')+closest_text()+
                                   ''+'。可随时点「停止匹配，用当前最接近的开播」。',
                                   seed_search_active=True,seed_attempt=number+1,seed_total=len(planned_seeds),seed_best_tier=best[2],seed_best_difference=best[3])
                            row=dict(seed=seed,phase='refine')
                            if context.get('skill_pool_mode'):
                                if skill_pool.refinement_used>=skill_pool.alns_total_budget:break
                                row.update(refine_round=refine_round+1,allocation='interleaved-one-new-combination')
                            try:
                                result=run_seed(number,seed,trial,'seed-'+str(number)+'-r'+str(refine_round)+'-',initial=choices,closest=hp_key,
                                                max_attempts=REFINE_RUNS,patience=8,incumbent=incumbent(),**(dict(pool_alns_budget=1) if context.get('skill_pool_mode') else {}))
                                consider(number,seed,result,row)
                                if context.get('skill_pool_mode'):
                                    allocation=result[2].get('alns_allocation',{});row['alns_allocation']=allocation
                                    if allocation.get('used')==0:finished_seeds.add(seed)
                            except Cancelled:
                                if not seed_stop():raise
                                seed_report['stopped_by_user']=True;break
                            except Exception as error:
                                row.update(executed=False,error=str(error)[:300])
                                partial=getattr(error,'search_report',{})
                                if partial.get('alns_allocation'):row['alns_allocation']=partial['alns_allocation']
                                if 'pool scope changed' in str(error):
                                    seed_report['attempts'].append(row);write_new(destination/'seed-search.json',seed_report);raise
                                if 'native attempt retained' in str(error) or 'still owns game' in str(error):
                                    seed_report['attempts'].append(row);write_new(destination/'seed-search.json',seed_report);raise
                                if context.get('skill_pool_mode') and not partial.get('alns_allocation',{}).get('can_continue'):finished_seeds.add(seed)
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
                write_new(destination/'page-comparison.json',dict(tier=tier,difference=difference,match_cost=difference,**breakdown))
                context.update(final_hp_matched=hp_matched,page_match=tier,page_hp_difference=breakdown['hp_difference'],page_match_cost=difference,
                               page_time_difference_seconds=breakdown['time_difference_seconds'],random_seed=seed_report['selected_seed'],
                               random_seed_inferred=seed_report['selected_seed']!=original_seed or bool(context.get('deal_seed_changed')),seed_attempts=sum(row.get('phase')=='screen' for row in seed_report['attempts']),
                               page_elixir_matched=breakdown['elixir_matched'],page_elixir_strict_matched=breakdown['elixir_strict_matched'])
                context['page_match_breakdown']=breakdown
                context['page_match_detail']=cost_text(difference,breakdown)
                from failure_recovery import version_hint
                context['version_check_hint']=version_hint(tier)
                # Final gate: both players must leak exactly the page's elixir, which pins
                # what was paid for abilities. Anything else is never published.
                elixir_refusal=elixir_gate(read(source),aligned,execution)
                if elixir_refusal is not None:
                    raise RuntimeError(elixir_refusal+'（'+seed_search_note(len(seed_report['attempts']),seed_policy['allowed'])+'）；未放行，未发布回放。')
                context.update(seed_search_active=False,ability_search_active=False)
                full=finalize(aligned,execution,receipt)
                native=preparation/'complete-native.json';write_new(native,full)
                status('validating','手机本机：核对完整录像的原生 JSON 往返。')
                probe('bootstrap-v4',execute=True,native=native)
                roundtrip=read(destination/(last_attempt+'-source-execution.json'))
                if not roundtrip.get('loaded_from_json') or roundtrip['commands']!=full['native_replay']['cmd']:
                    raise RuntimeError('native JSON round-trip changed source commands')
                try:context['preparation_hint_saved']=save_hint(files,hint_initial,aligned,exact=hp_matched,roundtrip_verified=True)
                except (OSError,ValueError,KeyError,TypeError):context['preparation_hint_saved']=False
        else:
            from ability_search import search,search_with_hp_floor,terminal_hp_matches,fixed_choice_trial
            if locked_contract:
                from locked_seed_playback import configure as configure_locked
                aligned=configure_locked(aligned,locked_contract)
            rng_eligible=bool(search_reasons(aligned,read(source)))
            adaptive_mode=bool(mumu_enabled() and rng_eligible and not locked_contract and (not request.get('skill_target_test') or adaptive_test))
            if adaptive_test and not adaptive_mode:raise ValueError('adaptive native test is not eligible')
            selected_candidate={}
            candidate_records={}
            attempt_prefix=''
            def execute_candidate(candidate,number):
                nonlocal prep
                prep=preparation/(attempt_prefix+'ability-candidate-'+str(number)+'.json');write_new(prep,candidate)
                name=(attempt_prefix+'candidate-'+str(number)) if attempt_prefix else ('bootstrap-v3' if number==0 else 'ability-candidate-'+str(number))
                if not attempt_prefix:
                    if request.get('skill_target_test',{}).get('schema')=='royale-replay.free-skill-checkpoint.v1':
                        status('simulating','自由技能检查点候选 '+str(number+1)+'；当前种子 '+str(candidate['initialization_only']['rndSeed'])+'，检查2:20塔血，不固定技能。')
                    elif locked_contract:status('simulating','固定种子 '+str(locked_contract['random_seed'])+'，完整技能分支 '+str(number+1)+'；复核已验证前缀，再比较后续技能。')
                    elif adaptive_mode:status('simulating','反馈寻优候选 '+str(number+1)+'，种子 '+str(candidate['initialization_only']['rndSeed'])+'；各个种子分别探索技能，可恢复暂存分支。')
                    else:status('simulating','优先比较技能组合 '+str(number+1)+'；固定种子，保留六塔逐塔血差最小的完整对局，然后搜索随机种子。')
                candidate_receipt=probe(name,execute=True,candidate=True)
                selected_candidate.update(receipt=candidate_receipt,preparation=prep)
                candidate_records[str(prep)]=dict(selected_candidate)
                report=read(destination/(name+'-source-execution.json'))
                if locked_contract:
                    from locked_seed_playback import verify_execution as verify_locked
                    if verify_locked(report,locked_contract):context['checkpoint_prefix_verified']=True
                return report,dict(attempt=name,preparation=str(prep))
            skill_test=request.get('skill_target_test')
            if skill_test and skill_test.get('schema')=='royale-replay.free-skill-checkpoint.v1':
                if (skill_test.get('source_sha256')!=request['source_sha256'] or skill_test.get('checkpoint_tick')!=2800
                    or skill_test.get('owner')!=1 or skill_test.get('tower_slot')!=1 or skill_test.get('minimum_exclusive')!=2417):raise ValueError('自由技能检查点来源或目标不一致')
                aligned.update(ability_actor_names={},ability_target_choices={})
                from skill_checkpoint_search import search as checkpoint_search
                result=checkpoint_search(aligned,execute_candidate,cancelled=lambda:(destination/'stop-request.json').exists())
                write_new(destination/'skill-checkpoint-result.json',result)
                recovered=recover_failed_attempt(destination,last_attempt,identity)
                context.update(checkpoint_simulation_only=True,generation_released=recovered in ('restarted','already_released'))
                status('stopped','自由技能检查点预演已完成；发现 '+str(len(result['solutions']))+' 个2:20塔血大于2417的前缀。后续技能和整局尚未验证。',monitor_active=False)
                return
            if skill_test and not adaptive_test:
                if (skill_test.get('schema')!='royale-replay.skill-target-test.v1' or skill_test.get('source_sha256')!=request['source_sha256']
                    or skill_test.get('targets')!={'18':'golden-knight','24':'boss-bandit'}):raise ValueError('定向测试来源或技能约束不一致')
                for index in (18,24):
                    if index>=len(aligned['events']) or aligned['events'][index]['kind']!='activate_ability':raise ValueError('定向技能索引不是源技能')
                aliases={'golden-knight':{'goldenknight','championgoldenknight'},'boss-bandit':{'bossbandit','banditboss','championbossbandit'}}
                constraints={};observed=[]
                for audit_number in (250,251):
                    audit=copy.deepcopy(aligned);audit.update(ability_target_choices={},ability_actor_names=dict(constraints),prune_below_oracle=False)
                    audit_report,audit_evidence=execute_candidate(audit,audit_number)
                    observed+=audit_report.get('ability_observations',[])
                    write_new(destination/('skill-identity-audit-'+str(audit_number)+'.json'),dict(report=audit_report,evidence=audit_evidence))
                    for index,key in skill_test['targets'].items():
                        names={a['name'] for row in observed for a in row.get('actors',[]) if a.get('name','').lower() in aliases[key]}
                        if len(names)==1:constraints[index]=next(iter(names))
                    if len(constraints)==2:break
                if len(constraints)!=2:raise ValueError('未能从原生候选核实黄金圣骑与首领大盗名称；未猜测目标')
                aligned['ability_actor_names']=constraints
                write_new(destination/'skill-target-plan.json',dict(source_sha256=request['source_sha256'],targets=constraints,source_events_unchanged=True))
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
                def skill_difference(candidate,result):
                    _,difference=page_comparison(read(source),candidate,result)
                    if difference is None:raise ValueError('技能候选缺少可核验的逐塔血量')
                    return difference
                def skill_best(candidate,result,difference,evidence):
                    tier,_=page_comparison(read(source),candidate,result)
                    context.update(seed_search_active=True,ability_search_active=True,best_source_execution_verified=True,
                        best_page_match=tier,best_page_hp_difference=difference)
                    status('simulating','当前最优完整对局的逐塔血差 '+str(difference)+'；继续比较独立技能分支和符合条件的种子。可停止匹配并播放当前最优完整对局。')
                try:
                    if adaptive_mode:
                        from adaptive_skill_search import search as adaptive_search
                        def adaptive_prepare(seed,number):
                            nonlocal prep
                            trial=copy.deepcopy(delayed);trial['initialization_only']['rndSeed']=seed
                            trial.update(ability_actor_names={},ability_target_choices={},prune_below_oracle=True)
                            trial_seen=[]
                            for calibration in range(12):
                                trial_seen.append(deck_fingerprint(trial))
                                label='seed-'+str(number)+'-deal-'+str(calibration)
                                prep=preparation/(label+'.json');write_new(prep,trial)
                                deal=probe(label)
                                trial=calibrate(trial,deal,trial_seen)
                                if trial['native_deal_ready']:return trial
                            raise RuntimeError('adaptive seed deal calibration did not converge')
                        def adaptive_decision(value):
                            context.update(adaptive_search_active=True,adaptive_seed=value['seed'],
                                adaptive_action=value['action'],adaptive_decision=value['reason'])
                            status('simulating','反馈寻优：'+{'continue':'继续当前种子','new_seed':'尝试新种子','revisit':'恢复暂存种子'}[value['action']]
                                +' '+str(value['seed'])+'；'+value['reason']+'。')
                        def adaptive_snapshot(value):
                            write_search_snapshot(destination/'adaptive-search.json',dict(value,
                                source_sha256=request['source_sha256'],game_pid=identity['pid'],
                                game_start_time=identity['process_start_time']))
                        aligned,execution,search_result=adaptive_search(aligned,
                            retry_seed_plan(request['source_sha256'],source_seed,aligned['initialization_only']['rndSeed']),
                            adaptive_prepare,execute_candidate,
                            lambda candidate,result:terminal_hp_matches(read(source),candidate,result),skill_difference,
                            max_attempts=12 if adaptive_test else 128,max_seeds=2 if adaptive_test else 8,
                            max_seconds=420 if adaptive_test else 900,
                            cancelled=lambda:(destination/'stop-request.json').exists(),on_best=skill_best,
                            on_decision=adaptive_decision,on_snapshot=adaptive_snapshot,
                            stop_requested=lambda:best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity),
                            boundary_errors=(BestRequested,SearchBudgetExhausted))
                    else:
                        aligned,execution,search_result=(search_with_hp_floor if mumu_enabled() else search)(aligned,execute_candidate,
                            lambda candidate,result:terminal_hp_matches(read(source),candidate,result),
                            cancelled=lambda:(destination/'stop-request.json').exists(),score=skill_difference,on_best=skill_best,
                            stop_requested=lambda:best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity),
                            boundary_errors=(BestRequested,SearchBudgetExhausted))
                except Exception as error:
                    if hasattr(error,'search_report'):write_new(destination/'ability-search.json',error.search_report)
                    if adaptive_test and hasattr(error,'search_report'):
                        write_new(destination/'adaptive-test-result.json',dict(simulation_test_completed=True,full_source_completed=False,
                            source_sha256=request['source_sha256'],search_report=error.search_report,scene_published=False))
                        recovered=recover_failed_attempt(destination,last_attempt,identity)
                        context.update(adaptive_simulation_only=True,generation_released=recovered in ('restarted','already_released'))
                        status('stopped','反馈调度原生测试已完成；本轮未获得完整结果，未发布播放画面。',monitor_active=False)
                        return
                    if skill_test and not adaptive_test:write_new(destination/'skill-target-result.json',dict(simulation_test_completed=True,full_source_completed=False,
                        source_sha256=request['source_sha256'],targets=constraints,error=str(error),search_report=getattr(error,'search_report',None),scene_published=False))
                    raise
                write_new(destination/'ability-search.json',search_result)
                if adaptive_test:
                    write_new(destination/'adaptive-test-result.json',dict(simulation_test_completed=True,full_source_completed=True,
                        source_sha256=request['source_sha256'],search_report=search_result,scene_published=False))
                    recovered=recover_failed_attempt(destination,last_attempt,identity)
                    context.update(adaptive_simulation_only=True,generation_released=recovered in ('restarted','already_released'))
                    status('stopped','反馈调度原生测试已完成；完整候选和暂存分支已保留，未发布播放画面。',monitor_active=False)
                    return
                selected_candidate.clear();selected_candidate.update(candidate_records[search_result['selected_evidence']['preparation']])
                context.update(ability_search_active=False,seed_search_active=False,
                    adaptive_search_active=False,
                    skill_search_hp_difference=search_result['selected_hp_difference'],
                    skill_search_attempts=len(search_result['attempts']),skill_search_stopped_by_user=search_result['stopped_by_user'])
                fixed_skills=copy.deepcopy(aligned.get('ability_target_choices',{}))
                fixed_actor_names={str(row['event_index']):row['actors'][row['selected_ordinal']]['name'] for row in execution.get('ability_observations',[])
                    if row.get('phase')=='selected' and 0<=row.get('selected_ordinal',-1)<len(row.get('actors',[])) and row['actors'][row['selected_ordinal']].get('name')}
                if skill_test:
                    tier,difference=page_comparison(read(source),aligned,execution)
                    actual={key:fixed_actor_names.get(key) for key in constraints}
                    if actual!=constraints:raise ValueError('定向技能的原生实际对象不符合约束')
                    write_new(destination/'skill-target-result.json',dict(simulation_test_completed=True,full_source_completed=True,
                        source_sha256=request['source_sha256'],targets=constraints,actual_targets=actual,page_match=tier,page_hp_difference=difference,
                        hp_floor_violation=execution.get('hp_floor_violation'),floor_fallback_used=search_result.get('floor_fallback_used',False),
                        retained_events=len(aligned['events']),selected_evidence=search_result['selected_evidence'],scene_published=False))
                    recovered=recover_failed_attempt(destination,last_attempt,identity)
                    context.update(targeted_simulation_only=True,generation_released=recovered in ('restarted','already_released'))
                    status('stopped','指定技能的原生预演测试已完成；未发布播放画面。详细结果和塔血越界记录已保留。',monitor_active=False)
                    return
                # Always compare the simulated end with the page (the search only does so for ambiguous abilities).
                tier,difference=page_comparison(read(source),aligned,execution)
                initial_seed=aligned['initialization_only']['rndSeed'];original_seed=source_seed
                reasons=search_reasons(aligned,read(source))
                side_known=all(all(d['oracle_final_hp'][key]>0 for key in ('princess0','princess1')) for d in read(source)['decks'])
                context.update(seed_search_eligible=bool(reasons),seed_search_reasons=reasons,
                    tower_comparison_basis='per-owner-native-spawn-order-and-survivors-v2',destroyed_princess_side_verified=side_known)
                seed_report=dict(search_policy='best-six-tower-skills-then-eligible-seeds-v2',fixed_ability_target_choices=fixed_skills,eligible=bool(reasons),trigger_reasons=reasons,
                    original_seed=original_seed,original_tier=tier if initial_seed==original_seed else None,
                    original_difference=difference if initial_seed==original_seed else None,initial_seed=initial_seed,
                    preparation_hint_used=hint_detail['used'],attempts=[],selected_seed=initial_seed)
                def rank(tier,difference,report):return (bool(report.get('hp_floor_violation')),difference if difference is not None else 1<<30,PAGE_MATCH_TIERS.index(tier))
                best=(rank(tier,difference,execution),initial_seed,tier,difference,(aligned,execution,search_result,dict(selected_candidate)))
                if tier!='exact' and reasons and not locked_contract and not adaptive_mode:
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
                            trial.update(ability_actor_names=fixed_actor_names,prune_below_oracle=True)
                            trial_seen=[]
                            for calibration in range(12):
                                trial_seen.append(deck_fingerprint(trial))
                                prep=preparation/('seed-'+str(number)+'-deal-'+str(calibration)+'.json');write_new(prep,trial)
                                deal=probe('seed-'+str(number)+'-deal-'+str(calibration))
                                trial=calibrate(trial,deal,trial_seen)
                                if trial['native_deal_ready']:break
                            else:raise RuntimeError('seed deal calibration did not converge')
                            attempt_prefix='seed-'+str(number)+'-'
                            trial,trial_execution,trial_search=fixed_choice_trial(trial,fixed_skills,execute_candidate,
                                lambda candidate,result:terminal_hp_matches(read(source),candidate,result))
                            trial_tier,trial_difference=page_comparison(read(source),trial,trial_execution)
                            return (rank(trial_tier,trial_difference,trial_execution),seed,trial_tier,trial_difference,
                                (trial,trial_execution,trial_search,dict(selected_candidate)))
                        finally:attempt_prefix=''
                    best,attempts,stopped=choose_trials(best,retry_seed_plan(request['source_sha256'],original_seed,initial_seed),evaluate_seed,
                        lambda:best_requested(destination/'accept-best-seed.json',request['source_sha256'],identity),progress,Cancelled)
                    seed_report.update(attempts=attempts,stopped_by_user=stopped)
                    context['seed_search_budget_exhausted']=any(row.get('budget_exhausted') for row in attempts)
                    seed_report['budget_exhausted']=context['seed_search_budget_exhausted']
                    context['seed_search_stopped_by_user']=stopped
                context['seed_search_active']=False
                if adaptive_mode:
                    seed_report.update(search_policy=search_result['policy'],fixed_ability_target_choices=None,
                        attempts=[dict(seed=s['seed'],executed=bool(s['complete']),difference=s['best_difference'],
                            candidates=s['visits'],remaining=len(s['pending'])) for s in search_result['seeds']
                            if s['visits'] and s['seed']!=search_result['seed_pool'][0]],
                        initial_seed=search_result['seed_pool'][0],decisions_file='adaptive-search.json',
                        stopped_by_user=search_result['stopped_by_user'],budget_exhausted=search_result['budget_exhausted'],
                        skill_choices_searched_independently_per_seed=True)
                    context.update(seed_search_stopped_by_user=search_result['stopped_by_user'],
                        seed_search_budget_exhausted=search_result['budget_exhausted'])
                elif locked_contract:seed_report.update(skipped_reason='user_selected_seed_locked',checkpoint_prefix_verified=True)
                elif tier=='exact':seed_report['skipped_reason']='initial_result_exact'
                elif not reasons:seed_report['skipped_reason']='no_hunter_play_or_identified_skeleton_king_ability'
                _,selected_seed,tier,difference,(aligned,execution,search_result,chosen)=best
                selected_candidate.clear();selected_candidate.update(chosen)
                if locked_contract:
                    from locked_seed_playback import verify_execution as verify_locked
                    if selected_seed!=locked_contract['random_seed'] or not verify_locked(execution,locked_contract):raise ValueError('selected full replay differs from locked seed/checkpoint')
                    write_new(destination/'seed-locked-selection.json',dict(source_sha256=request['source_sha256'],random_seed=selected_seed,
                        checkpoint_prefix_verified=True,checkpoint_hps=locked_contract['checkpoint_hps'],selected_tier=tier,selected_difference=difference,
                        full_source_completed=True,selected_evidence=search_result['selected_evidence']))
                seed_report.update(selected_seed=selected_seed,selected_tier=tier,selected_difference=difference)
                hp_matched=tier=='exact'
                write_new(destination/'seed-search.json',seed_report)
                receipt=selected_candidate['receipt'];prep=selected_candidate['preparation']
                context['ability_target_inferred']=search_result['inferred']
                context['hp_floor_fallback_used']=bool(execution.get('hp_floor_violation'))
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
            elif context.get('page_match')=='same_towers':ready_message='胜负和各方毁塔数量与网页一致，逐塔血差合计 '+str(context.get('page_hp_difference'))+time_note(context)+elixir_note(context)+'；已试 '+str(context.get('seed_attempts',0))+' 个随机种子。不符合搜索条件的对局直接跳过搜索。'
            elif context.get('page_match')=='same_winner':ready_message='胜负与网页一致，但各方毁塔数量不同（已试 '+str(context.get('seed_attempts',0))+' 个随机种子）；仍可播放，过程与原局不同。'
            elif not context.get('final_hp_matched'):ready_message='全部指令已执行，但终局与网页不符（已另试 '+str(context.get('seed_attempts',0))+' 个随机种子）；仍可播放，过程可能与原局不同。'
            elif context.get('random_seed_inferred'):ready_message='换用随机种子后战报塔血一致；原种子未知，毁塔侧未核定，过程为推断。等待打开游戏。'
            else:ready_message='全部指令及 JSON 核验通过，双方国王塔和剩余公主塔血量与战报一致；毁塔侧未核定。等待悬浮进度卡就绪并打开游戏。'
            if context.get('seed_search_budget_exhausted'):ready_message+=' 已达到本场安全准备上限，保留已完整验证的最佳结果。'
            if context.get('hp_floor_fallback_used'):ready_message+=' 所有首轮可达分支均未满足塔血下限；当前为获准的最小半程差分支续算结果，不是精确还原。'
            if context.get('page_match_breakdown') is not None:ready_message+=context['page_match_detail']
            ready_message+=context.get('version_check_hint','')
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
    except Cancelled as error:
        status('cancelled','已在安全边界取消本机准备；没有重复发布原生任务。原因：'+str(error),monitor_active=False,cancellation_reason=str(error))
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
