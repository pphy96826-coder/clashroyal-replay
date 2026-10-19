"""Avoid Windows ADB's text-mode stdin for bounded binary read requests."""
import re
import subprocess
import uuid
from pathlib import Path


def read_batch(adb,reader,pid,generation,payload):
    from portable_config import windows,deployment_id
    if not windows():
        return subprocess.check_output(adb+['shell','-T',reader,str(pid),generation],input=payload,timeout=10)
    if not re.fullmatch(r'/data/local/tmp/cr_readonly_mem_[a-f0-9]{16}',reader):raise ValueError('unbound read-only binary')
    if type(pid) is not int or not 0<pid<1<<22 or not str(generation).isdigit():raise ValueError('invalid read process generation')
    if not 4<=len(payload)<=4+4096*12:raise ValueError('excessive binary read request')
    token=uuid.uuid4().hex
    folder=Path(__file__).resolve().parent/'build-readonly-memory/requests'
    folder.mkdir(parents=True,exist_ok=True)
    local=folder/(token+'.bin')
    directory='/data/local/tmp/royale_replay_mem_requests_'+deployment_id()
    remote=directory+'/'+token+'.bin'
    with local.open('xb') as file:file.write(payload)
    try:
        subprocess.run(adb+['shell','mkdir','-p',directory],check=True,capture_output=True,timeout=10)
        subprocess.run(adb+['shell','chmod','700',directory],check=True,capture_output=True,timeout=10)
        subprocess.run(adb+['push',str(local),remote],check=True,capture_output=True,timeout=15)
        return subprocess.check_output(adb+['exec-out',reader+' '+str(pid)+' '+str(generation)+' < '+remote],timeout=10)
    finally:
        # Only these exact, newly created request files are removed.
        subprocess.run(adb+['shell','rm','-f',remote],capture_output=True,timeout=10)
        local.unlink(missing_ok=True)
