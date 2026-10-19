"""Offline Windows host checks. Never contacts Android or changes networking."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def validate_device_abi(value):
    if value!='arm64-v8a':
        raise ValueError('当前原生适配仅支持 arm64-v8a；x86/x86_64 或翻译层不能视为兼容。')


def inspect(config_path,probe_tools=True):
    config_path=Path(config_path).resolve()
    cfg=json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    ndk=Path(cfg['ndk_bin']) if cfg.get('ndk_bin') else None
    def executable(key):
        value=cfg.get(key)
        return bool(value and Path(value).is_file())
    checks=dict(windows_x64=platform.system()=='Windows' and platform.machine().lower() in ('amd64','x86_64'),
        python=sys.version_info>=(3,12),configuration=config_path.is_file(),adb=executable('adb_path'),lldb=executable('lldb_path'))
    try:
        import tkinter
        checks['tkinter']=True
    except ImportError:checks['tkinter']=False
    checks['ndk_compiler']=bool(ndk and (ndk/'clang++.exe').is_file())
    checks['ndk_readelf']=bool(ndk and (ndk/'llvm-readelf.exe').is_file())
    properties=ndk.parents[4]/'source.properties' if ndk and len(ndk.parents)>=5 else None
    accepted=('30.0.16248370','27.3.13750724') if cfg.get('native_transport')=='mumu-nativebridge-v1' else ('30.0.16248370',)
    checks['ndk_revision']=bool(properties and properties.is_file() and any(version in properties.read_text(encoding='utf-8') for version in accepted))
    server_arch='x86_64' if cfg.get('native_transport')=='mumu-nativebridge-v1' else 'aarch64'
    checks['ndk_debugger']=bool(ndk and len(list(ndk.parent.glob('lib/clang/*/lib/linux/'+server_arch+'/lldb-server')))==1)
    binding=Path(cfg['device_binding_file']) if cfg.get('device_binding_file') else None
    checks['device_selection']=False
    if binding and binding.is_file():
        from adb_discovery import checked_binding
        try:
            selected=json.loads(binding.read_text(encoding='utf-8'));port=selected['adbPort']
            checked_binding(dict(instance_name=selected['vmName'],adb_port=port,serial='127.0.0.1:'+str(port)))
            checks['device_selection']=(selected.get('schema')=='royale-replay.local-binding.v1' and selected['vmName']==cfg.get('instance_name'))
        except (KeyError,ValueError,TypeError):pass
    checks['lldb_python_android']=False
    details={}
    if probe_tools and checks['windows_x64'] and checks['lldb']:
        # A standalone local LLDB interpreter, without target or connection.
        from portable_config import prepare_lldb_environment
        prepare_lldb_environment(cfg)
        commands=[cfg['lldb_path'],'-b','-o','platform list','-o',
                  'script import lldb,json,sys; print("RR_PY_OK_v1"); print(sys.version)','-o','quit']
        try:
            done=subprocess.run(commands,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=25)
            checks['lldb_python_android']=(done.returncode==0 and 'RR_PY_OK_v1' in done.stdout and 'remote-android' in done.stdout
                and not any(word in done.stdout.lower() for word in ('traceback','error:','not supported')))
            details['lldb_probe']=done.stdout[-4000:]
        except (OSError,subprocess.SubprocessError) as error:details['lldb_probe']=str(error)
    checks['native_transport']=cfg.get('native_transport','arm64-native') in ('arm64-native','mumu-nativebridge-v1')
    core_ready=all(checks.values());runtime=config_path.parent/'runtime/native/runtime-profile.json'
    return dict(checks=checks,host_ready=core_ready,runtime_prepared=runtime.is_file(),playback_verified=False,
                windows_execution_verified=False,device_contacted=False,network_requests=False,details=details)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parent.parent/'deploy-config.json')
    args=parser.parse_args();report=inspect(args.config)
    print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['host_ready'] else 2)


if __name__=='__main__':main()
