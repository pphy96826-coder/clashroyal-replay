"""Line-delimited local JSON bridge for the native macOS window (no sockets)."""
import platform_lock as fcntl
import json
import os
import sys
import threading
import time
import traceback
from console_backend import Cancelled, OperationLock, Player, STORE, PROJECT, owned_scene_state, scene_metadata
from browser_capture import save_capture
from bridge_queue import DIRECTORY as BRIDGE_DIRECTORY, pending_jobs, process_job, update_status
from replay_lifecycle import ClientUnavailable,client_generation,clear_playback
from pathlib import Path


class Worker:
    def __init__(self):
        self.output_lock = threading.Lock(); self.state_lock = threading.Lock()
        self.busy = False; self.playback = None; self.log = None
        self.last_request=None
        self.stop_requested = threading.Event()
        self.bridge_current = None
        self.bridge_preparing = False
        self.closed = threading.Event(); self.player = Player(self.emit)

    def emit(self, kind, value):
        with self.output_lock:
            if kind == 'run': self.log = STORE / os.path.basename(value) / 'console.log'
            if kind in ('playing', 'resumed'): self.playback = value
            if kind == 'stopped': self.playback = None
            if kind=='downloaded':self.last_request=dict(command='play',html=value['path'],speed=1)
            if kind=='playback_ended' and self.bridge_current:
                update_status(BRIDGE_DIRECTORY,self.bridge_current,'complete' if value.get('reason')=='complete' else 'cancelled',value['message'])
            if self.bridge_current and ((kind == 'status' and self.bridge_preparing) or
                                        (kind in ('complete', 'stopped') and not self.bridge_preparing)):
                state = 'preparing' if kind == 'status' else 'complete' if kind == 'complete' else 'cancelled'
                message = str(value) if kind != 'complete' else '原生回放已经播放完毕。'
                try: update_status(BRIDGE_DIRECTORY, self.bridge_current, state, message)
                except OSError: pass
            if kind in ('status', 'log', 'error', 'stopped', 'cancelled','complete','playback_ended') and self.log:
                with self.log.open('a',encoding='utf-8') as f: f.write(time.strftime('[%H:%M:%S] ') + str(value) + '\n')
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
            except ClientUnavailable:
                self.stop_requested.clear();clear_playback(self,'closed')
            except Exception as exc:
                self.emit('log', traceback.format_exc()); self.emit('error', str(exc))
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
                            self.emit('playback_ended',dict(reason='stopped',can_replay=bool(self.last_request),client_refreshed=True,message='已退出回放，客户端已刷新。'))
                        except ClientUnavailable:clear_playback(self,'closed')
                        except Exception as error: self.emit('error', str(error))
                self.emit('busy', False)
        threading.Thread(target=run, daemon=False).start()

    def adopt(self):
        state = self.player.discover_owned()
        if state:
            self.emit('adopted', state)
            try:
                doc, metadata = scene_metadata(state['attempt'])
                path=doc.get('source_html')
                if path and Path(path).is_file():self.last_request=dict(command='play',html=path,speed=metadata['speed'])
                self.emit('match', doc); self.emit('resumed', metadata)
                self.emit('position', dict(state, duration=metadata['duration']))
                if state['tick']/20 >= metadata['duration']:
                    self.finish(metadata)
            except (ValueError, OSError, KeyError) as exc:
                self.emit('log', '已有回放仍保留；未恢复输入信息：' + str(exc))

    def finish(self,current):
        """Called under OperationLock; reset only the proven owned client."""
        self.emit('complete',current);self.playback=None
        self.bridge_current=None
        self.player.cancel.clear()
        try:
            self.player.stop_owned()
            self.emit('playback_ended',dict(reason='complete',can_replay=bool(self.last_request),client_refreshed=True,
                message='回放已完成，客户端已刷新。请选择重新回放或退出回放。'))
        except ClientUnavailable:clear_playback(self,'closed')

    def command(self, doc):
        kind = doc.get('command')
        if kind in ('capture-play', 'capture-save'):
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
                    self.playback = None
                    self.player.play(result['path'], speed)
                else: self.emit('status', 'HTML 已保存，可在控制台点击播放。')
            self.launch(capture)
        elif kind in ('play','replay'):
            if kind=='replay':
                if not self.last_request:raise ValueError('没有可重新播放的回放，请先选择文件。')
                doc=dict(self.last_request)
            html, speed = doc.get('html'), doc.get('speed', 1)
            if not isinstance(html, str) or speed not in (.25, .5, 1, 2, 4):
                raise ValueError('文件或倍速不正确')
            if self.busy:
                self.emit('error', '当前步骤仍在进行，请等待或取消。'); return
            self.player.cancel.clear()
            self.last_request=dict(command='play',html=html,speed=speed)
            self.bridge_current = None
            self.playback = None
            self.launch(lambda: self.player.play(html, speed))
        elif kind in ('stop','exit'):
            if kind=='exit':self.last_request=None
            with self.state_lock:
                running = self.busy
                if running:
                    self.stop_requested.set(); self.player.cancel.set()
            if running:
                self.emit('status', '已请求取消，等待当前原生步骤安全结束…')
            else:
                def stop():
                    if not self.player.active and not self.player.discover_owned():
                        self.playback=None
                        self.emit('playback_ended',dict(reason='exit',can_replay=bool(self.last_request),client_refreshed=False,message='已退出回放，可选择其他文件。'));return
                    self.player.new_folder(); self.player.stop_owned()
                    self.emit('playback_ended',dict(reason='stopped',can_replay=bool(self.last_request),client_refreshed=True,message='已退出回放，客户端已刷新。'))
                self.launch(stop)
        elif kind == 'shutdown':
            self.closed.set(); self.player.cancel.set()
        else: raise ValueError('未知控制台操作')

    def poll_playback(self):
        if self.busy or not self.playback:return
        current=self.playback
        try:
            from console_backend import read_json,ROOT
            identity=read_json(ROOT/(current['attempt']+'-binding.json'))['identity']
            generation=client_generation(identity)
            if generation!='current':clear_playback(self,generation);return
            state=owned_scene_state(current['attempt'])
            if self.playback is current:
                self.emit('position',dict(state,duration=current['duration']))
                if state['tick']/20>=current['duration']:
                    self.launch(lambda:self.finish(current))
        except Exception as exc:
            if self.busy:return
            self.emit('log','回放状态已结束：'+str(exc));clear_playback(self,'unavailable')

    def monitor(self):
        while not self.closed.wait(1):self.poll_playback()

    def bridge_monitor(self):
        while not self.closed.wait(1):
            if self.busy: continue
            jobs = pending_jobs()
            if not jobs: continue
            path = jobs[0]
            def action(path=path):
                self.bridge_current = path.stem
                self.bridge_preparing = True
                self.player.cancel.clear()
                try: process_job(self.player, path, self.emit)
                finally: self.bridge_preparing = False
            self.launch(action)


def main():
    os.umask(0o077)
    STORE.mkdir(parents=True, exist_ok=True)
    lock = (STORE/'desktop.lock').open('a+b')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({'event': 'fatal', 'value': '回放控制台已打开，请使用现有窗口。'}, ensure_ascii=False), flush=True); return
    worker = Worker(); worker.emit('ready', '就绪 · 请选择已保存的 RoyaleAPI 回放 HTML')
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
