"""Private filesystem handoff from the opt-in browser native-messaging host.

No listening TCP port, browser-profile access or HTTP client. Jobs are claimed
once and retained; an interrupted claimed job is never silently replayed.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from browser_capture import save_capture, replay_url
from console_backend import STORE, PROJECT, Cancelled

from portable_config import bridge_queue
DIRECTORY = bridge_queue()


def valid_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value: raise ValueError('桥接任务编号无效')
    return value


def status_path(directory, identifier):
    return Path(directory) / (valid_id(identifier) + '.status.json')


def update_status(directory, identifier, state, message):
    path = status_path(directory, identifier)
    value = dict(ok=True, job_id=identifier, state=state, message=str(message)[:4000],
                 worker_pid=os.getpid(), updated_at=time.time())
    fd, name = tempfile.mkstemp(prefix='status-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(value, f, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def pending_jobs(directory=DIRECTORY):
    directory = Path(directory)
    if not directory.is_dir(): return []
    result = []
    for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime):
        if path.name.endswith('.status.json'): continue
        try:
            identifier = valid_id(path.stem)
            status = json.loads(status_path(directory, identifier).read_text(encoding="utf-8"))
            state = status.get('state')
            if state == 'queued': result.append(path)
            elif state in ('validating', 'preparing') and status.get('worker_pid') != os.getpid():
                update_status(directory, identifier, 'needs_review', '上次控制台在处理中退出；为避免重复提交，没有自动重试。请检查游戏后手动重发。')
        except (ValueError, OSError, KeyError): continue
    return result


def process_job(player, path, emit, *, project=PROJECT, captures=STORE/'web-html',enqueue=None):
    path = Path(path); identifier = valid_id(path.stem); directory = path.parent
    update_status(directory, identifier, 'validating', '控制台已收到页面，正在核对回放数据。')
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get('schema') != 'official-web-replay.bridge-job.v1' or doc.get('job_id') != identifier or doc.get('command') != 'capture-play':
            raise ValueError('桥接任务格式无效')
        tag, url = replay_url(doc.get('source_url'))
        html_path = directory / (identifier + '.html')
        if html_path.is_symlink() or not 0 < html_path.stat().st_size <= 25 * 1024 * 1024: raise ValueError('桥接 HTML 路径或大小无效')
        raw = html_path.read_bytes()
        if tag != doc.get('replay_tag') or hashlib.sha256(raw).hexdigest() != doc.get('source_sha256'): raise ValueError('桥接 HTML 编号或校验和不一致')
        result = save_capture(raw.decode('utf-8'), url, project=project, directory=captures)
        emit('downloaded', result)
        if enqueue is not None:
            enqueue(result['path'])
            update_status(directory,identifier,'pending_playback','已加入待播队列；本场尚未播放，未覆盖当前战斗。')
            return
        update_status(directory, identifier, 'preparing', 'HTML 已完整保存，正在准备官服原生回放。')
        player.play(result['path'], 1)
        update_status(directory, identifier, 'playing', '原生回放已就绪，请在安卓1观看。关闭浏览器弹窗不会停止播放。')
    except Cancelled:
        update_status(directory, identifier, 'cancelled', '已取消；等待已提交的原生步骤安全结束。')
        raise
    except Exception as exc:
        update_status(directory, identifier, 'failed', '未开始播放：' + str(exc))
        raise
