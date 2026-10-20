"""Local HTML player orchestration. No browser, emulator creation or network setup.

All native work uses the existing audited scripts/immutable receipts. A failed
native task is never retried automatically. Stop only restarts an exactly owned
local replay process, after a new read-only ownership/generation check.
"""
import platform_lock as fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import time
import uuid

from client_session import ReadOnlySession, current_device_binding,ensure_current_device_binding
from finalize_replay import finalize
from scene_start_contract import require_idle_lobby
from timing_policy import offset_for, recipe_for
from replay_content_cache import content_digest
from replay_lifecycle import ClientUnavailable,client_generation
from tower_profiles import tower_key
from align_native_deal import calibrate,deck_fingerprint
from saved_replay import remember
from failure_recovery import explanation

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent/'vendor'
STORE = ROOT / 'console-runs'
PACKAGE = 'com.tencent.tmgp.supercell.clashroyale'
ACTIVITY = PACKAGE + '/com.supercell.titan.tencent.GameAppTencent'
AUDITED_SHA = 'c6b2482a2f1fbd2e15c99df7fb18ba3d5596b77b3a81930d3638241a3c37fe55'
MASK = 0x00ffffffffffffff
RECIPE_FILES = ('import_replay.py', 'prepare_native_replay.py', 'align_native_deal.py',
                'bootstrap_input.py', 'source_execution.h', 'native_bootstrap_probe.cpp',
                'finalize_replay.py', 'cache_lease.h','tower_profiles.py','native_tower_check.h','observe_tower_catalog.py',
                'portable_config.py','platform_lock.py','native_expression.py','mapped_elf.py','binary_read_transport.py','mumu_bridge_guest.cpp','mumu_bridge_host.cpp',
                'mumu_compile.py','mumu_lifecycle.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    with Path(path).open('x',encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def recipe_digest():
    values = [(name, digest(ROOT / name)) for name in RECIPE_FILES]
    values.append(('html-parser', digest(PROJECT / 'native_runner/tools/royaleapi_hog_il.py')))
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def receipt_ok(doc, *, scene=False, execution=False):
    if doc.get('errors') or not doc.get('detached'):
        reason='；'.join(map(str,doc.get('errors',[]))) or '调试器未确认分离'
        cleanup='组件已安全卸载' if doc.get('component_unloaded') and doc.get('detached') else '现场保留，需安全释放后再播放'
        raise RuntimeError('回放未启动：'+reason+'；'+cleanup+'。不会自动重试。')
    if scene:
        if not doc.get('native_replay_scene_present') or doc.get('local_driver', {}).get('error'):
            raise RuntimeError('回放场景未就绪；没有把加载成功当作播放成功。')
    else:
        from portable_config import translated
        from mumu_lifecycle import released
        if not doc.get('source_bootstrap_verified') or not (doc.get('component_unloaded') or translated() and released(doc)):
            raise RuntimeError('原生初始化/清理没有完成；保留现场并停止。')
    if execution and not doc.get('private_source_execution_complete'):
        raise RuntimeError('存在未执行的原始指令，拒绝生成不完整回放。')


def validate_cache(record, html_sha, recipe):
    """Never trust a filename/cache hit without its hashes and clean evidence."""
    if (record.get('source_sha256'), record.get('recipe'), record.get('library_sha256')) != (html_sha, recipe, AUDITED_SHA):
        raise ValueError('cache generation differs')
    paths = {}
    for name in ('preparation', 'native_replay', 'execution', 'receipt', 'roundtrip', 'roundtrip_receipt'):
        item = record[name]; path = Path(item['path'])
        if digest(path) != item['sha256']:
            raise ValueError('cached artifact changed: ' + name)
        paths[name] = path
    prep, native = read_json(paths['preparation']), read_json(paths['native_replay'])
    expected = finalize(prep, read_json(paths['execution']), read_json(paths['receipt']))
    if prep['source_sha256'] != html_sha or native['native_replay'] != expected['native_replay']:
        raise ValueError('cached replay differs from executed source')
    check = read_json(paths['roundtrip']); receipt = read_json(paths['roundtrip_receipt'])
    receipt_ok(receipt, execution=True)
    if check['commands'] != native['native_replay']['cmd'] or not check.get('loaded_from_json'):
        raise ValueError('native round-trip changed commands')
    return paths


def register_cache(prep, native, execution, receipt, roundtrip, roundtrip_receipt, directory=STORE, *, recipe=None):
    record = dict(source_sha256=read_json(prep)['source_sha256'], recipe=recipe or recipe_digest(), library_sha256=AUDITED_SHA)
    for name, path in dict(preparation=prep, native_replay=native, execution=execution,
                           receipt=receipt, roundtrip=roundtrip, roundtrip_receipt=roundtrip_receipt).items():
        record[name] = dict(path=str(Path(path).resolve()), sha256=digest(path))
    validate_cache(record, record['source_sha256'], record['recipe'])
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ('cache-' + record['source_sha256'] + '-' + record['recipe'][:16] + '.json')
    if not destination.exists():
        write_new(destination, record)
    return destination


def find_content_cache(source, recipe, directory=None):
    """Exact parsed-content alias, never a tag-only or stale-HTML cache hit."""
    directory=STORE if directory is None else Path(directory)
    requested=content_digest(source)
    candidates=sorted(directory.glob('cache-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for index in candidates[:4096]:
        try:
            record=read_json(index)
            if record.get('recipe')!=recipe or record.get('library_sha256')!=AUDITED_SHA:continue
            prep_path=Path(record['preparation']['path'])
            if digest(prep_path)!=record['preparation']['sha256']:continue
            prep=read_json(prep_path);canonical_path=prep_path.parent/'source.json'
            if digest(canonical_path)!=prep['source_manifest_sha256']:continue
            canonical=read_json(canonical_path)
            if canonical['source_sha256']!=record['source_sha256']:continue
            if content_digest(canonical)!=requested:continue
            if digest(prep_path.parent/'source.html')!=canonical['source_sha256']:continue
            paths=validate_cache(record,record['source_sha256'],recipe)
            return paths,dict(kind='identical-full-parsed-replay',content_sha256=requested,
                              displayed_html_sha256=source['source_sha256'],
                              canonical_html_sha256=canonical['source_sha256'],cache_index=str(index),
                              canonical_evidence_relabelled=False)
        except (ValueError,KeyError,OSError,RuntimeError):
            continue
    return None,None


def allocate_attempt(scene=False):
    """Reservations survive a failed build and prevent reuse by other consoles."""
    prefix = 'scene-v' if scene else 'bootstrap-v'
    for number in range(1 if scene else 2, 100000):
        name = prefix + str(number)
        if any(ROOT.glob(name + '-*.json')) or (ROOT / ('build-' + name if scene else 'build-v' + str(number))).exists():
            continue
        try:
            with (ROOT / (name + '-console-reservation.json')).open('x',encoding='utf-8') as f:
                json.dump({'console_pid': os.getpid()}, f)
            return name
        except FileExistsError:
            continue
    raise RuntimeError('没有可用的独立运行编号')


def scene_metadata(attempt):
    binding = read_json(ROOT / (attempt + '-binding.json'))
    prep = Path(binding['preparation_path'])
    full = prep.parent / 'complete-native.json'
    source = prep.parent / 'source.json'
    if digest(prep) != binding['preparation_sha256'] or digest(full) != binding['native_replay_sha256']:
        raise ValueError('existing scene input hashes differ')
    native = read_json(full); doc = read_json(source)
    if native['source_sha256'] != doc['source_sha256'] or doc['source_sha256'] != binding['source_html_sha256']:
        raise ValueError('existing scene source differs')
    if native['native_accepted_events'] != binding['source_event_count'] or len(native['native_replay']['cmd']) != binding['source_event_count']:
        raise ValueError('existing scene command count differs')
    if native.get('diagnostic_only') is True:
        preview=native['diagnostic_preview']
        doc=dict(doc,diagnostic_preview=preview)
        return doc,dict(attempt=attempt,duration=preview['stop_tick']/20,speed=binding['playback_speed'],
                        diagnostic_only=True,complete_replay_verified=False,
                        preview_event_count=preview['preview_event_count'],original_source_event_count=preview['original_source_event_count'])
    return doc, dict(attempt=attempt, duration=native['native_terminal_tick']/20, speed=binding['playback_speed'])


def owned_scene_state(attempt, *, allow_transition=False):
    """Strict read-only proof before a client-only Stop. No loose PID matching."""
    if not re.fullmatch(r'scene-v[1-9][0-9]*', attempt):
        raise ValueError('invalid scene identifier')
    binding = read_json(ROOT / (attempt + '-binding.json'))
    result = read_json(ROOT / (attempt + '-result.json'))
    comp = read_json(ROOT / (attempt + '-component.json'))
    identity = binding['identity']; s = ReadOnlySession(identity)
    maps = s.verify()
    def pointer(address):
        return struct.unpack('<Q', s.read(address, 8))[0]
    def integer(address):
        return struct.unpack('<i', s.read(address, 4))[0]
    manager = pointer(s.base + 0x1d46bd0)
    controller = pointer(manager + 0x28)
    expected = result.get('fields', [])
    if len(expected) != 48 or expected[5] != 1 or not expected[27] or controller != expected[27]:
        raise ValueError('当前画面不是本工具拥有的回放；保持客户端不变。')
    if pointer(s.base + 0x1d34ae0) != int(binding['root_raw'], 0) or pointer(int(binding['root_raw'], 0) + 0x20) != int(binding['services_raw'], 0):
        raise ValueError('客户端资源代际改变')
    rows = [v.split() for v in maps.splitlines() if len(v.split()) >= 6 and v.split()[-1] == comp['device_path']]
    table = pointer(controller) & MASK
    # The cloned table lives in the owned heap object, NOT in the .so. Only
    # its two private callbacks point into this exact component's executable map.
    original = struct.unpack('<128Q', s.read(s.base + 0x1bebd08, 128 * 8))
    cloned = struct.unpack('<128Q', s.read(table, 128 * 8))
    slots = (0x68 // 8, 0x78 // 8)
    table_owned = all(cloned[i] == original[i] for i in range(128) if i not in slots)
    table_owned = table_owned and all(any(int(v[0].split('-')[0], 16) <= (cloned[i] & MASK) < int(v[0].split('-')[1], 16)
                                        and 'x' in v[1] for v in rows) for i in slots)
    from portable_config import translated
    if translated():
        from mapped_elf import load_bias
        from elf_contract import Elf
        raw=Path(comp['local_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=comp['sha256']:raise ValueError('回放组件文件已改变')
        remote=subprocess.check_output(s.adb+['shell','sha256sum',comp['device_path']],text=True,timeout=10).split()[0]
        if remote!=comp['sha256']:raise ValueError('设备回放组件已改变')
        image=Elf(raw);module=load_bias(maps.splitlines(),comp['device_path'],image)
        table_owned=all(cloned[i]==original[i] for i in range(128) if i not in slots)
        for slot,name in zip(slots,('_ZN12_GLOBAL__N_111local_frameEPvf','_ZN12_GLOBAL__N_112local_renderEPvf')):
            va,size=image.object_symbol(name,kind=2);address=module+va
            if cloned[slot]&MASK!=address or s.read(address,size)!=image.at(va,size):table_owned=False
    domain = pointer(controller + 0x90)
    loading=bool(allow_transition and expected[3]==6 and integer(controller+0x30)==0
                 and domain and integer(domain+0x20)==0 and not pointer(controller+0x50))
    if not table_owned or integer(controller + 0x58) != 1 or not domain or (integer(domain + 0x20) != 4 and not loading):
        raise ValueError('不是已绑定的本地回放控制器')
    auxiliary = pointer(manager + 0x20)
    if (auxiliary and not allow_transition) or integer(manager + 0x3c):
        raise ValueError('场景正在切换，请稍后停止')
    tick = integer(domain + 0x60)
    status = subprocess.check_output(s.adb + ['shell', f'cat /proc/{s.pid}/status'], text=True, timeout=10)
    if any(line.startswith('TracerPid:') and line.split()[1] != '0' for line in status.splitlines()):
        raise ValueError('原生步骤尚未脱离调试器，不中断它')
    s.verify()
    return dict(attempt=attempt, identity=identity, controller=hex(controller), tick=tick, serial=identity['serial'],
                state=integer(controller + 0x30), scene=hex(pointer(controller + 0x50)), auxiliary=hex(auxiliary))


class Cancelled(Exception):
    pass


class Player:
    def __init__(self, emit=lambda *args: None):
        self.emit = emit; self.cancel = threading.Event(); self.active = None
        STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.folder = None
        self.last_device_serial = None
        self.last_attempt = None

    def recover_failed(self, error):
        """Restart only a detached, bound failed attempt in this exact game.

        No retries, module unloading, global ADB reset or foreign-battle stop.
        Unknown/pending debugger state remains a visible manual-recovery case.
        """
        if self.folder is None:self.new_folder()
        stale_failure=False
        if not self.last_attempt:
            observation=read_json(self.observation())
            session=ReadOnlySession(observation['identity']);maps=session.verify()
            for file in sorted(ROOT.glob('scene-v*-component.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                component=read_json(file);name=file.name.removesuffix('-component.json')
                if component['device_path'] not in maps:continue
                bound=read_json(ROOT/(name+'-binding.json'))['identity']
                current=observation['identity']
                if any(bound.get(k)!=current.get(k) for k in ('pid','process_start_time','serial','library_sha256')):continue
                failures=[read_json(path) for path in ROOT.glob(name+'-*-result.json')]
                if not any(r.get('detached') and r.get('errors') for r in failures):continue
                self.last_attempt=name;stale_failure=True;break
            if not self.last_attempt:return False
        attempt = self.last_attempt
        binding = read_json(ROOT/(attempt+'-binding.json'))
        comp = read_json(ROOT/(attempt+'-component.json'))
        result = read_json(ROOT/(attempt+'-result.json'))
        if not stale_failure and not result.get('errors') and (binding.get('scene') or not binding.get('source_execution') or result.get('private_source_execution_complete')):
            return False
        if not result.get('detached'):
            raise RuntimeError('调试器尚未确认退出，未自动重启客户端')
        if result.get('component_unloaded'):
            return False  # Already clean; avoid an unnecessary cold start.
        session = ReadOnlySession(binding['identity'])
        maps = session.verify()
        if not any(len(row.split())>=6 and row.split()[-1]==comp['device_path'] for row in maps.splitlines()):
            raise RuntimeError('无法确认失败组件归属，未自动关闭游戏')
        if binding.get('scene'):
            try:
                owned_scene_state(attempt)
            except (ValueError,RuntimeError):
                # A reconnect can replace the public resource manager inside
                # the SAME PID. Do not unload its borrowed old graph. A strict
                # idle lobby plus this exact detached mapped owner permits the
                # user-authorized client-only restart, never a foreign battle.
                observation=read_json(self.observation())
                identity=observation['identity']
                if any(identity.get(k)!=binding['identity'].get(k) for k in ('pid','process_start_time','serial','library_sha256')):
                    raise RuntimeError('新客户端不继承旧现场，未关闭它')
                status=subprocess.check_output(session.adb+['shell',f'cat /proc/{session.pid}/status'],text=True,timeout=10)
                if not any(line.startswith('TracerPid:') and line.split()[1]=='0' for line in status.splitlines()):raise RuntimeError('仍有调试器占用')
                session.verify()
                subprocess.run(session.adb+['shell','am','force-stop',PACKAGE],check=True,timeout=15,capture_output=True)
                self.active=None
                subprocess.run(session.adb+['shell','am','start','-n',ACTIVITY],check=True,timeout=20,capture_output=True)
            else:
                self.active = attempt
                self.stop_owned()
        else:
            observation = self.observation()  # Strict idle lobby, no foreign battle.
            if read_json(observation)['identity'] != binding['identity']:
                raise RuntimeError('客户端代际已改变，未关闭新进程')
            status = subprocess.check_output(session.adb+['shell',f'cat /proc/{session.pid}/status'],text=True,timeout=10)
            if not any(line.startswith('TracerPid:') and line.split()[1]=='0' for line in status.splitlines()):
                raise RuntimeError('客户端仍有调试器占用，未强制关闭')
            session.verify()
            subprocess.run(session.adb+['shell','am','force-stop',PACKAGE],check=True,timeout=15,capture_output=True)
            self.active = None
            subprocess.run(session.adb+['shell','am','start','-n',ACTIVITY],check=True,timeout=20,capture_output=True)
        self.emit('recovered', explanation(error)+' 已清除本次失败进程并重新打开游戏；请等待大厅就绪后选择回放。未自动重试。')
        self.last_attempt = None
        return True

    def stage(self, text):
        self.emit('status', text); self.emit('log', text)

    def checkpoint(self):
        if self.cancel.is_set():
            raise Cancelled('已取消；已经提交的原生步骤已安全结束。')

    def command(self, script, *args, native=False):
        # A native task must finish/detach; cancellation is checked AFTER it.
        self.checkpoint()
        from portable_config import config
        command = [config().get('python',sys.executable), '-u', str(ROOT / script), *map(str, args)]
        identity=None
        if native and '--attempt' in args:
            attempt=str(args[args.index('--attempt')+1]);identity=read_json(ROOT/(attempt+'-binding.json'))['identity']
        logfile = self.folder / (f'{time.time_ns()}-{Path(script).stem}.log')
        self.emit('log', '执行：' + Path(script).stem)
        with logfile.open('x',encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started = time.monotonic(); warned = False;last_liveness=0
            while process.poll() is None:
                time.sleep(.2)
                now=time.monotonic()
                if identity and now-last_liveness>=1:
                    last_liveness=now;state=client_generation(identity)
                    if state in ('closed','replaced'):
                        # The target generation is gone: there is no native
                        # task left to interrupt. Reap only our helper tree.
                        if os.name=='nt':
                            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=5)
                        else:process.terminate()
                        self.active=None
                        raise ClientUnavailable('游戏客户端已关闭；已退出本轮回放，不会重发原生任务。')
                if not native and now-started>45:
                    process.kill();process.wait(timeout=5)
                    raise RuntimeError('本地准备步骤超时，已结束等待；没有提交游戏任务。')
                if not warned and time.monotonic() - started > 45:
                    self.emit('log', '此步骤仍在进行，日志持续保存；不会重复提交。'); warned = True
                # Existing scripts own timeouts and native handles. Never kill a
                # published task even if the GUI is closed/cancelled.
            output = logfile.read_text(encoding='utf-8',errors='replace')
        self.emit('log', output[-5000:].strip())
        if process.returncode:
            raise RuntimeError(output[-2400:] or f'步骤失败：{script}')
        if not native:
            self.checkpoint()

    def new_folder(self):
        self.folder = STORE / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        self.folder.mkdir(mode=0o700); self.emit('run', str(self.folder))

    def discover_owned(self):
        device=ensure_current_device_binding()
        adb=['adb','-s',device['serial']]
        found=subprocess.run(adb+['shell','pidof',PACKAGE],capture_output=True,text=True,timeout=10)
        if found.returncode==1 and not found.stdout.strip():return None
        if found.returncode or len(found.stdout.split())!=1:raise RuntimeError('无法确认唯一游戏进程')
        pid=int(found.stdout.strip())
        stat=subprocess.check_output(adb+['shell','cat',f'/proc/{pid}/stat'],text=True,timeout=10)
        start=stat[stat.rfind(')')+2:].split()[19]
        for file in sorted(ROOT.glob('scene-v*-result.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            name = file.name.removesuffix('-result.json')
            if not re.fullmatch(r'scene-v[1-9][0-9]*', name):
                continue
            try:
                identity=read_json(ROOT/(name+'-binding.json'))['identity']
                if (identity.get('serial'),identity.get('pid'),identity.get('process_start_time'))!=(device['serial'],pid,start):continue
                state = owned_scene_state(name)
            except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError):
                continue
            self.active = name
            return state
        return None

    def stop_owned(self):
        if self.folder is None:
            self.new_folder()
        if not self.active and not self.discover_owned():
            raise RuntimeError('未发现本工具拥有的回放；不会停止其他游戏或训练。')
        binding=read_json(ROOT/(self.active+'-binding.json'))
        generation=client_generation(binding['identity'])
        if generation in ('closed','replaced'):
            self.active=None;raise ClientUnavailable('客户端已关闭，已退出回放。')
        state = owned_scene_state(self.active)  # immediate proof, not stale UI state
        write_new(self.folder / ('stop-intent-' + str(time.time_ns()) + '.json'), state)
        self.stage('停止本地回放：仅重启它所在的游戏客户端，不重启安卓1。')
        adb = ['adb', '-s', state['serial']]
        subprocess.run(adb + ['shell', 'am', 'force-stop', PACKAGE], check=True, timeout=15)
        self.active = None
        write_new(self.folder / ('stopped-owned-scene-' + str(time.time_ns()) + '.json'), state)
        try:
            start_adb=['adb','-s',ensure_current_device_binding()['serial']]
            subprocess.run(start_adb + ['shell', 'am', 'start', '-n', ACTIVITY], check=True, timeout=20,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.SubprocessError as exc:
            self.emit('stopped', '本地回放已停止，但重新打开游戏失败。请自行打开原客户端。')
            raise RuntimeError('本地回放已停止；重新打开游戏失败：' + str(exc)) from exc
        self.emit('stopped', '回放已停止，游戏客户端已重新打开。请保持在大厅。')

    def finish_owned(self):
        """Terminal-only release/reopen fallback; direct Home reconstruction is unsafe."""
        if not self.active:return
        attempt=self.active
        current=owned_scene_state(attempt)
        _,metadata=scene_metadata(attempt)
        if metadata.get('diagnostic_only') or current['tick']/20<metadata['duration']:
            raise RuntimeError('尚未完成的回放不能当作终局自动退出')
        self.stage('回放终局：安全释放本地现场并自动重新打开客户端；当前不是免重启返回。')
        self.stop_owned()  # Fresh identity/table proof; only this owned client.
        self.last_attempt=None
        deadline=time.monotonic()+45;ready=False
        while time.monotonic()<deadline:
            try:self.observation();ready=True;break
            except (ValueError,RuntimeError):time.sleep(1)
        self.emit('lobby-ready','游戏已自动重新打开'+('并确认回到大厅。' if ready else '，请等待启动加载或登录。')+'客户端使用安全重启兜底；可选择下一场。')
        return dict(client_reopened=True,lobby_verified=ready,seamless=False)
        self.command('observe_current_client.py', '--output', path)
        doc = read_json(path)
        serial=doc['identity']['serial']
        if serial!=self.last_device_serial:
            self.emit('log','已自动连接我的安卓-1：'+serial+'；客户端身份重新核验，不沿用旧进程地址。')
            self.last_device_serial=serial
        state = doc['scene_state']
        if (state.get('kind'), state.get('state'), state.get('domain_mode'), state.get('battle_present')) != (0, 9, 1, False):
            raise RuntimeError('请让已有安卓1进入大厅；其他对局不会被覆盖。')
        return path

    def observation(self):
        path = self.folder / ('client-' + str(time.time_ns()) + '.json')
        self.command('observe_current_client.py', '--output', path)
        doc = read_json(path)
        serial=doc['identity']['serial']
        if serial!=self.last_device_serial:
            self.emit('log','已自动连接我的安卓-1：'+serial+'；客户端身份重新核验，不沿用旧进程地址。')
            self.last_device_serial=serial
        state = doc['scene_state']
        if (state.get('kind'), state.get('state'), state.get('domain_mode'), state.get('battle_present')) != (0, 9, 1, False):
            raise RuntimeError('请让已有安卓1进入大厅；其他对局不会被覆盖。')
        return path

    def wait_lobby(self):
        self.stage('等待已有安卓1的游戏大厅；不修改网络或登录设置。')
        deadline = time.monotonic() + 90
        last = None
        while time.monotonic() < deadline:
            self.checkpoint()
            try:
                return self.observation()
            except (RuntimeError, ValueError) as exc:
                last = exc
                try:
                    adb=['adb','-s',ensure_current_device_binding()['serial']]
                    result=subprocess.run(adb+['shell','pidof',PACKAGE],capture_output=True,text=True,timeout=2)
                    if result.returncode==1 and not result.stdout.strip():raise ClientUnavailable('客户端已关闭，已退出等待大厅。')
                except (OSError,subprocess.SubprocessError):pass
            self.cancel.wait(3)
        raise RuntimeError('大厅尚未准备好，请自行完成登录后再次播放。' + str(last))

    def probe(self, prep, observation, *, execute=False, native=None, scene=False, speed=1, candidate=False):
        attempt = allocate_attempt(scene)
        args = ['--attempt', attempt, '--client-observation', observation, '--preparation', prep]
        if execute: args += ['--source-execution']
        if native: args += ['--native-replay', native]
        if scene: args += ['--scene', '--playback-speed', speed]
        self.command('build_bootstrap_probe.py', *args)
        self.command('deploy_bootstrap_probe.py', '--attempt', attempt)
        self.last_attempt = attempt
        self.command('run_bootstrap_probe.py', '--attempt', attempt, native=True)
        result_path = ROOT / (attempt + '-result.json'); result = read_json(result_path)
        if scene and result.get('fields', [0] * 48)[5]:
            self.active = attempt
            write_new(self.folder / 'owned-scene.json', dict(attempt=attempt, receipt=str(result_path)))
        if scene and self.active == attempt and not result.get('errors') and result.get('detached') and not result.get('native_replay_scene_present'):
            # Start can detach during the normal state5 fade/resource load.
            # Observe the exact owned scene; NEVER submit the replay a second time.
            self.stage('原生场景已提交，等待资源加载和画面就绪；不会重复提交。')
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                self.checkpoint()
                state = owned_scene_state(attempt, allow_transition=True)
                if state['state'] == 9 and state['scene'] != '0x0' and state['auxiliary'] == '0x0':
                    for number in range(1, 10000):
                        receipt = attempt + '-observe-v' + str(number)
                        if not (ROOT / (receipt + '-result.json')).exists(): break
                    self.command('run_bootstrap_probe.py', '--attempt', attempt, '--action', 'observe', '--receipt', receipt, native=True)
                    result_path = ROOT / (receipt + '-result.json'); result = read_json(result_path)
                    break
                self.cancel.wait(1)
        if candidate:
            from mumu_lifecycle import released
            if (not result.get('detached') or not result.get('source_bootstrap_verified')
                    or not released(result)):
                receipt_ok(result, execution=True)
        else: receipt_ok(result, scene=scene, execution=execute and not scene)
        self.checkpoint()
        return attempt, result_path

    def play(self, html, speed=1):
        self.checkpoint(); self.new_folder()
        self.last_attempt = None
        path = Path(html).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in ('.html', '.htm'):
            raise ValueError('请选择已保存的 RoyaleAPI 回放 HTML 文件。')
        if not 0 < path.stat().st_size <= 25 * 1024 * 1024:
            raise ValueError('HTML 文件为空或超过25MB')
        raw = path.read_bytes(); html_sha = hashlib.sha256(raw).hexdigest()
        source_html = self.folder / 'source.html'
        with source_html.open('xb') as f: f.write(raw)
        self.stage('1/5 读取 HTML，保留全部下牌、技能、时间和坐标。')
        source = self.folder / 'source.json'
        self.command('import_replay.py', source_html, '--project-root', PROJECT, '--output', source)
        doc = read_json(source)
        self.emit('saved', remember(STORE, source_html, doc))
        timing_ticks = offset_for(doc['replay_tag'])
        recipe = recipe_for(recipe_digest(), timing_ticks)
        doc['execution_timing_offset_seconds'] = timing_ticks / 20
        self.emit('match', doc)
        if timing_ticks:
            self.stage(f'全局时序规则：所有对局的下牌与技能统一延后 {timing_ticks / 20:g} 秒；不叠加旧单场延迟，原始 HTML 与终局规则不变，使用独立缓存。')
        if doc['unresolved_base_card_ids']:
            raise ValueError('当前适配器尚不支持这些卡牌，未替换或丢弃：' + ', '.join(doc['unresolved_base_card_ids']))
        for deck in doc['decks']:
            tower=deck.get('tower') or {}
            tower_key(tower.get('card_key'))
            if type(tower.get('level')) is not int or not 1<=tower['level']<=16:raise ValueError('需要明确且受当前客户端支持的塔楼等级（1至16级）。')
        cache = STORE / ('cache-' + html_sha + '-' + recipe[:16] + '.json')
        cached = None
        if cache.exists():
            try:
                cached = validate_cache(read_json(cache), html_sha, recipe)
                cached_offset = read_json(cached['preparation']).get('execution_timing', {}).get('offset_ticks', 0)
                if cached_offset != timing_ticks:
                    raise ValueError('cached execution timing differs from selected A/B')
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                cached = None
                self.emit('log', '缓存校验未通过，本轮重新生成：' + str(exc))
        if cached is None:
            cached, reuse = find_content_cache(doc, recipe)
            if cached:
                cached_offset=read_json(cached['preparation']).get('execution_timing',{}).get('offset_ticks',0)
                if cached_offset!=timing_ticks:
                    cached=None
                else:
                    write_new(self.folder/'cache-reuse.json',reuse)
                    self.stage('同一场回放的全部指令、卡组、等级、形态、坐标及结果一致；复用已验证原生输入，不重复预演。')
        if self.discover_owned():
            self.stop_owned()
            observation = self.wait_lobby()
        else:
            self.stage('2/5 检查已有安卓1与官服客户端；仅允许大厅状态。')
            observation = self.wait_lobby()
        if cached:
            self.stage('3/5 命中已完整验证的回放缓存，跳过重复预演。')
            prep, native = cached['preparation'], cached['native_replay']
        else:
            self.stage('3/5 校准卡牌等级和初始牌序（首次导入需要准备）。')
            levels = self.folder / 'levels.json'; prep0 = self.folder / 'preparation-initial.json'
            self.command('observe_card_levels.py', '--observation', observation, '--source', source, '--output', levels)
            towers=self.folder/'towers.json'
            self.command('observe_tower_catalog.py','--observation',observation,'--output',towers)
            self.command('prepare_native_replay.py', source, '--level-evidence', levels,'--tower-evidence',towers, '--output', prep0)
            if timing_ticks:
                shifted = self.folder / 'preparation-timing.json'
                self.command('timing_policy.py', '--preparation', prep0, '--offset-ticks', timing_ticks, '--output', shifted)
                prep0 = shifted
            seen=[]
            for calibration in range(12):
                observed_prep=read_json(prep0);seen.append(deck_fingerprint(observed_prep))
                _, deal = self.probe(prep0, observation)
                aligned=calibrate(observed_prep,read_json(deal),seen)
                prep=self.folder/('preparation-calibrated-'+str(calibration)+'.json')
                write_new(prep,aligned)
                if aligned['native_deal_ready']:break
                self.stage('校准原生牌序：卡牌相关发牌规则需要额外初始化核验；尚未执行源指令。')
                prep0=prep
            else:raise RuntimeError('原生牌序未能在有界校准内匹配；初始化现场已安全释放，未执行回放指令。')
            self.stage('4/5 原生引擎完整预演，逐条核对全部指令，再校验导入。')
            from ability_search import search,terminal_hp_matches
            selected_evidence={}
            def execute_candidate(candidate,number):
                candidate_path=self.folder/('ability-candidate-'+str(number)+'.json')
                write_new(candidate_path,candidate)
                candidate_attempt,candidate_receipt=self.probe(candidate_path,observation,execute=True,candidate=True)
                evidence=dict(preparation=str(candidate_path),attempt=candidate_attempt,receipt=str(candidate_receipt))
                selected_evidence.update(evidence)
                return read_json(ROOT/(candidate_attempt+'-source-execution.json')),evidence
            try:
                from portable_config import translated
                chosen,report,search_result=search(read_json(prep),execute_candidate,
                    lambda candidate,result:terminal_hp_matches(doc,candidate,result),cancelled=self.cancel.is_set,
                    max_attempts=16 if translated() else 256)
            except Exception as error:
                if hasattr(error,'search_report'):write_new(self.folder/'ability-search.json',error.search_report)
                raise
            write_new(self.folder/'ability-search.json',search_result)
            if search_result['ambiguous']:
                self.stage('技能候选已找到终局塔血匹配；这是推断匹配，不是原始技能目标或过程唯一性证明。')
            prep=Path(selected_evidence['preparation'])
            attempt=selected_evidence['attempt'];receipt=Path(selected_evidence['receipt'])
            execution = ROOT / (attempt + '-source-execution.json'); native = self.folder / 'complete-native.json'
            self.command('finalize_replay.py', '--preparation', prep, '--report', execution, '--receipt', receipt, '--output', native)
            check_attempt, check_receipt = self.probe(prep, observation, execute=True, native=native)
            register_cache(prep, native, execution, receipt, ROOT / (check_attempt + '-source-execution.json'), check_receipt, recipe=recipe)
        self.checkpoint()
        self.stage('5/5 准备原生画面；画面将在已有安卓1窗口显示。')
        # Recheck immediately before publishing, not merely at import time.
        observation = self.observation()
        attempt, receipt = self.probe(prep, observation, execute=True, native=native, scene=True, speed=speed)
        self.emit('playing', dict(attempt=attempt, event_count=doc['retained_action_count'],
                                 duration=read_json(native)['native_terminal_tick'] / 20,
                                 speed=speed, receipt=str(receipt), timing_offset_seconds=timing_ticks / 20))


    def play_diagnostic(self,html,evidence,speed=1):
        from desktop_diagnostic import play
        return play(self,html,evidence,speed)


class OperationLock:
    def __enter__(self):
        STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
        from portable_config import operation_lock
        lockpath=operation_lock();lockpath.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.file = lockpath.open('a+b')
        try: fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('另一个控制台正在操作回放，请勿重复启动。')
        return self

    def __exit__(self, *args):
        self.file.close()
