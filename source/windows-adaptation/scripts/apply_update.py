"""Offline update of an existing Windows bundle, with locks and recoverable backup."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]


def update(target):
    target=Path(target).expanduser().resolve();app=target/'app';core=app/'official-web-replay'
    if not core.is_dir() or not (app/'deploy-config.json').is_file():raise ValueError('请选择已经配置好的Windows完整环境根目录，不是源码目录')
    config=json.loads((app/'deploy-config.json').read_text(encoding='utf-8'))
    if config.get('native_transport')!='mumu-nativebridge-v1':raise ValueError('本更新包只用于已有MuMu Windows适配环境')
    os.environ['ROYALE_REPLAY_CONFIG']=str(app/'deploy-config.json')
    sys.path.insert(0,str(core))
    import portable_config
    import platform_lock
    manifest=json.loads((ROOT/'update-manifest.json').read_text(encoding='utf-8'))
    for relative,expected in manifest.items():
        file=ROOT/'project'/relative
        if file.is_symlink() or not file.resolve().is_relative_to((ROOT/'project').resolve()):raise ValueError('非法源路径')
        if hashlib.sha256(file.read_bytes()).hexdigest()!=expected:raise ValueError('更新包校验失败：'+relative)
    with contextlib.ExitStack() as stack:
        for path in (core/'console-runs/desktop.lock',portable_config.operation_lock()):
            path.parent.mkdir(parents=True,exist_ok=True)
            handle=stack.enter_context(path.open('a+b'))
            try:platform_lock.flock(handle,platform_lock.LOCK_EX|platform_lock.LOCK_NB)
            except BlockingIOError:raise RuntimeError('请先关闭回放控制台并等当前原生步骤结束；没有覆盖运行中的程序')
        backup=target/'state'/('update-backup-'+uuid.uuid4().hex);backup.mkdir(parents=True,exist_ok=False)
        checks=target/'manifest.json'
        catalog=json.loads(checks.read_text(encoding='utf-8')) if checks.is_file() else None
        if checks.is_file():shutil.copy2(checks,backup/'manifest.json')
        for relative,expected in manifest.items():
            if relative.startswith(('runtime/','console-runs/')) or relative=='deploy-config.json':raise ValueError('更新包不得覆盖实例配置、缓存或运行时')
            destination=app/relative
            if destination.is_symlink() or not destination.resolve().is_relative_to(app):raise ValueError('目标文件越界')
            if destination.exists():
                saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,saved)
            destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name(destination.name+'.update-'+uuid.uuid4().hex)
            shutil.copyfile(ROOT/'project'/relative,temporary);os.replace(temporary,destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=expected:raise RuntimeError('更新后校验失败：'+relative)
            if catalog is not None:catalog['files']['app/'+relative]=dict(bytes=destination.stat().st_size,sha256=expected)
        if catalog is not None:
            temporary=checks.with_suffix('.updated.json');temporary.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,checks)
        receipt=dict(updated_files=len(manifest),backup=str(backup),network_changed=False,game_apk_changed=False,runtime_preserved=True)
        (backup/'update-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target',required=True);args=parser.parse_args()
    print(json.dumps(update(args.target),ensure_ascii=False,indent=2))
