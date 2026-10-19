"""Bounded read-only liveness checks; stale processes never inherit ownership."""
import subprocess

PACKAGE='com.tencent.tmgp.supercell.clashroyale'
class ClientUnavailable(RuntimeError):pass

def client_generation(identity):
    adb=['adb','-s',identity['serial']]
    try:
        result=subprocess.run(adb+['shell','pidof',PACKAGE],capture_output=True,text=True,timeout=2)
        pids=result.stdout.split()
        if result.returncode==1 and not pids:return 'closed'
        if result.returncode or not pids:return 'unavailable'
        if pids!=[str(identity['pid'])]:return 'replaced'
        stat=subprocess.check_output(adb+['shell','cat',f"/proc/{identity['pid']}/stat"],text=True,timeout=2)
        return 'current' if stat[stat.rfind(')')+2:].split()[19]==identity['process_start_time'] else 'replaced'
    except (subprocess.SubprocessError,OSError,IndexError):return 'unavailable'

def clear_playback(worker,reason):
    worker.playback=None;worker.player.active=None
    worker.emit('playback_ended',dict(reason=reason,can_replay=bool(worker.last_request),client_refreshed=False,
        message='客户端已关闭，已退出回放。可重新回放或选择其他文件。' if reason in ('closed','replaced') else '设备连接已中断，已退出回放等待。'))
