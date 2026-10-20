"""Discover/reconnect only the existing Android1's configured loopback ADB.

No port-range scan, public hosts, adb kill-server, emulator launch, or network
setting change. Resolve before a NEW client observation; never move a live
native task or its old process pointers to a newly discovered client.
"""
import subprocess
import time


def device_states(output):
    rows={}
    for line in output.splitlines():
        fields=line.split()
        if len(fields)>=2 and fields[1] in ('device','offline','unauthorized','recovery','sideload'):
            if fields[0] in rows:raise RuntimeError('ADB设备序号重复，停止自动选择')
            rows[fields[0]]=fields[1]
    return rows


def checked_binding(binding):
    port=binding.get('adb_port')
    if (not isinstance(binding.get("instance_name"),str) or not binding.get("instance_name") or type(port) is not int or not 1024<=port<=65535
        or binding.get('serial')!='127.0.0.1:'+str(port)):
        raise ValueError('自动ADB连接仅允许已有安卓1配置中的本机端口')
    return binding


def resolve_device(binding_loader,*,timeout=8):
    if not 0<timeout<=15:raise ValueError('bounded ADB discovery timeout required')
    deadline=time.monotonic()+timeout;attempted=set();last='未连接'
    while True:
        binding=checked_binding(binding_loader());serial=binding['serial']
        output=subprocess.check_output(['adb','devices','-l'],text=True,timeout=5)
        state=device_states(output).get(serial)
        if state=='unauthorized':raise RuntimeError('安卓1需要在模拟器内确认ADB授权；不会自动接受授权')
        if state=='device':
            if binding_loader()==binding:return binding
        elif serial not in attempted:
            # Only this exact loopback endpoint was read from Android1's own
            # settings. Other attached devices are neither selected nor reset.
            attempted.add(serial)
            result=subprocess.run(['adb','connect',serial],text=True,stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,timeout=5)
            last=(result.stdout or '').strip()[-300:]
        if time.monotonic()>=deadline or len(attempted)>3:
            raise RuntimeError('未发现已就绪的“我的安卓-1”ADB。请保持现有模拟器开启；已自动尝试其当前本机端口。'+last)
        time.sleep(.3)
