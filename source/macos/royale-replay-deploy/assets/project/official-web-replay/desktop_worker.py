"""Line-delimited local JSON bridge for the native macOS window (no sockets)."""
import fcntl
import json
import os
import sys
import threading
import time
import traceback
import subprocess
from replay_queue import ReplayQueue
from console_backend import Cancelled, OperationLock, Player, STORE, PROJECT, owned_scene_state, scene_metadata
from browser_capture import save_capture
from bridge_queue import DIRECTORY as BRIDGE_DIRECTORY, pending_jobs, process_job, update_status
from saved_replay import selected, forget
from failure_recovery import explanation


class Worker:
    def __init__(self):
        self.output_lock = threading.Lock(); self.state_lock = threading.Lock()
        self.busy = False; self.playback = None; self.log = None
        self.stop_requested = threading.Event()
        self.bridge_current = None
        self.bridge_preparing = False
        self.closed = threading.Event(); self.player = Player(self.emit)
        self.queue = ReplayQueue(STORE)
        self.queue_active = None
        self.parse_lock = threading.Lock()

    def emit(self, kind, value):
        with self.output_lock:
            if kind == 'run': self.log = STORE / os.path.basename(value) / 'console.log'
            if kind in ('playing', 'resumed'): self.playback = value
            if kind == 'stopped': self.playback = None
            if kind in ('complete','error','recovered','stopped') and self.queue_active:
                self.queue.set_state(self.queue_active, 'complete' if kind=='complete' else 'failed', message=str(value))
                self.queue_active=None
            if self.bridge_current and ((kind == 'status' and self.bridge_preparing) or
                                        (kind in ('complete', 'stopped') and not self.bridge_preparing)):
                state = 'preparing' if kind == 'status' else 'complete' if kind == 'complete' else 'cancelled'
                message = str(value) if kind != 'complete' else '原生回放已经播放完毕。'
                try: update_status(BRIDGE_DIRECTORY, self.bridge_current, state, message)
                except OSError: pass
            if kind in ('status', 'log', 'error', 'stopped', 'cancelled') and self.log:
                with self.log.open('a') as f: f.write(time.strftime('[%H:%M:%S] ') + str(value) + '\n')
            try:
                print(json.dumps({'event': kind, 'value': value}, ensure_ascii=False), flush=True)
            except BrokenPipeError:
                self.closed.set(); self.player.cancel.set()

    def launch(self, action):
        with self.state_lock:
            if self.busy:
                self.emit('error', '当前步骤仍在进行，请等待或取消。'); return
            self.busy = True
        self.emit('busy', True)
        def run():
            try:
                with OperationLock(): action()
            except Cancelled as exc:
                self.emit('cancelled', str(exc))
            except Exception as exc:
                self.emit('log', traceback.format_exc())
                try:
                    recovered = self.player.recover_failed(exc)
                except Exception as recovery_error:
                    recovered = False
                    self.emit('log', '自动恢复未通过归属检查：'+str(recovery_error))
                if recovered: self.playback = None
                else: self.emit('error', str(exc)+'\n'+explanation(exc))
            finally:
                # A Stop received during adoption or the last native step must
                # not disappear merely because that step returned normally.
                while True:
                    with self.state_lock:
                        requested = self.stop_requested.is_set()
                        self.stop_requested.clear()
                        if not requested:
                            self.busy = False
                            break
                    if self.player.active:
                        try:
                            with OperationLock(): self.player.stop_owned()
                        except Exception as error: self.emit('error', str(error))
                self.emit('busy', False)
        threading.Thread(target=run, daemon=False).start()

    def adopt(self):
        state = self.player.discover_owned()
        if state:
            self.emit('adopted', state)
            try:
                doc, metadata = scene_metadata(state['attempt'])
                self.emit('match', doc); self.emit('resumed', metadata)
                self.emit('position', dict(state, duration=metadata['duration']))
                if state['tick']/20 >= metadata['duration']:
                    if metadata.get('diagnostic_only'):
                        self.emit('status','诊断预览已到分歧点暂停，不是完整回放。可检查画面或安全停止。')
                    else:
                        self.player.finish_owned()
                        self.emit('complete', metadata); self.playback = None
            except (ValueError, OSError, KeyError) as exc:
                self.emit('log', '已有回放仍保留；未恢复输入信息：' + str(exc))

    def command(self, doc):
        kind = doc.get('command')
        if kind == 'queue-add':
            paths=doc.get('htmls')
            if not isinstance(paths,list) or not 1<=len(paths)<=128 or any(not isinstance(p,str) for p in paths):
                raise ValueError('请选择1至128个HTML')
            def enqueue():
                for path in paths:
                    try:self.queue.add(path)
                    except Exception as error:self.emit('log','入队失败：'+str(error))
                self.emit('queue',self.queue.snapshot())
                self.parse_queued()
            threading.Thread(target=enqueue,daemon=True).start()
        elif kind == 'queue-next':
            if self.busy or self.playback:raise ValueError('请先等当前回放完成；不会覆盖正在播放的战斗')
            item=self.queue.next_ready()
            if item is None:raise ValueError('下一场尚未解析完成或队列为空')
            speed=doc.get('speed',1)
            if speed not in (.25,.5,1,2,4):raise ValueError('播放倍速不正确')
            def next_replay():
                path=self.queue.source(item['id'])
                self.queue.set_state(item['id'],'playing');self.queue_active=item['id']
                self.player.cancel.clear()
                evidence=self.queue.diagnostic(item['id'])
                if evidence:self.player.play_diagnostic(str(path),evidence,speed)
                else:self.player.play(str(path),speed)
                self.emit('queue',self.queue.snapshot())
            self.launch(next_replay)
        elif kind in ('capture-play', 'capture-save'):
            html, url, speed = doc.get('html'), doc.get('url'), doc.get('speed', 1)
            if not isinstance(html, str) or not isinstance(url, str) or speed not in (.25, .5, 1, 2, 4):
                raise ValueError('网页数据或倍速不正确')
            if self.busy:
                self.emit('error', '当前步骤仍在进行，请等待或取消。'); return
            self.player.cancel.clear()
            self.bridge_current = None
            def capture():
                self.emit('status', '校验当前网页并保存完整回放 HTML…')
                result = save_capture(html, url, project=PROJECT, directory=STORE/'web-html')
                self.emit('downloaded', result)
                if kind == 'capture-play':
                    if self.playback:
                        self.queue.add(result['path']);self.emit('queue',self.queue.snapshot())
                        self.emit('status','网页回放已入队，尚未播放；当前战斗保持不变。')
                        threading.Thread(target=self.parse_queued,daemon=True).start()
                    else:self.player.play(result['path'], speed)
                else: self.emit('status', 'HTML 已保存，可在控制台点击播放。')
            self.launch(capture)
        elif kind in ('play', 'replay-saved'):
            if kind == 'replay-saved':
                saved = selected(STORE, doc.get('source_sha256'))
                if saved is None: raise ValueError('没有已保存回放')
                doc = dict(doc, html=saved['path'])
            html, speed = doc.get('html'), doc.get('speed', 1)
            if not isinstance(html, str) or speed not in (.25, .5, 1, 2, 4):
                raise ValueError('文件或倍速不正确')
            if self.busy or self.playback:
                self.command(dict(command='queue-add',htmls=[html]))
                self.emit('status','新HTML已请求入队，尚未播放；不会覆盖当前战斗。')
                return
            if self.busy:
                self.emit('error', '当前步骤仍在进行，请等待或取消。'); return
            self.player.cancel.clear()
            self.bridge_current = None
            self.playback = None
            self.launch(lambda: self.player.play(html, speed))
        elif kind == 'remove-saved':
            def remove():
                if not isinstance(doc.get('source_sha256'), str): raise ValueError('需要确认保存的回放')
                forget(STORE, doc['source_sha256'])
                self.emit('saved', None)
                self.emit('status', '已移除保存选择；原 HTML、缓存和诊断记录仍保留。')
            self.launch(remove)
        elif kind == 'stop':
            with self.state_lock:
                running = self.busy
                if running:
                    self.stop_requested.set(); self.player.cancel.set()
            if running:
                self.emit('status', '已请求取消，等待当前原生步骤安全结束…')
            else:
                def stop():
                    self.player.new_folder(); self.player.stop_owned()
                self.launch(stop)
        elif kind == 'shutdown':
            self.closed.set(); self.player.cancel.set()
        else: raise ValueError('未知控制台操作')

    def parse_queued(self):
        # Separate pure parser, no native lock, debugger, ADB or simulation.
        with self.parse_lock:
            for row in self.queue.snapshot():
                if self.closed.is_set():return
                if row['state']!='queued':continue
                self.queue.set_state(row['id'],'parsing')
                self.emit('queue',self.queue.snapshot())
                try:
                    path=self.queue.source(row['id'])
                    output=path.with_suffix('.json')
                    subprocess.run([sys.executable,'-u',str(__import__('pathlib').Path(__file__).with_name('import_replay.py')),
                        str(path),'--project-root',str(PROJECT),'--output',str(output)],
                        check=True,timeout=60,capture_output=True)
                    parsed=json.loads(output.read_text(encoding='utf-8'))
                    if parsed['source_sha256']!=row['sha256']:raise ValueError('解析源哈希不符')
                    self.queue.set_state(row['id'],'ready',replay_tag=parsed['replay_tag'],count=parsed['retained_action_count'])
                except Exception as error:self.queue.set_state(row['id'],'failed',message=str(error))
                self.emit('queue',self.queue.snapshot())

    def monitor(self):
        while not self.closed.wait(7):
            if self.busy or not self.playback: continue
            current = self.playback
            try:
                state = owned_scene_state(current['attempt'])
                if self.playback is current:
                    self.emit('position', dict(state, duration=current['duration']))
                    if state['tick'] / 20 >= current['duration']:
                        if current.get('diagnostic_only'):
                            if not current.get('preview_paused'):
                                current['preview_paused']=True
                                self.emit('status','诊断预览已到分歧点暂停，不是完整回放。可检查画面或安全停止。')
                            continue
                        def finish():
                            self.player.finish_owned()
                            self.emit('complete', current);self.playback=None
                            self.emit('queue',self.queue.snapshot())
                        self.launch(finish)
            except Exception as exc:
                if self.busy: continue
                self.emit('log', '状态读取暂停：' + str(exc)); self.emit('status', '暂无法读取播放进度，请检查安卓1；未自动重启。')
                self.playback = None

    def bridge_monitor(self):
        while not self.closed.wait(1):
            if self.busy: continue
            jobs = pending_jobs()
            if not jobs: continue
            path = jobs[0]
            def action(path=path):
                queue_only=bool(self.playback)
                if not queue_only:self.bridge_current = path.stem
                self.bridge_preparing = True
                self.player.cancel.clear()
                try:
                    process_job(self.player,path,self.emit,enqueue=self.queue.add if queue_only else None)
                    if queue_only:
                        self.emit('queue',self.queue.snapshot())
                        threading.Thread(target=self.parse_queued,daemon=True).start()
                finally: self.bridge_preparing = False
            self.launch(action)


def main():
    os.umask(0o077)
    os.environ['PATH'] = os.environ.get('PATH', '') + ':/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin'
    STORE.mkdir(parents=True, exist_ok=True)
    lock = (STORE/'desktop.lock').open('a+')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({'event': 'fatal', 'value': '回放控制台已打开，请使用现有窗口。'}, ensure_ascii=False), flush=True); return
    worker = Worker(); worker.emit('ready', '就绪 · 请选择已保存的 RoyaleAPI 回放 HTML')
    try: worker.emit('saved', selected(STORE))
    except (ValueError, KeyError, OSError) as error: worker.emit('log', str(error))
    worker.emit('queue',worker.queue.snapshot())
    threading.Thread(target=worker.parse_queued,daemon=True).start()
    worker.launch(worker.adopt)
    threading.Thread(target=worker.monitor, daemon=True).start()
    threading.Thread(target=worker.bridge_monitor, daemon=True).start()
    try:
        for line in sys.stdin:
            try: worker.command(json.loads(line))
            except Exception as exc: worker.emit('error', str(exc))
            if worker.closed.is_set(): break
    finally:
        worker.closed.set(); worker.player.cancel.set()


if __name__ == '__main__': main()
