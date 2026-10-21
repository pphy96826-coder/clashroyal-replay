"""Verified x86 Android host compiler cross-builds ARM64 inside the instance."""
from pathlib import Path
import os
import subprocess
from mumu_platform import enabled,arm_stubs,native_compiler


def run(command,*,stdout,stderr=subprocess.STDOUT,check=True,timeout=60):
    command=list(map(str,command))
    if not enabled():return subprocess.run(command,stdout=stdout,stderr=stderr,check=check,timeout=timeout)
    if not command[0].endswith('/bin/clang++') or command.count('-o')!=1:
        raise ValueError('unsupported MuMu compiler invocation')
    output=Path(command[command.index('-o')+1])
    sources=[v for v in command if v.endswith(('.cpp','.c'))]
    if not sources or len(sources)>8 or not output.parent.is_dir():
        raise ValueError('invalid bounded compilation inputs')
    if output.exists():raise FileExistsError('preserve existing native output')
    if '--target=aarch64-linux-android24' not in command:
        raise ValueError('only audited ARM64 target is supported')
    driver,linker,environment=native_compiler()
    command[0]=str(driver)
    command=[('--ld-path='+str(linker)) if value.startswith('--ld-path=') else '-gline-tables-only' if value=='-g' else value for value in command]
    command[1:1]=['-fintegrated-cc1','-fno-crash-diagnostics','-ccc-install-dir',str(driver.parent),'-L'+str(arm_stubs())]
    environment=dict(environment)
    for key in ('TMPDIR','HOME'):
        if key in os.environ:environment[key]=os.environ[key]
    return subprocess.run(command,stdout=stdout,stderr=stderr,check=check,timeout=timeout,env=environment)
