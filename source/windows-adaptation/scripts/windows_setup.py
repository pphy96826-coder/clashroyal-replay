"""Windows source installer. No downloads, registry writes, device access or VM launch."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import uuid
import venv

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'project/official-web-replay'))
from adb_discovery import checked_binding
from windows_doctor import inspect


def read_binding(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'));port=data['adbPort']
    checked_binding(dict(instance_name=data['vmName'],adb_port=port,serial='127.0.0.1:'+str(port)))
    if data.get('schema')!='royale-replay.local-binding.v1':raise ValueError('invalid device binding schema')
    return data


def install(args):
    if platform.system()!='Windows' or platform.machine().lower() not in ('amd64','x86_64'):
        raise RuntimeError('Windows x64 installation is required; Mac tests do not count as Windows deployment')
    if sys.version_info<(3,12):raise RuntimeError('Python 3.12+ required')
    target=args.target.expanduser().absolute()
    if target.exists() or target.is_symlink():raise FileExistsError('choose a new target; existing deployment left intact')
    if len(target.parts)<2 or target==target.parent:raise ValueError('use a specific named deployment directory')
    binding=read_binding(args.binding_file)
    for tool in (args.adb,args.lldb):
        if not tool.is_file():raise FileNotFoundError(tool)
    if not (args.ndk_bin/'clang++.exe').is_file():raise FileNotFoundError('Windows NDK clang++.exe missing')
    shutil.copytree(ROOT/'project',target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','console-runs','build-readonly-memory'))
    identifier=uuid.uuid4().hex
    cfg=dict(deployment_id=identifier,debug_port=49000+int(identifier[:8],16)%10000,
        ndk_bin=str(args.ndk_bin.resolve()),adb_path=str(args.adb.resolve()),lldb_path=str(args.lldb.resolve()),
        device_binding_file=str(args.binding_file.resolve()),instance_name=binding['vmName'],
        python=str(target/'.venv/Scripts/python.exe'),platform='windows-x64',browser_bridge_enabled=False,
        native_transport=args.transport)
    config_path=target/'deploy-config.json';config_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report=inspect(config_path)
    (target/'host-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not report['host_ready']:
        print(json.dumps(report,ensure_ascii=False,indent=2))
        raise RuntimeError('host prerequisites failed; retained source/configuration for inspection, no device contacted')
    venv.EnvBuilder(with_pip=False,symlinks=False).create(target/'.venv')
    command='@echo off\r\nsetlocal\r\n"%~dp0.venv\\Scripts\\python.exe" -X utf8 "%~dp0official-web-replay\\windows_console.py"\r\nif errorlevel 1 pause\r\n'
    (target/'Start-Replay.cmd').write_bytes(command.encode('ascii'))
    result=dict(windows_console_installed=True,source=str(target),runtime_prepared=False,
                playback_verified=False,network_changed=False,device_contacted=False)
    (target/'installation-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    selected=sub.add_parser('select-device');selected.add_argument('--output',type=Path,required=True)
    selected.add_argument('--name',required=True);selected.add_argument('--port',type=int,required=True)
    doctor=sub.add_parser('doctor');doctor.add_argument('--config',type=Path,required=True)
    install_parser=sub.add_parser('install')
    install_parser.add_argument('--transport',choices=('arm64-native','mumu-nativebridge-v1'),default='arm64-native')
    for flag in ('target','binding-file','adb','lldb','ndk-bin'):install_parser.add_argument('--'+flag,type=Path,required=True)
    args=parser.parse_args()
    if args.action=='select-device':
        checked_binding(dict(instance_name=args.name,adb_port=args.port,serial='127.0.0.1:'+str(args.port)))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(dict(schema='royale-replay.local-binding.v1',vmName=args.name,adbPort=args.port),stream,ensure_ascii=False,indent=2)
        print('Device selection saved; no connection attempted.')
    elif args.action=='doctor':
        report=inspect(args.config);print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['host_ready'] else 2)
    else:install(args)


if __name__=='__main__':main()
