"""Read-only, bounded diagnostic ZIP. No backend, ADB, root or network imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import zipfile

VERSION='2026.10.19-hotfix3'
RUN=re.compile(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{8}')
ATTEMPT=re.compile(r'(?:bootstrap|scene)-v[1-9][0-9]{0,6}')
MAX_FILE=4*1024*1024
MAX_TOTAL=16*1024*1024
MAX_FILES=256


def snapshot(root,path):
    root=Path(root).absolute();path=Path(path).absolute()
    relative=path.relative_to(root)
    cursor=root
    for part in relative.parts:
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('linked record refused')
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_FILE:raise ValueError('oversized/nonregular record')
        raw=stream.read(MAX_FILE+1);after=os.fstat(stream.fileno())
    if len(raw)>MAX_FILE or len(raw)!=before.st_size or (
            before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(
            after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('record changed')
    return raw


def export_diagnostics(store,output,*,core=None,run=None):
    store=Path(store).absolute();output=Path(output).absolute()
    if output.suffix.lower()!='.zip':raise ValueError('请选择新的 .zip 文件名')
    if output.exists():raise FileExistsError('保存位置已有文件；请换一个 ZIP 文件名，原文件未改动')
    core=Path(core).absolute() if core is not None else store.parent
    if core!=store.parent:raise ValueError('core must be the owner of console-runs')
    if store.is_symlink() or core.is_symlink():raise ValueError('linked diagnostic root refused')
    notes=[];selected={};attempts=[]
    if run is not None:
        run=Path(run).absolute()
        if run.parent!=store or not RUN.fullmatch(run.name) or run.is_symlink():raise ValueError('foreign run refused')
    elif store.is_dir():
        children=list(store.iterdir())
        if len(children)>8192:raise ValueError('too many run entries; choose a task explicitly')
        runs=[p for p in children if RUN.fullmatch(p.name) and p.is_dir() and not p.is_symlink()]
        run=max(runs,key=lambda p:p.stat().st_mtime_ns) if runs else None
    if run and run.is_dir():
        children=list(run.iterdir())
        if len(children)>4096:raise ValueError('too many task entries')
        for path in children:
            # Never recurse into HTML/queue/cache/runtime/toolchain directories.
            if (path.suffix=='.json' and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,110}\.json',path.name)
                and path.name not in ('config.json','deploy-config.json')) or path.name in ('console.log','error.txt'):
                selected['task/'+path.name]=path
        log=run/'console.log'
        if log.is_file():
            try:
                text=snapshot(store,log).decode('utf-8',errors='replace')
                attempts=list(dict.fromkeys(re.findall(r'\b(?:bootstrap|scene)-v[1-9][0-9]{0,6}\b',text)))[-32:]
            except (OSError,ValueError) as error:notes.append('Cannot inspect task log: '+type(error).__name__)
        owned=run/'owned-scene.json'
        if owned.is_file():
            try:
                attempt=json.loads(snapshot(store,owned)).get('attempt','')
                if isinstance(attempt,str) and ATTEMPT.fullmatch(attempt):attempts.append(attempt)
            except (OSError,ValueError) as error:notes.append('Cannot inspect scene reference: '+type(error).__name__)
    for attempt in sorted(set(attempts)):
        for suffix in ('result','binding','component','source-execution','loader-binding'):
            path=core/(attempt+'-'+suffix+'.json')
            if path.is_file():selected['attempts/'+path.name]=path
    for name in ('timing-policy.json','timing-overrides.json'):
        path=core/name
        if path.is_file():selected['environment/'+name]=path
    data={};total=0
    for name,path in sorted(selected.items()):
        try:
            if len(data)>=MAX_FILES or path.stat().st_size>MAX_TOTAL-total:raise ValueError('bundle limit')
            raw=snapshot(core,path)
            if len(raw)>MAX_TOTAL-total:raise ValueError('bundle limit')
            data[name]=raw;total+=len(raw)
        except (OSError,ValueError) as error:notes.append('Skipped '+name+': '+type(error).__name__)
    report=dict(schema='royale-replay.diagnostic-export.v1',version=VERSION,
        platform=platform.system(),architecture=platform.machine(),python=platform.python_version(),
        selected_run=run.name if run else None,records=len(data),uncompressed_bytes=total,
        source_html_included=False,game_binaries_included=False,browser_data_included=False,
        network_requests=False,game_operations=False,atomic_checkpoint=False,notes=notes,
        privacy='Contains private paths, process addresses and parsed replay records. Share privately.')
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name,raw in data.items():bundle.writestr(name,raw)
        bundle.writestr('REPORT.json',json.dumps(report,ensure_ascii=False,indent=2))
        bundle.writestr('SHA256SUMS.txt',''.join(hashlib.sha256(raw).hexdigest()+'  '+name+'\n' for name,raw in data.items()))
    return dict(path=str(output),records=len(data),bytes=output.stat().st_size,partial=bool(notes))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(export_diagnostics(args.store,args.output),ensure_ascii=False))
